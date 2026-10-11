"""Claude Code interface — the second coding agent, same contract as agent_pi.

Runs `claude -p --output-format stream-json --verbose` and tails its JSONL
stdout line by line, forwarding each event to a callback while the agent
works. Takes a PiRequest and returns a PiResult so agents.execute() drives
both coding agents through one code path.

Tool restriction is two layers, both from the agent's `tools` list:
  --tools          which built-in tools exist at all (base names: Read, Bash)
  --allowedTools   what may run without asking; entries may carry Claude Code
                   permission-rule syntax, e.g. `Bash(git diff:*)`
With --permission-mode dontAsk, anything not allowed is denied, never prompted.
--restricted drops user/project settings and confines file tools to the repo;
--strict-mcp-config drops every MCP server. The agent sees only what it names.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Callable, Optional

from .agent_pi import ARG_VALUE_CHARS, RESULT_SNIPPET_CHARS, _clip, _label
from .data_types import PiRequest, PiResult
from .utils import now_iso, operator_env

CLAUDE_CODE_PATH = os.environ.get("CLAUDE_CODE_PATH", "claude")
PROVIDER = "anthropic"

# SSSF thinking levels -> Claude Code --effort (low | medium | high | xhigh | max)
EFFORT = {"off": "low", "minimal": "low", "low": "low", "medium": "medium",
          "high": "high", "xhigh": "xhigh", "max": "max"}


def resolve_model(pattern: str) -> str:
    """`anthropic/claude-opus-5-5` -> `claude-opus-5-5`. Provider must be anthropic."""
    provider, _, model_id = pattern.partition("/")
    if provider != PROVIDER or not model_id:
        raise ValueError(f"model {pattern!r} must be written anthropic/<model-id> "
                         "for coding_agent: claude_code")
    return model_id


def check_installed() -> None:
    if not shutil.which(CLAUDE_CODE_PATH):
        raise ValueError(f"claude CLI not found ({CLAUDE_CODE_PATH!r}) — install Claude Code "
                         "or set CLAUDE_CODE_PATH")


def tool_flags(tools: Optional[list[str]]) -> list[str]:
    """`["Read", "Bash(git diff:*)"]` -> --tools Read,Bash --allowedTools Read "Bash(git diff:*)"."""
    if tools is None:
        return []                            # None = Claude Code's full default set
    base = list(dict.fromkeys(t.split("(", 1)[0] for t in tools))
    flags = ["--tools", ",".join(base)]
    if tools:
        flags += ["--allowedTools", *tools]
    return flags


def _cc_session_id(session_id: str) -> str:
    """Claude Code wants a UUID; derive a stable one from the SSSF session id."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, session_id))


def _result_text(content) -> str:
    if isinstance(content, str):
        return content
    return "".join(part.get("text", "") for part in content or []
                   if isinstance(part, dict) and part.get("type") == "text")


class ToolCallTracker:
    """Folds Claude Code's stream into ONE record per completed tool call.

    A call is announced as a `tool_use` block in an assistant message and
    finished by the matching `tool_result` block in the next user message.
    """

    def __init__(self) -> None:
        self._open: dict[str, dict] = {}

    def observe(self, event: dict) -> list[dict]:
        """Returns a record per tool call this event finished — one user
        message can close several parallel calls."""
        etype = event.get("type")
        if etype not in ("assistant", "user"):
            return []                        # system events carry `message` as a plain string
        content = (event.get("message") or {}).get("content") or []
        if etype == "assistant":
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    self._open.setdefault(str(block.get("id")), {
                        "tool": block.get("name") or "tool",
                        "args": block.get("input") or {},
                        "started_at": now_iso(),
                        "clock": time.monotonic(),
                    })
            return []
        return [self._close(block) for block in content
                if isinstance(block, dict) and block.get("type") == "tool_result"]

    def _close(self, block: dict) -> dict:
        call_id = str(block.get("tool_use_id") or "")
        opened = self._open.pop(call_id, {})
        tool = opened.get("tool", "tool")
        args = opened.get("args", {})
        record = {
            "tool": tool,
            "tool_call_id": call_id,
            "args": {key: _clip(value, ARG_VALUE_CHARS) if isinstance(value, str) else value
                     for key, value in args.items()},
            "ok": not block.get("is_error", False),
            "label": _label(tool, args),
        }
        text = _result_text(block.get("content"))
        if text:
            record["result_snippet"] = _clip(text, RESULT_SNIPPET_CHARS)
        record["ended_at"] = now_iso()
        if opened.get("clock"):
            record["duration_ms"] = int((time.monotonic() - opened["clock"]) * 1000)
        if opened.get("started_at"):
            record["started_at"] = opened["started_at"]
        return record


