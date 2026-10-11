# UI Test Task

## Variables

### prompt

{{prompt}}

### previous_envelope

{{previous_envelope}}

### context_handoff_dir

{{context_handoff_dir}}

## Task

Verify every check in `previous_envelope.checks` against the running app at `previous_envelope.url`.

1. Read `previous_envelope.plan_path` if it is set, for what the change is meant to do.
2. For each check: drive the browser to the state it describes, confirm it with a snapshot, and save a screenshot to `previous_envelope.screenshots_dir` using an absolute filename.
3. Emit your `Report` JSON — one `checks` entry per check in the brief, in the same order.

## Report

Respond with ONLY valid JSON matching `UiTestOutput` — no prose before or after:

```json
{
  "status": "success",
  "passed": false,
  "summary": "<one sentence: N of M UI checks passed>",
  "checks": [
    {
      "check": "<the check, in the brief's words>",
      "passed": false,
      "observed": "Clicked Reset with count at 3; count still shows 3. Expected 0.",
      "screenshot": "<screenshots_dir>/01_reset-button.png"
    }
  ],
  "artifacts": ["<screenshots_dir>/01_reset-button.png"],
  "notes_for_next_agent": "<for the builder: what to fix, referencing the screenshots>"
}
```

`status` is `success` when the testing itself completed — it is not the verdict. The verdict is `passed`, true only when every check passed.
