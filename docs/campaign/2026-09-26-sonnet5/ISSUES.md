# Sonnet 5 campaign: issues and decisions

The Luna campaign's issues (I-01 to I-37) are in `../2026-09-25/ISSUES.md`.
Entries here are numbered S-xx.

### S-01 Scope and settings (user decisions, 2026-09-26)
- Claude Code 2.1.283, `claude-sonnet-5`, effort `medium`, in both conditions,
  on the user's Claude subscription (OAuth token from `claude setup-token`).
- 1 rep (120 runs) to begin with; more reps only if usage limits allow.
- Luna used effort `max`. Pass rates are therefore not comparable across the
  two campaigns. The A-vs-B comparison within each campaign is unaffected.
- Phase 1 (fixed-candidate agreement) does not depend on the model and is
  reused from Luna. Phases 4 and 5 are run again.

### S-02 SecureBench Claude Code harness brought to parity with upstream (before rep 1)
The harness had not been used in a campaign before. Changes, each matching the
upstream Harbor/Pier `ClaudeCode` agents:
- `effort` option, passed as `--effort`.
- `prompt: instructions`, so the prompt is the row's public instructions
  verbatim (as Codex got in Luna), placed after a `--` separator.
- `IS_SANDBOX=1`, so `--dangerously-skip-permissions` runs as root.
- `--verbose --output-format stream-json` instead of one final JSON object,
  so a run cut off by the timeout still has a record of its events.
- `FORCE_AUTO_BACKGROUND_TASKS=1` and `ENABLE_BACKGROUND_TASKS=1`, passed
  through `harness.env`.

### S-03 Agent HOME drift found in the smoke test and fixed (before rep 1)
Details in Luna ISSUES I-37. The Codex and Claude Code harnesses replaced the
image's HOME, which hid `/root/.gitconfig`, `~/go`, `~/.rustup` and more.
SecureBench fix-git failed on "Committer identity unknown" while native
passed. After the fix, the Go module cache, cargo and the git identity are
visible in the SecureBench agent containers, and fix-git passes in both
conditions. The smoke runs (before and after the fix) are kept in
`runs/campaign-sonnet5-smoke/` and are not counted.

### S-04 One smoke-test capture was rejected without a logged reason (not reproduced)
The first post-fix SecureBench cattrs run ended with
`candidate_capture_done status=rejected`. The Oracle then graded an empty
candidate: all 12 cases were `candidate_error`. Capture swallowed the
`CandidateCaptureError` message, and the stopped workspace had already been
removed. A rerun captured normally; that run failed on a real `case_9`
divergence. The rejection reason is now written to the progress event
(`reason`, host-side only) and to `campaign-events.jsonl`, so if it recurs in
rep 1 the cause will be visible.

### S-05 Subscription handling
- The driver drops `ANTHROPIC_API_KEY` and `ANTHROPIC_AUTH_TOKEN` from the child
  env and sets `CLAUDE_FORCE_OAUTH=1`, so no run can bill the API.
- A run that ends on a usage limit is set aside (`<task>.usage-limit-<t>`) and
  redone after the reset. It does not use an infrastructure retry, and no new
  run starts before the reset.
- `cost_usd` is Claude Code's API-price estimate (`total_cost_usd`); it was not billed.
- Native passes the real OAuth token into the agent container (upstream
  behaviour); SecureBench keeps it in the host relay. `key_scan` checks for the
  token under `runs/campaign-sonnet5/`. Revoke the token after the campaign.

### S-06 Usage accounting with background tasks
Background tasks split one session into several `result` events. The last one
carries the session totals (tokens, `total_cost_usd`). `num_turns` is per
segment and is summed. A run killed before any `result` event falls back to
summed per-message usage, which undercounts output tokens: a lower bound.

### S-07 Rep 1 restarted at 04:17 to fix limit detection and usage flags (recorded)
Rep 1 started at 04:12. Five minutes in, two driver problems showed up:
- **Limit detection:** a subscription limit hit would have been recorded as a
  genuine agent failure. Claude Code's newer limit text ("You've hit your
  limit · resets …") matched no marker. The driver now also reads the
  `rate_limit_event` stream event: any status other than `allowed`/
  `allowed_warning` marks the run as model_api, and `resetsAt` gives the exact
  pause time.
- **Usage flags:** a SecureBench run whose bounded stdout cut the stream (a
  655 KB base64 image line in financial-document-processor; Luna I-28) was
  marked `usage_known` with partial counts. `usage_known` now requires a
  `result` event, the same rule as Luna.

The driver and its children were stopped. Five runs were already finished;
their records were rebuilt with the new parser (verdicts unchanged). The 5
in-flight runs were set aside as `<task>.interrupted-<t>` and are not counted.
Rep 1 was relaunched with the same seed and schedule.

At 04:15 the stream reported the subscription's seven-day window at 66%
utilization, resetting 2026-09-27 17:00 CEST.

### S-08 SecureBench's 1 MiB agent-stdout bound drops most usage totals (open; needs a decision)
`MAX_COMMAND_OUTPUT_BYTES = 1024 * 1024` (`securebench/sandboxes/base.py:19`)
bounds the agent stdout the host keeps. Upstream-style `--verbose` stream-json
is much larger than Codex's event stream. A 14-minute DeepSWE session
(happy-dom rep 1) reached the bound exactly (1,047,899 bytes) before its final
`result` event. Those runs get `usage_known=false`, so B's token figures
cover only runs that stayed under 1 MiB (mostly short TB runs), while A's
cover all runs.

