# Set up UI testing

Turn on `adw_sdlc`'s browser test for this repo: when a change touches the UI, code starts the app, the `ui_tester` agent (Sonnet + Playwright MCP) uses it like a user and screenshots a verdict per check, and failures go back to the builder with the screenshots. Until this is done, the phase is skipped and the run log says so.

Do every step, in order, in the **target repo root**, after `/sssf install`. Ask the engineer only for what you cannot read from the repo.

## How it works (read once)

```
plan (ui_impact, ui_checks) -> build -> test loop
  -> code(ui_scope)   planner said ui_impact OR a changed file matches UI_APP.frontend_paths?
       no  -> skipped, nothing spent
       yes -> code(start_app)  UI_APP.argv on a free port, polled until it answers
              -> ui_tester ⇄ builder(ui_fix)   bounded, screenshots ride in the envelope
              -> app stopped (always)
  -> review -> commits -> push -> PR (UI results in the body)
```

| Piece | Where | Owner |
|---|---|---|
| How to start the app, what counts as frontend | `UI_APP` in `adws/adw_modules/quality.py` | you, per repo |
| Tester agent: model, tools | `ui_tester` in `adws/adw_sssf_config/sssf.claude.config.yaml` | stamped, ready |
| Playwright MCP server | `adws/adw_data/harness_engineering/playwright.mcp.json` | stamped, ready |
| Tester prompts | `adws/adw_data/prompt_engineering/ui_tester/` | stamped, edit freely |
| Start/stop, scope decision | `adws/adw_modules/ui.py` | factory code |

The tester has `Read` plus every Playwright tool except `browser_run_code_unsafe` (it runs arbitrary code outside the browser). No shell, no edits, `writes: []`. Screenshots go to `adws/adw_data/sessions/<adw_id>/context_handoff/screenshots/`, never the repo. UI testing needs the Claude Code roster; the pi roster has no `ui_tester`.

## Step 1 — Prerequisites

```bash
claude --version                 # Claude Code CLI on PATH (or CLAUDE_CODE_PATH in .env)
node --version && npx --version  # the MCP server runs via npx
npx -y @playwright/mcp@latest --help >/dev/null && echo mcp-ok
npx -y playwright install chromium   # the browser the MCP drives, once per machine
```

## Step 2 — Find how the app starts

Read the repo, do not guess: `package.json` scripts (`dev`, `start`, `preview`), `justfile`/`Makefile`, `docker-compose.yml`, framework config (`vite.config.*`, `next.config.*`), the README. You need:

1. **The dev-server command** and **how it takes a port** — a flag (`--port 3000`), the `PORT` env var, or neither (hard-coded; then find the config and make it read `PORT`, or ask the engineer).
2. **The page to start on** — usually `/`; a health or login page if `/` redirects.
3. **The frontend paths** — the directories and file types whose change means "the UI changed".
4. **What else must be running** — a backend API, a database, env vars. The command must bring up everything the UI needs, from a fresh worktree.

Common shapes:

| Stack | argv |
|---|---|
| Vite | `["npm", "run", "dev", "--", "--port", "{port}", "--strictPort"]` |
| Next.js | `["npx", "next", "dev", "-p", "{port}"]` |
| Bun server reading PORT | `["bun", "run", "apps/web/server.ts"]` |
| Static files | `["python3", "-m", "http.server", "{port}", "-d", "public"]` |
| Frontend + API | a script that starts both, e.g. `["npm", "run", "dev:all"]` with the frontend on `$PORT` |

## Step 3 — Set `UI_APP` in `adws/adw_modules/quality.py`

```python
UI_APP = UiAppSpec(
    argv=["npm", "run", "dev", "--", "--port", "{port}", "--strictPort"],
    ready_path="/",
    frontend_paths=["apps/web/", "src/components/", "*.css", "*.tsx"],
    startup_timeout_seconds=90,      # raise it for slow first builds
)
```

Rules — the same as every block in `quality.py`:

