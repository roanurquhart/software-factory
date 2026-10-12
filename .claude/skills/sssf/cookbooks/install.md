# Install

`/sssf install` — stamp the entire factory out of the skill and into the current working directory.

## Run it

```bash
uv run .claude/skills/sssf/scripts/install.py
```

Run from the **target repo root** — the cwd is where everything lands. If the skill lives in your user scope, the path is `~/.claude/skills/sssf/scripts/install.py`.

### Keep the factory out of the repo: `--local`

```bash
uv run .claude/skills/sssf/scripts/install.py --local
```

Use this when the factory is your personal workflow and the repo should not carry it (a shared or public repo). Two things change:

- **Nothing is committed for the factory.** Instead of appending to `.gitignore` (which is itself committed), `--local` writes `adws/`, `justfile`, `.env.sample`, `.env`, `.sssf/`, the bytecode patterns and, if present, `.claude/skills/sssf/` to `.git/info/exclude`. That file is per clone, never committed, and shared by every worktree. It warns about anything already committed, since excluding a path does not untrack it.
- **Plans and write-ups stay in the session.** Both configs are set to `records: session`: the planner and documenter keep their records in the run's `context_handoff/` instead of copying them into `specs/` and `app_docs/`, and the PR body carries them. A run commits only the product change.

Every check still holds. Runs execute from the main checkout (worktrees never need the factory), protected files are fingerprinted by content rather than through `git status`, and records are sealed by hash instead of by commit. See `references/config.md` → `records` and → Write permissions.

## What gets stamped

`install.py` copies `templates/` into the cwd:

| Stamped | From | Tracked? |
|---|---|---|
| `adws/adw_sssf_config/sssf.config.yaml` | `templates/sssf.config.yaml` | yes — the agent roster |
| `.env.sample` | `templates/env.sample` | yes |
| `adws/adw_*.py` | `templates/adws/` | yes — the fourteen starter ADWs |
| `adws/adw_modules/` | `templates/adws/adw_modules/` | yes — all low-level logic |
| `adws/adw_data/prompt_engineering/{planner,builder,scout,reviewer,documenter}/` | `templates/prompt_engineering/` | yes — **the user-owned home for prompts** |
| `adws/adw_data/harness_engineering/` | `templates/harness_engineering/` | yes — **the user-owned home for pi extensions** |
| `justfile` | `templates/justfile` | yes — starter recipes: `just demo`, the workflows, the trace reads, `just obs` |
| `adws/adw_data/sessions/`, `adws/adw_data/sssf.db` | created at runtime | no — gitignored |

"Tracked" is the default install. With `--local`, none of these are tracked: they are excluded in `.git/info/exclude` instead.

The two `*_engineering` dirs mirror the two config keys of the same name: `prompt_engineering` is what an agent is told, `harness_engineering` is what its harness can do. Both are yours the moment they are stamped. Edit them in `adws/adw_data/`, never back inside the skill.

`harness_engineering/` ships with `subagents.ts` — the pi extension backing `subagent_create` / `_continue` / `_list` / `_remove`, wired to the planner and scout in the starter roster.

## Idempotency

Re-running is safe. `install.py` skips **every** file that already exists — your config, your prompts, and previously stamped code alike — and reports what it skipped, so a second run doubles as a drift check. To refresh stamped code (`adw_modules/`, the starter `adw_*.py`) to the skill's current version, run with `--force` — but know that `--force` overwrites ALL existing stamped files, including `sssf.config.yaml` and `prompt_engineering/`, so commit or back up user-owned edits first.

## Post-install checklist

1. **Env** — `cp .env.sample .env`, then set `OPENROUTER_API_KEY` in `.env`. (A `claude_code` roster needs no key — it uses your Claude Code login. Set `CLAUDE_CODE_PATH` only if `claude` is not on PATH.)
2. **Pi is installed and on PATH** — `pi --version`. Set `PI_PATH` in `.env` if it is not.
3. **The model resolves** — the config's default `gemini-3.6-flash` must be a registered id in `~/.pi/agent/models.json`. Check with `pi --list-models` or read the file directly; see `references/config.md` for model resolution.
4. **Gitignore** — `install.py` appends `adws/adw_data/sessions/`, `adws/adw_data/sssf.db*`, and `.env` for you; confirm they landed. All three are runtime or secrets and must never be committed. With `--local`, check `.git/info/exclude` instead and confirm `git status` shows nothing from the factory.
5. **Git repo** — ADWs that end in a commit phase call `git_helper.commit_all`, which raises if the cwd is not a git repository. Run `git init` and make a first commit before using `adw_plan_build.py`, `adw_plan_build_test.py`, or `adw_simple_sdlc.py`. `adw_document.py` needs one too: it measures the change with `git diff` against a base ref (`main` by default, `--base` to override).
6. **UI testing (optional)** — if this repo has a frontend and you will use `adw_sdlc`, follow [setup_ui_testing.md](setup_ui_testing.md) after the smoke test below. Until then the UI phase is skipped, and each run's log says so.
7. **Smoke test** — `just demo` runs two cheap read-only workflows back to back, or run the smallest ADW directly:

```bash
just demo                                                    # both, end to end
uv run adws/adw_prompt.py "reply with a one-line summary of this repo"   # the raw form
```

Green means the whole path works: config validated, session minted, Pi ran, envelope parsed, events landed in `adws/adw_data/sssf.db`. Verify the trace exists before trusting anything larger:

```bash
sqlite3 adws/adw_data/sssf.db "select adw_id, status from sessions order by started_at desc limit 1;"
```

If the smoke test fails, fix it before composing chains — every multi-agent ADW rides on this exact path.