Verdicts are unaffected. The agent keeps running, and the candidate is
captured from the stopped workspace, not from stdout. This is the Luna I-28
limitation, made much more frequent by stream-json. The bound is a framework
constant, not a tester-config setting; changing it is the user's call (see
the memory rule on limits). The report states token comparisons as
known-usage-only.

### S-09 On agent crash or timeout, SecureBench grades nothing and upstream grades the stopped state (open; policy decision)
In SecureBench skrub-duration-encoding rep 1, the Claude Code process aborted
after 613 s (`Aborted (core dumped)` on stderr, no other diagnostic; the
container and core file are gone). `extract_candidate` raises
`CandidateProductionError` on any non-zero exit
(`securebench/candidates/extraction.py:84`) and `CandidateProductionTimeout` on
timeout. No candidate is captured, and the Oracle scores an empty submission
(all cases `candidate_error`). Upstream Harbor/Pier still run the verifier on
whatever the agent left, including committed work after an
`AgentTimeoutError`.

This is deliberate, tested behaviour
(`tests/test_v2_harness_bridge.py:281`), and the Luna campaign had it too:
4 SecureBench `producer_timeout` runs scored with no candidate, while native
graded its 3 agent timeouts. It is left unchanged for this campaign, so that
B is the same system in both campaigns and within the rep. The report counts
such runs separately.

The 1 MiB stdout bound (S-08) was reached just before the abort
(1,048,386 bytes). The bounded reader keeps draining the pipe past the bound
(`_BoundedOutput.append`), so it does not stall or kill the agent. The abort
is recorded as a Claude Code crash of unknown cause.

Decision needed: whether SecureBench should capture the stopped state after a
non-zero exit or a timeout, as upstream does. That is an architecture change
(stopped-state capture is already the model), with test updates.

### S-10 Capture rejected work over untracked build output (fixed after rep 1; 3 SecureBench runs redone)
Rep 1 had 10 SecureBench runs that graded no candidate. Three were stopped-
workspace captures rejected over files git never commits:
- **fd-deterministic-multi-key-sorting** and **pest-character-class-coalescing:**
  `candidate workspace exceeds max_changed_bytes: 138038171 > 134217728` (and
  142903125). Cargo's `target/` was counted. fd passed natively.
- **python-statemachine-state-data-scoping:**
  `candidate symlink target escapes tree: .venv/bin/python -> /usr/local/bin/python3`.
  The virtualenv that uv creates, ignored through `.venv/.gitignore`.

Capture copied the whole working tree and staged it with `git add --all
--force`, so ignored build output, virtualenvs and caches counted toward
bounds and symlink checks. Upstream grades commits, which cannot contain
them.

Fix (`securebench/candidates/capture.py`, `_WorktreeIgnore`): during the
stopped-worktree walk, untracked paths that git ignores are skipped. Git runs
with the trusted baseline's git directory and the workspace as work tree, so
the candidate's `.gitignore` files are read as data and its `.git` (config,
hooks, fsmonitor) is never used. Symlinked `.gitignore` files are not
followed. Skipping only drops untracked content: baseline-tracked paths are
always captured, and every captured path still passes the path and symlink
policy. Tests: `tests/test_v2_candidates.py`, the last four tests. None of the
30 DeepSWE reference patches adds an ignored path (checked against each
image), so Phase 1 is unaffected.

The three runs were redone for SecureBench only, with the originals kept as
`<task>.capture-rejected-superseded-<t>`. This is treated like an
infrastructure retry: the lost candidate was a harness defect. Caveat: it
gives these three B runs a second agent sample while A keeps its first.

The other 7: skrub, mashumaro, feal-linear-cryptanalysis and gpt2-codegolf
exited non-zero or timed out (S-09, unchanged). db-wal-recovery,
extract-moves-from-video and mteb-leaderboard never wrote their answer file:
genuine agent outcomes. db-wal-recovery destroyed the WAL it had to recover by
opening the live database. mteb-leaderboard gave up after Claude Code's
WebSearch/WebFetch were unavailable (`allow_external_tools: false`, as in
Luna); native used them, then cloned from GitHub.

Luna impact (see Luna I-38): the same silent rejections are in the Luna
SecureBench runs. python-statemachine had no candidate in all 3 reps, fd in
rep 3, hf-model-inference in reps 2-3.

### S-11 Five SecureBench infrastructure retries before the agent started (recorded)
Five SecureBench attempts ended in `task_internal_error` within seconds of
starting, before any agent command: helm-unified-manifest-stream at 05:08,
the three capture-fix reruns at 13:48, and fd again at 13:49. Each was retried
automatically and then ran normally. `sb_run` did not keep the event's
`error_type`, so the exception class is not recorded; it keeps it now. No
agent work was lost. The 13:48 cluster coincided with three SecureBench runs
starting at the same moment.

### S-12 Code changed during the campaign (recorded)
`FREEZE.md` was written at 04:12, before rep 1. These changes came later, each
described above:
- the driver's limit detection and usage flags (S-07, 04:17; the rep restarted);
- producer/capture fields in records and the `rebuild` command (records rebuilt
  after rep 1, verdicts unchanged);
- the capture fix for ignored paths (S-10, after rep 1; 3 SecureBench runs redone);
- rejection reasons and `error_type` in progress events.

Every counted SecureBench run used the S-02/S-03 harness (image HOME, parity
flags). Of the counted runs, only the three S-10 reruns used the capture fix.
None of the other 57 SecureBench captures contained an ignored path large
enough to matter: none was rejected, and in the 7 no-candidate runs the
causes were agent exit or missing answer files (S-09, S-10).