- **argv list, bare binary names.** `{port}` is replaced with a free port, also exported as `PORT`. Never hard-code a port: two worktree runs at once would collide.
- **It runs in the run's worktree**, a fresh checkout of the branch. If the app needs installed dependencies, make the command install them (`["sh", "-c", "npm ci && npm run dev -- --port $PORT"]`) or the first run fails with missing modules.
- **No `.env` in the worktree.** The worktree is a fresh checkout, and `.env` is gitignored. The ADW process loads the main checkout's `.env` and the app inherits that environment, so variables are available. A framework that reads `.env` FILES itself (Vite, Next) won't find them; copy the file in your command (`cp ../../../../.env .env && ...`) or have the framework read `process.env`.
- `frontend_paths`: trailing `/` = directory prefix, `*` = glob, anything else = exact path. Too narrow and a UI change slips through when the planner misses it; too wide and backend-only runs pay for a browser.

## Step 4 — Prove the app starts the way the factory starts it

From the repo root, with your real argv:

```bash
PORT=4567 <your command with {port} replaced by 4567> &
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:4567/   # must be < 500
kill %1
```

Fix the command until this works from a clean checkout (`git stash -u` first if the tree is dirty, or test inside `git worktree add /tmp/uicheck HEAD`).

## Step 5 — Check the tester's harness

Open `adws/adw_sssf_config/sssf.claude.config.yaml` and confirm the `ui_tester` entry exists with `harness_engineering: [adws/adw_data/harness_engineering/playwright.mcp.json]`. Adjust only if the app needs it:

- **Viewport**: `--viewport-size` in `playwright.mcp.json` (default `1280x800`).
- **Browser**: add `"--browser", "firefox"` (or `webkit`, `msedge`) to the args; install it with `npx playwright install <name>`.
- **Login**: if the app needs auth, add the test credentials to the `ui_tester` prompts (`system.md`), never to the plan. Prefer a seeded test user.

`{{context_handoff_dir}}` in the MCP config is rendered per run — leave it. `--output-dir` points at the same `screenshots/` folder the tester is told to use, so Playwright's output never lands in the repo.

## Step 6 — Smoke test

Pick a tiny, real UI change in this repo and run it locally, without a PR:

```bash
uv run adws/adw_sdlc.py --config adws/adw_sssf_config/sssf.claude.config.yaml --no-pr \
  "<a small visible change, e.g. change the main heading text to 'Hello SSSF'>"
```

Green means:

```bash
sqlite3 adws/adw_data/sssf.db "select seq, name, status from phases where adw_id='<id>' order by seq;"
```

shows `ui_scope`, `start_app`, `ui_test_1` (and `ui_fix_N` if it found something), all `success`, and the screenshots exist under `adws/adw_data/sessions/<id>/context_handoff/screenshots/`. Open one and confirm it shows your change.

Then a backend-only request: `ui_scope` should log `run_ui_test: False` and no `start_app` phase should appear.

## When it fails

| Symptom | Cause | Fix |
|---|---|---|
| `ui_scope` logs "UI_APP is not set up" | `UI_APP.argv` is empty | Step 3 |
| `start_app` fails: "exited N before answering" | command crashed — the log tail is in the error, full log at `context_handoff/ui_app.log` | missing deps (install in the command), wrong cwd, or missing env |
| `start_app` fails: "did not answer within Ns" | slow first build, wrong `ready_path`, or the app ignores the port | raise `startup_timeout_seconds`; make it honor `{port}`/`PORT` |
| `ui_test` gate: "screenshot not found" / "must be under …" | tester used a relative filename | it re-prompts the same session automatically; if it persists, strengthen the screenshot rule in `ui_tester/system.md` |
| `permission_breach` in `ui_test` | something wrote into the repo (usually a relative screenshot) | same as above |
| validation: `MCP config not found` | `playwright.mcp.json` missing | re-run install, or restore it from the skill's `templates/harness_engineering/` |
| tester can't reach the page | app binds to `localhost` IPv6 only, or a different host | bind to `127.0.0.1`, or change `ready_path`/the URL host in `ui.py` |