def _context_tokens(usage: dict) -> int:
    return int(sum(usage.get(part) or 0 for part in (
        "input_tokens", "output_tokens",
        "cache_read_input_tokens", "cache_creation_input_tokens")))


def run(request: PiRequest, on_event: Optional[Callable[[dict], None]] = None,
        on_spawn: Optional[Callable[[int], None]] = None,
        on_exit: Optional[Callable[[int], None]] = None) -> PiResult:
    """Run one non-interactive Claude Code turn. First call creates the session,
    later calls with the same session_id resume it — same context window."""
    model_id = resolve_model(request.model)
    cc_session = _cc_session_id(request.session_id)

    # Claude Code has no create-or-continue flag, so a marker records that the
    # session exists. It lives in the agent's runtime dir, next to the run record.
    marker = Path(request.session_dir) / f"{cc_session}.started"
    resuming = marker.exists()

    cmd = [
        CLAUDE_CODE_PATH, "-p", "--output-format", "stream-json", "--verbose",
        "--model", model_id,
        "--effort", EFFORT.get(request.thinking, "medium"),
        "--permission-mode", "dontAsk",
        "--restricted", "--strict-mcp-config",
        *tool_flags(request.tools),
    ]
    for directory in request.add_dirs:
        cmd += ["--add-dir", directory]
    if resuming:
        cmd += ["--resume", cc_session]      # the recorded system prompt is reused
    else:
        cmd += ["--session-id", cc_session, "--system-prompt", request.system_prompt]
    cmd += ["--", request.prompt]

    raw_path = Path(request.raw_output_path)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    marker.parent.mkdir(parents=True, exist_ok=True)

    result = PiResult(session_id=request.session_id)
    seen_messages: set[str] = set()
    final: dict = {}
    # stdin DEVNULL for the same reason as agent_pi: a non-TTY stdin can make
    # the CLI wait forever for piped input.
    process = subprocess.Popen(cmd, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, bufsize=1, cwd=request.cwd,
                               env=operator_env())
    if on_spawn:
        on_spawn(process.pid)
    with raw_path.open("a") as raw:
        assert process.stdout is not None
        for line in process.stdout:
            raw.write(line)
            raw.flush()
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            etype = event.get("type")
            if etype == "system" and event.get("subtype") == "init":
                marker.touch()
            elif etype == "assistant":
                message = event.get("message") or {}
                # Each content block arrives as its own event carrying the same
                # message usage, so occupancy is read once per message id.
                if message.get("id") not in seen_messages:
                    seen_messages.add(message.get("id"))
                    turn = _context_tokens(message.get("usage") or {})
                    if turn:
                        result.context_tokens = turn
            elif etype == "result":
                final = event
            if on_event:
                on_event(event)

    stderr = process.stderr.read() if process.stderr else ""
    result.returncode = process.wait()
    if on_exit:
        on_exit(process.pid)

    # Spend comes from the result event: it is per-send and already deduplicated.
    result.text = final.get("result") or ""
    usage = final.get("usage") or {}
    result.usage.input_tokens = usage.get("input_tokens") or 0
    result.usage.output_tokens = usage.get("output_tokens") or 0
    result.usage.cache_read_tokens = usage.get("cache_read_input_tokens") or 0
    result.usage.cache_write_tokens = usage.get("cache_creation_input_tokens") or 0
    result.usage.reasoning_tokens = (usage.get("output_tokens_details") or {}).get("thinking_tokens") or 0
    result.usage.total_tokens = _context_tokens(usage)
    result.usage.total_cost = final.get("total_cost_usd") or 0.0
    result.tokens = result.usage.total_tokens
    result.cost = result.usage.total_cost
    model_usage = (final.get("modelUsage") or {}).get(model_id) or {}
    result.context_window = int(model_usage.get("contextWindow") or 0)

    if (result.returncode != 0 or final.get("is_error")) and not result.text:
        raise RuntimeError(f"claude exited {result.returncode}: {stderr.strip()[-800:]}")
    return result
