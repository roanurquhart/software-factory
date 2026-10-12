# Plan Task

## Variables

### prompt

{{prompt}}

### previous_envelope

{{previous_envelope}}

### context_handoff_dir

{{context_handoff_dir}}

### records

{{records}}

## Task

Plan the work described in `prompt`.

1. Write the full plan to `<context_handoff_dir>/plan.md` — this is the copy the builder reads.
2. **Only when `records` is `repo`:** copy that file into the repo under `specs/`. When `records` is `session`, skip this step entirely and write nothing in the repo: `<context_handoff_dir>/plan.md` is the record, and the ADW seals it.
   - **List `specs/` before you pick the name.** A session that plans more than once reuses its `<adw_id>`, so the obvious name may already be taken.
   - Base name: `specs/<adw_id>_<slug>.md`, where `<adw_id>` is the session directory name inside `context_handoff_dir` (`.../sessions/<adw_id>/context_handoff`) and `<slug>` is two to four kebab-case words naming the work.
   - If a file with that name already exists, use `specs/<adw_id>_<slug>_v2.md`, then `_v3`, and so on until the name is free. **Never overwrite an existing spec** — the earlier plan is the record of what was asked for then.
   - **Copy it, do not retype it.** One bash call does the whole step:
     `mkdir -p specs && cp "<context_handoff_dir>/plan.md" "specs/<adw_id>_<slug>.md"`
     Writing the plan a second time through `write` re-emits every line you already wrote, which costs the whole document again in output tokens and lets the two copies drift.
3. Decide `ui_impact`: true when the work changes anything a user sees or does in the app's UI (pages, components, styles, client behaviour). When true, list `ui_checks` — each one a single behaviour a tester can observe in a browser ("Clicking Reset sets the counter to 0"), not an implementation detail. Backend-only work: `ui_impact: false`, `ui_checks: []`.
4. Emit your `Report` JSON. `artifacts` holds `<context_handoff_dir>/plan.md`, plus the `specs/` copy when `records` is `repo`.

## Report

Respond with ONLY valid JSON matching `PlanOutput` — no prose before or after:

```json
{
  "status": "success",
  "summary": "<one sentence describing the plan>",
  "artifacts": ["<context_handoff_dir>/plan.md", "specs/<adw_id>_<slug>.md"],
  "commit_message": "<imperative one-line git subject for committing THIS PLAN DOCUMENT, not the work it describes — e.g. 'Add spec for the /health endpoint'>",
  "notes_for_next_agent": "<what the builder must know>",
  "ui_impact": false,
  "ui_checks": ["<one observable browser behaviour per entry; empty when ui_impact is false>"]
}
```

Both `artifacts` entries are the paths you ACTUALLY wrote, `_v2` suffix and all. Gates open these files — a name you meant to use fails them.
