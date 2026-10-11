# Plan: Add a Prerequisites section to README.md

## Request
Add a short "Prerequisites" section to `README.md`, right after the `## Install` heading. It lists the tools the factory needs, one line each: uv, Claude Code (`claude`) or pi, sqlite3, git, gh for pull requests, and bun for the dashboard.

## Scope
- Change only **one file**: `README.md`.
- This is a docs-only change. No code, tests or UI change.

## Current state (README.md, lines 51–61)
```
## Install

Two steps: get the skill into your repo, then stamp the factory.

### Agentic Install
...
### Manual Install

**Prereqs:** [`uv`](...), [`pi`](...), `sqlite3`, and an API key ... [`bun`](https://bun.sh) only if you want the visualizer.
```

## Change
Put a new `### Prerequisites` subsection directly under `## Install`. It goes **before** the "Two steps: …" sentence, so it is the first thing after the heading. Use `###` because it sits under the `##` Install heading, at the same level as Agentic/Manual Install.

Insert this exact block:

```markdown
## Install

### Prerequisites

- [`uv`](https://docs.astral.sh/uv/) runs every factory script.
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) (`claude`) or [`pi`](https://github.com/mariozechner/pi-coding-agent) is the coding agent that runs each phase.
- `sqlite3` lets you query the trace db at `adws/adw_data/sssf.db`.
- `git` is needed by chains that end in a commit phase.
- [`gh`](https://cli.github.com/) is needed only for workflows that open pull requests.
- [`bun`](https://bun.sh) is needed only for the dashboard (the trace visualizer).

Two steps: get the skill into your repo, then stamp the factory.
```

Rules:
- One bullet line per tool, in the order above. No sub-bullets and no extra prose.
- Leave the existing `**Prereqs:**` line under `### Manual Install` (line 61) as it is. It also covers API keys, which this request does not ask about. Do not delete or rewrite it.
- Do not touch any other section.

## Out of scope (note only, do not fix)
The README still says Claude Code is "stubbed" / "v1 is Pi only" (around lines 151 and 365). But `.claude/skills/sssf/templates/adws/adw_modules/agent_cc.py` now contains a real `claude` CLI backend. Those older lines may be stale. Do not edit them in this change.

## Verification
1. `grep -n "^## Install" -A 3 README.md` shows a blank line and then `### Prerequisites` right after `## Install`.
2. `grep -n "^### Prerequisites" README.md` finds exactly one match.
3. The section has exactly 6 bullet lines, mentioning uv, claude/pi, sqlite3, git, gh and bun.
4. `git diff --stat` shows only `README.md` changed, with insertions only (about 9 lines).
5. The Markdown renders cleanly: links are well formed and there is a blank line before and after the list.
