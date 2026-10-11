# README: Prerequisites section under Install

## What changed and why

`README.md` now has a short `### Prerequisites` subsection directly under `## Install`. It lists the tools the factory needs, one bullet per tool:

- `uv`, which runs every factory script.
- Claude Code (`claude`) or `pi`, the coding agent that runs each phase.
- `sqlite3`, for querying the trace db at `adws/adw_data/sssf.db`.
- `git`, needed by chains that end in a commit phase.
- `gh`, needed only for workflows that open pull requests.
- `bun`, needed only for the dashboard (the trace visualizer).

Before this change, the prerequisites appeared only in a single `**Prereqs:**` line under "Manual Install". A reader following the agentic path had no list to check against. The new section puts the list at the top of Install.

## Files

- `README.md`: adds the `### Prerequisites` heading and six bullets (9 inserted lines). No other lines are changed.
- `specs/6755aff0_readme-prerequisites-section.md`: the plan this change followed (new file, 56 lines). It is a planning artifact, not runtime documentation.

The existing `**Prereqs:**` line under "Manual Install" is unchanged. It also covers API keys, which the new section does not mention.

## How to use or verify

- `grep -n "^## Install" -A 3 README.md` should show `### Prerequisites` after the blank line that follows the heading.
- `grep -c "^### Prerequisites" README.md` should print `1`.
- `git diff --stat` should list only `README.md` and the spec file, with insertions only.

This is a docs-only change. No code, tests, or config were touched.
