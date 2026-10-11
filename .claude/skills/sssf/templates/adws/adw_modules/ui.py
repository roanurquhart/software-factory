"""UI testing plumbing: decide whether the UI phase runs, and serve the app for it.

Both halves are code. Whether the UI changed is a question the diff answers —
the planner's `ui_impact` is intent, `UI_APP.frontend_paths` against the real
changed files is fact, and either one is enough to run the phase. Starting the
app is a known command, so the ui_tester is handed a URL and nothing else.
"""

from __future__ import annotations

import fnmatch
import os
import signal
import socket
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from . import git_helper
from .data_types import EventRecord, PlanOutput, UiTestBrief, UiTestOutput
from .quality import UI_APP
from .utils import operator_env

LOG_TAIL_CHARS = 2_000


@dataclass
class App:
    url: str
    pid: int
    log_path: Path


def configured() -> bool:
    return bool(UI_APP.argv)


def _matches(path: str, pattern: str) -> bool:
    if pattern.endswith("/"):
        return path.startswith(pattern)
    return fnmatch.fnmatch(path, pattern) if "*" in pattern else path == pattern


def changed_since(base: str) -> list[str]:
    """Every file the run changed: tracked diffs against base, plus untracked."""
    return list(dict.fromkeys(git_helper.diff_files(base) + git_helper.untracked_files()))


def touched(plan: PlanOutput, changed: list[str]) -> tuple[bool, str]:
    """(run the UI phase?, why). Planner intent OR frontend files in the diff."""
    frontend = [f for f in changed
                if any(_matches(f, p) for p in UI_APP.frontend_paths)]
    if frontend:
        return True, f"frontend files changed: {', '.join(frontend[:5])}"
    if plan.ui_impact:
        return True, "planner marked the work ui_impact"
    return False, "no frontend files changed and the planner marked no ui_impact"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _tail(path: Path) -> str:
    return path.read_text(errors="replace")[-LOG_TAIL_CHARS:] if path.exists() else ""


def start(run) -> App:
    """Start the app on a free port in the run's tree and wait until it answers.

    A free port per run, so two worktree runs never fight over :3000.
    """
    port = _free_port()
    argv = [arg.replace("{port}", str(port)) for arg in UI_APP.argv]
    log_path = run.context_handoff_dir / "ui_app.log"
    env = {**operator_env(), "PORT": str(port)}
    with log_path.open("w") as log:
        # Own process group, so stop() takes down whatever the command spawned
        # (npm -> node -> vite) and not just the wrapper.
        process = subprocess.Popen(argv, cwd=run.repo_root, env=env, stdin=subprocess.DEVNULL,
                                   stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    run.tracer.process_start(run.adw_id, "code", "ui_app", process.pid, " ".join(argv))
    app = App(url=f"http://127.0.0.1:{port}{UI_APP.ready_path}", pid=process.pid,
              log_path=log_path)

    deadline = time.monotonic() + UI_APP.startup_timeout_seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stop(run, app)
            raise RuntimeError(f"UI app exited {process.returncode} before answering:\n"
                               f"{_tail(log_path)}")
        try:
            with urllib.request.urlopen(app.url, timeout=2) as response:
                if response.status < 500:
                    return app
        except urllib.error.HTTPError as error:
            if error.code < 500:
                return app
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(0.5)
    stop(run, app)
    raise RuntimeError(f"UI app did not answer {app.url} within "
                       f"{UI_APP.startup_timeout_seconds}s:\n{_tail(log_path)}")


def stop(run, app: App) -> None:
    """Terminate the app's whole process group; never raises."""
    try:
        os.killpg(app.pid, signal.SIGTERM)
        for _ in range(20):
            os.killpg(app.pid, 0)            # raises once the group is gone
            time.sleep(0.25)
        os.killpg(app.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    run.tracer.process_end(run.adw_id, app.pid)
    run.tracer.event(EventRecord(adw_id=run.adw_id,
                                 phase_id=run.phases[-1].phase_id if run.phases else "",
                                 type="log", name="ui_app_stopped",
                                 payload={"pid": app.pid, "log": str(app.log_path)}))


def brief(plan: PlanOutput, app: App, run, changed: list[str]) -> UiTestBrief:
    """The ui_tester's input envelope: URL, checks, and where screenshots go."""
    screenshots = run.context_handoff_dir / "screenshots"
    screenshots.mkdir(parents=True, exist_ok=True)
    plan_path = run.context_handoff_dir / "plan.md"
    checks = plan.ui_checks or ["The change described in the plan renders and works in the browser."]
    return UiTestBrief(
        status="success",
        summary=f"App is running at {app.url}. Verify {len(checks)} UI check(s).",
        url=app.url,
        checks=checks,
        plan_path=str(plan_path) if plan_path.exists() else "",
        changed_files=changed,
        screenshots_dir=str(screenshots.resolve()),
        notes_for_next_agent=("Save every screenshot under screenshots_dir with an ABSOLUTE "
                              "filename. One verdict per check, each with its screenshot."),
    )


def as_fix_request(result: UiTestOutput) -> UiTestOutput:
    """The tester's report, re-addressed to the builder.

    The screenshots are the point: a builder fixing from the tester's words
    alone repairs what it guesses, not what rendered. So the opening line it
    reads names every failing screenshot and tells it to look first.
    """
    failing = [c for c in result.checks if not c.passed]
    shots = [c.screenshot for c in failing if c.screenshot]
    look = ("FIRST open each of these screenshots with the Read tool — they show what "
            "the browser actually rendered: " + ", ".join(shots) + ". ") if shots else ""
    return result.model_copy(update={
        "notes_for_next_agent": (f"{look}Then fix every failing check below; `observed` is "
                                 f"what the tester saw. Tester's notes: "
                                 f"{result.notes_for_next_agent}"),
    })
