# Campaign ISSUES

Suspected bugs, fidelity differences and evidence gaps found during the
campaign. Nothing listed here has been fixed; conversions, oracles, adapters and
the verifier are frozen for the campaign.

Status key: **open** (needs a decision), **recorded** (known difference, the
campaign proceeds and reports it).

## Phase 0

### I-01 Working tree has 31 DeepSWE rows; the campaign uses the 30 committed ones (recorded)
`benchmarks/deep-swe/tasks-v2.jsonl` in the working tree has 31 rows: the
uncommitted `obsidian-linter-auto-table-of-contents` is appended, and
`inventory.csv` is locally edited to mark it approved. The campaign uses the 30
rows at HEAD (`git show HEAD:benchmarks/deep-swe/tasks-v2.jsonl` →
`runs/campaign/ds-admitted-tasks-v2.jsonl`). The working tree is therefore not
clean at freeze; FREEZE.md records the dirty paths.

### I-02 `uv` is not installed (recorded)
The test suite was run with `.venv/bin/python -m pytest -q` instead of
`uv run --no-sync --with pytest python -m pytest -q`. Same interpreter and
packages as the installed venv.

### I-03 (resolved in campaign configs: per-task upstream memory_mb; capture cap = upstream storage_mb) "TerminalBench at 512 MiB" is the capture cap, not container memory (recorded)
Commit 645cfcb says "DeepSWE runs at 8g, TerminalBench at 512 MiB"; the 512 MiB
is `capture.max_candidate_bytes` (536870912) in the TB tester configs. No TB
config sets `docker.memory_limit`, so TB SecureBench runs so far used the
sandbox default of **1g** (`securebench/sandboxes/docker.py:288`). Upstream TB
gives 2048–8192 MB per task. Campaign configs set each task's upstream
`memory_mb` (see `configs/resources.csv`).

### I-04 SecureBench has no CPU limit; upstream sets per-task CPUs (open)
Upstream: DeepSWE 2 CPUs (agent and verifier); TB 1 CPU for every task except
rstan-to-pystan (4). Harbor and Pier enforce these under local Docker
(`--cpus`). SecureBench sandboxes pass `--memory` and `--pids-limit` but no CPU
limit, and the tester config has no CPU field. Under condition B, agents and
evaluation containers can use all 12 host CPUs. This affects wall time and any
CPU-bound task (crack-7z-hash, feal-linear-cryptanalysis, rstan-to-pystan,
build-heavy DeepSWE suites). Matching it requires a framework change (a
`docker.cpus` tester field), which is a decision for the user, or recording it
as a condition difference.

### I-05 `vulnerable-secret` row timeout is 1200 s; upstream is 900 s (recorded)
The campaign config sets `harness.config.timeout_seconds: 900`, which caps the
effective timeout at `min(row, config)` = 900 s. The row itself is unchanged.

### I-06 Seven TB rows use images that exist only on this machine (open)
log-summary-date-ranges, raman-fitting, protein-assembly, write-compressor,
mteb-leaderboard, mteb-retrieve and rstan-to-pystan pin bare local image IDs
(`securebench-wb-<row>:local`, built 2026-09-22). Their build contexts under
`benchmarks/terminal-bench/docker/<row>/` are byte-identical to upstream
`environment/`, but the images were rebuilt, so apt/pip package versions can
differ from upstream's published `alexgshaw/<row>:20251031` images (digests
differ; see `phase0/image-digests.tsv`). No tooling in the repo builds them, and
they cannot be pulled, so the SecureBench condition is not reproducible on
another machine. The native condition uses the published upstream image, so
these 7 rows differ in image between A and B. The other 53 rows: the upstream
tag resolves to exactly the SecureBench-pinned digest.

### I-07 DeepSWE capture: SecureBench takes the working tree, upstream takes commits only (accepted by user)
Upstream `pre_artifacts.sh` captures `git diff <base> HEAD`: uncommitted work is
dropped and graded as base (reward 0). SecureBench's git_patch capture takes the
final working tree. The instruction says "commit everything when you are done",
so a run that does not commit can pass in B and fail in A. Condition-A runs save
both the committed diff and the working-tree diff so Phase 5 can separate this.

### I-08 SecureBench capture drops test-file hunks (recorded)
`securebench/candidates/capture.py` drops edits under `exclude_paths` (e.g.
`tests/**`). Upstream's grader resets only the files that test.patch touches
before applying test.patch; other test-file edits by the agent survive. Phase 1
feeds the same candidate bytes to both verifiers, so this matters only for
Phase 5 (real agent output).

### I-09 Agent prompt and codex flags differ between conditions (recorded)
- B wraps the instruction in `task.json` plus a SecureBench preamble
  (`securebench/harnesses/shared.py:234`); A passes `instruction.md` verbatim.
  The DeepSWE instruction text is identical.
- Harbor/Pier run `codex exec ... --enable unified_exec`; SecureBench does not.
- Pier's codex defaults to effort `high`; campaign passes `max` explicitly.
- A: the API key enters the agent container (upstream design). B: the key stays
  in the host-side provider relay.

### I-10 TB network policy differs for some rows (accepted by user: intended hardening)
Upstream TB tasks all set `allow_internet = true` (unrestricted). SecureBench
rows: log-summary-date-ranges and write-compressor have `mode: none`; raman-fitting,
protein-assembly, mteb-leaderboard, mteb-retrieve, rstan-to-pystan are
`restricted` to named domains; the rest are `internet`, extended by the
tester-codex allowlist. DeepSWE: both conditions deny agent network (upstream
`no-network`; Pier allowlists only the model API).

## Phase 1 evidence gaps

### I-11 29 of 30 DeepSWE rows have no replayable malicious candidate (open)
Only go-critic has candidate-level malicious tests (`forged_success` ×3). The
other DeepSWE rows' "malicious" coverage is Oracle-level forged evidence
(hand-built `ChallengeEvidence`), which cannot be replayed through an upstream
verifier. TB malicious candidates are mostly content-level (forged verdict
files etc.) and are replayable; the generic capture-shape attacks (symlink,
type flip, oversize) are rejected at SecureBench capture and have no verdict to
compare.

### I-12 cancel-async-tasks: attack candidates intermittently yield infrastructure_error (open)
`tools.qualify_rows` marks the row **failing**. Three runs of
`tests/test_cancel_async_tasks_v2.py` with Docker gave different failing cases,
all with `infrastructure_error {'code': 'adapter_failed', 'message': 'Reviewed
protocol Adapter exited unsuccessfully'}` where `failed` is expected:
- run 1 (under load, qualify_rows): 2 failures
- run 2 (under load): `abandons_cleanup_mutant`, `credential_forgery`
- run 3 (idle host, after reboot): `early_cancellation` only

The row is nondeterministic for malicious/mutant candidates. This matters for the
campaign: infrastructure errors are retried and excluded rather than counted as
failures, so a candidate that can make the adapter exit non-zero turns a
rejection into an excluded run. Not fixed (frozen conversion).

### I-13 Host rebooted mid Phase 0 (recorded)
The host rebooted during the first Docker-suite run (kernel 7.0.0-29 → 7.0.0-31).
The partial log is `phase0/pytest-docker.killed-at-11pct.log` (3 failures in the
first ~200 tests, unnamed in `-q` output). The suite was restarted with `-v`.
TB qualification ran on the old kernel. FREEZE.md records the kernel at freeze.
A stopped `securebench-copy-*` container from the killed run remains.

### I-06 update: cause of the 7 local images (open, needs approval)
They are plain `docker build`s of the unmodified upstream Dockerfiles, made
2026-09-22, on newer base layers (python 3.13.15 / 2026 Debian snapshot vs
3.13.7 / 2025). They add no packages. Compared with the published upstream images:
`/app` and pip set identical for log-summary-date-ranges, raman-fitting,
protein-assembly, rstan-to-pystan; **`/app` differs for write-compressor**
(recompiled `decomp`); **pip set differs for mteb-leaderboard and mteb-retrieve**
(newer transitive deps). The dossiers name the upstream images. Proposed fix:
pin `alexgshaw/<row>@<upstream digest>` (mapping in `phase0/tb-image-swap.txt`)
in `benchmarks/terminal-bench/tasks-v2.jsonl` and the 6 test files that assert
the image, then requalify those 7 rows. The edit was blocked by the permission
classifier; awaiting user approval.

### I-14 Instruction text differs from upstream in 6 rows, plus the prompt wrapper in all 60 (open)
Diffs in `phase0/instruction-diff/<row>.diff`; full SecureBench prompts in
`<row>.securebench-prompt.txt`.
- Accidental, restorable: git-leak-recovery (newlines collapsed; list structure
  lost), helm-array-merge-strategies (backticks dropped around quoted strings),
  meriyah-explicit-resource-declarations ("script-global error" → "script-global
  scope error").
- Added for stopped replay: headless-terminal, hf-model-inference, kv-store-grpc
  (dependency directories, foreground server). kv-store-grpc also changes `int`
  → `int32` and hard-codes the generated file names.
- All rows: B's prompt is "Read task.json and solve ... using only public
  workspace data ..." with the instruction inside task.json; for DeepSWE it also
  adds "do not edit tests, evaluation files, dependency files, lock files, or
  build configuration". A passes instruction.md verbatim.

### I-15 raman-fitting: one transient qualification failure (recorded)
Post-reboot qualify_rows: raman-fitting 39 passed / 1 failed; immediate rerun of
both test files passed (35 + 5). cancel-async-tasks passed in the same run. qualify_rows
keeps only counts, so the failing case is unknown.

### I-16 Per-row candidate caps can reject honest solutions upstream accepts (recorded)
The binding size limits are the rows' declared `max_bytes`, not the tester cap:
e.g. headless-terminal deps 8 MiB, kv-store-grpc deps 40 MB / 1024 files,
hf-model-inference model 300 MB. An agent whose working solution exceeds them
passes upstream and fails capture in B. Phase 5 will show whether it happens.

### I-06 resolved (2026-09-24)
With user approval the 7 rows now pin `alexgshaw/<row>@<upstream digest>` in
`benchmarks/terminal-bench/tasks-v2.jsonl`, and the 6 test files that assert the
image were updated to match (uncommitted). Requalified with `tools.qualify_rows`:
7/7 complete, 0 failures (`qualification/terminal-bench-image-swap/`). All 60
campaign rows now use the same image in A and B.

### I-14 resolved (2026-09-24, user request)
- Rows restored to upstream `instruction.md` text: git-leak-recovery,
  helm-array-merge-strategies, meriyah-explicit-resource-declarations (verbatim),
  kv-store-grpc (upstream text; only "system-wide" dropped and the replay
  paragraph kept, since dependencies must live in the declared replay directory).
- kv-store-grpc Oracle now accepts `int32` or `int64` value fields (upstream's
  prompt says "int" and upstream never checks the scalar type; identical varint
  encoding for every challenged value). New test
  `test_proto_contract_accepts_int64_values_like_upstream`; dossier updated.
- Codex harness has `harness.config.prompt: instructions` (default `task_file`
  keeps the old behaviour): the prompt is the row's public instructions verbatim
  and no task.json is written into the workspace. Campaign configs use it.
- Result: 8/60 prompts byte-identical to upstream instruction.md, 49 differ only
  by a trailing newline, 3 (headless-terminal, hf-model-inference, kv-store-grpc)
  keep their stopped-replay paragraph by design.
- Requalified: git-leak-recovery, kv-store-grpc complete; meriyah and helm are
  covered by the running DeepSWE qualification (edited before those rows ran).
  Non-Docker suite: 2097 passed.

### I-17 SecureBench `--show-agent-output` never streams Codex output (recorded; worked around in the wrapper)
`securebench/sandboxes/docker.py:_is_codex_agent_command` tests for the
substring `"codex exec"`, but the Codex harness runs
`codex <config args> exec ...`, so agent output is never streamed and
agent-trace.log stays empty. Codex's JSON stdout (with token usage) is not
persisted anywhere else. `tools/native_baseline/sb_run.py` replaces the check
with `\bcodex\b.*\bexec\b` (observation only: it enables line streaming of the
same process). The first two DeepSWE SecureBench smoke runs (cattrs, tengo,
rep0) have verdicts but no token counts; cattrs is rerun for cost numbers.

### I-18 Campaign harness bug: prompt starting with "-" (fixed during rep 1)
With `prompt: instructions`, ink-grid-box-layout's instruction ("- Update the
`display` ...") was passed to `codex exec` without `--`, so Codex rejected it as
an option and never ran; the empty candidate was scored `failed` (37 s, 0
tokens). Fixed in `securebench/harnesses/codex.py` (`-- <prompt>`, as Pier and
Harbor do); only this row starts with "-". The rep-1 run is kept as
`ink-grid-box-layout.prompt-dash-bug` and rerun. The campaign driver now marks any
run in which Codex never emitted `thread.started`/`turn.started` as
`infrastructure_error` (`agent_not_started`), in both conditions.

### I-19 Campaign harness bug: Harbor rejected `--ak capture_paths` (fixed before Phase 4)
Harbor validates agent kwargs against the agent's `options_model`; the capture
subclass now extends `CodexOptions`. The two affected native TB smoke runs were
rerun (`*.harness-bug-capture_paths` kept).

### I-20 Phase 4 restarted at 01:51 with more parallelism (recorded)
Phase 4 first started at 01:43 with 4 workers / 22 GB of memory ceilings, but
the host used ~3 GB RAM at load ~3.5 (limits are ceilings, not usage).
It was stopped at 01:50 and relaunched with 6 workers / 40 GB. Completed runs
were kept. In-flight runs were set aside as `<task>.attempt-0-*`; they are not
logged in retries.jsonl because they were operator restarts, not infra
errors (log: `logs/phase4.first-start.log`). A manual rerun of SecureBench
ink rep1, started before per-run locks existed, collided with the relaunched
driver. It was killed. The surviving run directory has a single Codex session
and no foreign `turn.completed`, so its tokens and verdict are unaffected.
The driver now takes a per-run pid lock.

### I-21 SecureBench DockerSandboxError after agent completion under load (watching)
securebench/terminal-bench/mteb-retrieve rep1: Codex finished its turn, then
the run ended `infrastructure_error {'code': 'task_execution_internal_error',
'message': 'Trusted row execution failed: DockerSandboxError'}` (313 s). Host
load was 14–16 on 12 CPUs (two Phase 4 drivers plus Phase 1). Retried per
policy; kept as `mteb-retrieve.attempt-0-*`. SecureBench keeps no further
detail, so the failing Docker call is unknown.

### I-22 Disk filled at ~04:14 (fixed; 3 runs rerun)
Pier and Harbor build and keep a `<task>__<trial>-main` image per trial (≈5–7 GB
each, partly shared layers), and BuildKit cache grew to 50 GB. The disk reached
100%. Effects:
- native deep-swe/prometheus rep1 and rep5: every attempt errored on compose
  build (`no space left on device`), then exhausted retries.
- native deep-swe/bandit rep1: the host could not write `model.patch`, so the
  upstream verifier graded the base state (reward 0, f2p 0/69). This was a
  false **failure**, not flagged as infra.

All three are set aside as `<task>.disk-full` and rerun. All other runs that
finished 03:30–04:25 were checked: none mention ENOSPC. SecureBench
helm-array-merge-strategies rep1 (`build_failed`, evaluated 04:13) was
re-graded from its stored candidate with free disk and failed again, so it is
genuine. Mitigation: `docker-gc.sh` runs every 10 min and removes per-trial
images that no container uses, plus build cache older than 30 min.
Disk use is logged in `logs/disk.log`. Pinned task images are never removed.

### I-23 SecureBench adapter timeouts under CPU contention (watching)
Phase 1 recording, narwhals partial mutant (02:54, load ~15 on 12 CPUs):
`infrastructure_error adapter_timeout` where qualification got `failed`. Same
pattern as I-12. SecureBench's per-challenge adapter timeouts are sensitive
to host load; upstream verifiers use one long suite timeout. In Phase 4 such
cases surface as retried infrastructure errors (excluded from pass rates), so
they cost reruns but do not become false passes. The count is watched in
retries.jsonl.

### I-24 Host CPU saturated 05:00–05:40; driver B stopped (recorded)
Load reached ~40 on 12 CPUs (vmstat: 99–100% user+sys, run queue 30–50, CPU
PSI "some" ≈ 50%). The cause was driver A (6 workers), driver B (2 workers) and
Phase 1 recording (vitest/go suites). SecureBench agent and evaluation
containers have no CPU cap (I-04). Infrastructure errors in this window:
native gcode-to-text rep2 `AgentSetupTimeoutError`; SecureBench prometheus
rep5 `DockerSandboxError` (as I-21); SecureBench extract-moves-from-video rep2
`ConfigError` during producer setup, 36 s in, before Codex started. All were
retried. Driver B's loop was stopped at 05:40. Its two in-flight runs
(meriyah rep5, both conditions) were allowed to finish, and their records
were written by `finalize-orphans.py`; native wall time for those two is
approximate. Driver A continues through reps 2–5 alone (6 workers).

### I-25 Campaign rule fix: recovered API reconnects were treated as infra (fixed, 1 run restored)
The `model_api` rule fired on Codex's `Reconnecting... 1/5 (stream
disconnected ...)` even when the session recovered and completed its turn. That
turned SecureBench sqlfmt rep2 (genuinely `failed`) into an infrastructure error
and re-rolled it, which biases pass rates upward. The rule now needs an API error
with no later `turn.completed`, or `turn.failed`. The new
`campaign repair` step re-applies the rule to every retried attempt and restores
wrongly retried ones; the superseded retry is kept as `.superseded-retry-*`.
sqlfmt rep2 was restored (`failed`). Driver A still runs the old rule, so
`repair` is run again after Phase 4.

### I-26 Phase 1 candidate kinds come from each test's own expectation (method note)
Kinds are assigned from the qualification test's recorded verdict, which matches
the test's assertion because every row passed qualification. Candidates the test
accepts are `reference` (honest variants, including correct answers with ignored
decorations such as a verdict claim). Rejected candidates are `malicious` when the
test or parameter names an attack (forged/claim/malformed/hostile/capture-shape),
otherwise `mutant`, or `base` for base or image-content checks. Six candidates whose
in-test verdict was a load-induced `infrastructure_error` are labelled by name.
Manual overrides: `phase1/kind-overrides.csv` (11 malformed/forged-artifact
cases). Totals: DeepSWE 30 base / 30 reference / 139 mutant / 5 malicious;
TB 33 base / 103 reference / ~180 mutant / ~274 malicious (of which ~135 are
capture-shape attacks rejected before any verdict).

### I-27 Recurring SecureBench `ConfigError` during producer setup; disk low-water 19 GB (recorded)
A second `task_execution_internal_error: ConfigError`, SecureBench true-myth
rep2, came before Codex started (after extract-moves rep2, I-24). SecureBench
records no detail. The Codex overlay preflight (`codex --version` exit != 0),
which is raised as ConfigError, is a plausible cause under load. Both were retried.
Disk: free space swung between 19 and 42 GB as per-trial builds came and went.
The GC loop now runs every 5 min, prunes build cache older than 5 min, and
prunes all unused cache when free space is under 25 GB.

### I-28 Rep 1 stopped at 34/60 tasks on the disk-full OSError; token usage unknown for ~3% of runs (fixed / recorded)
- At 04:21 an `OSError: No space left on device` in one worker (writing
  cli.log) propagated through the driver's thread pool and ended rep 1 after 66
  of 120 runs. phase4.sh went on to rep 2. The driver now logs worker exceptions
  and continues. `phase4-final.sh` waits for Phase 4, then runs two fill
  passes over reps 1–5 (completed runs are skipped), `repair`, `records` and the
  key scan. Rep order and interleaving within the fill still follow each rep's
  seeded schedule, but rep 1's missing 54 runs happen later in time than the rest
  of rep 1.
- Codex reports token usage only on `turn.completed`. Runs that time out, and
  SecureBench runs whose bounded stdout capture cut a very long JSON line
  (e.g. fd rep2: one 733 KB line truncated, no `turn.completed` retained), have
  unknown usage. As of 08:40 that was 6/191 runs (1 native, 5 SecureBench).
  Records now carry `usage_known`. The report excludes such runs from token and
  cost statistics, states their count, and presents totals as lower bounds.

### I-29 Campaign cut to 3 reps (user decision, 2026-09-25 14:15)
Planned: 60 tasks × 2 conditions × 3 reps = 360 agent runs. Reps 4–5 are not
run. 27 rep-5 runs completed earlier by driver B remain on disk under
`*/rep5/` but are excluded from all analysis (`REPS = (1, 2, 3)` in
`tools/campaign_aggregate.py`; Phase 5 runs with `--reps 1 2 3`). Rep 1's 54
missing runs (I-28) are filled after rep 3.

### I-30 Campaign replay bug: empty candidates rejected by config validation (fixed; regraded)
`phase1.replay_command` encoded an empty candidate (the base state) as one empty
argv string, which `harness.config.command` rejects. So every SecureBench grade of
an empty patch came back `infrastructure_error: no results.jsonl`, 23 DeepSWE
base candidates by 14:20. Empty content now yields no chunks. `phase1-fix.sh`
deletes those grades after Phase 1 grading ends, regrades them, and rebuilds
phase1-agreement.csv. Phase 5 (native DeepSWE runs with nothing committed) runs
later in a new process with the fixed code.

### I-31 Campaign replay bug: directory-tree candidates merged instead of replacing (fixed; regrading)
Both replay paths (Harbor replay agent and the SecureBench command replay)
extracted a TB candidate tar over the existing /app state. A directory-tree
candidate (e.g. git-leak-recovery's cleaned `/app/repo`) was merged into the
dirty base repository, so native accepted git-leak mutants and SecureBench
rejected git-leak references. Both paths now remove the row's declared
candidate paths first, so the candidate replaces them. Affected rows:
financial-document-processor, git-leak-recovery, headless-terminal,
hf-model-inference, kv-store-grpc. All their Phase 1 grades are redone
(`phase1-fix2.sh`). Checked on git-leak: reference is now pass/pass. The
"recover-without-cleaning" mutant stays native-pass / SecureBench-fail: upstream's
`test_no_secrets_in_unreachable_objects` inspects only *dangling* objects, so a
secret in an unreachable-but-referenced blob survives. That is a genuine
upstream-leniency finding.
58 TB candidates larger than the argv replay channel (financial-document-processor
trees, distribution-search .npy, dependency directories) are now graded on the
SecureBench side through the qualification tests' `verify_workspace` (same
capture + VerificationEngine, host directory instead of an agent container), and
flagged `securebench_source=host-capture`. Phase 5 uses the same functions.

### I-32 Two rep-1 runs blocked by empty lock files from the disk-full window (fixed)
`.protein-assembly.lock` (native and SecureBench, rep 1) was created at 04:14
while the disk was full, so the PID was never written. The stale-lock check read
PID 0, and `os.kill(0, 0)` signals the caller's own process group and succeeds,
so the lock looked live and both fill passes skipped the runs. The check now
treats an empty or zero PID as stale. Both runs were started at 16:55, after
the other 358; Phase 5 grades them in a follow-up pass.

### I-33 Phase 5 restarted at 17:15 with 4 workers and one infra retry (recorded)
With 6 grading workers the host load reached ~42 on 12 CPUs, and 3 of the
first 39 SecureBench cross-grades were infrastructure errors (the load pattern
of I-23). Phase 5 was stopped and relaunched with 4 workers (`phase5-chain.sh`);
finished grades were kept. After pass 1, cross-grades that ended in
`infrastructure_error` are moved aside (`*.infra-attempt-1`) and graded once
more, mirroring the campaign's retry policy. Remaining infra errors are
reported as n/a.

### I-34 Cross-grading is not meaningful for three TB rows (marked n/a in the report)
Upstream's kv-store-grpc tests need grpcio installed system-wide and a server
already listening on port 5328. hf-model-inference needs a Flask service
running on port 5000. A file-only replay cannot rebuild either, so the native
verifier fails every SecureBench candidate. In the other direction, native
agents follow upstream's instruction to install dependencies into the system
python (headless-terminal), so the declared dependency directory SecureBench
replays from is missing. These rows are n/a in Phase 5, and kv-store/hf also in
Phase 1, with the reason in REPORT.md. Raw verdicts stay in the CSVs.

### I-35 Fidelity findings from the campaign (not fixed; for the next conversion pass)
Remaining DeepSWE disagreements on real agent output (Phase 5), by the side that
accepts:
- SecureBench stricter (upstream accepts, SecureBench rejects): prometheus-typed-label-sorting
  (3 reps), updo-policy-alerting, task-task-graph-export, skrub-duration-encoding,
  termenv-preserve-ansi-resets (both directions of cross-grading agree on this).
- SecureBench more lenient (SecureBench accepts, upstream rejects):
  meriyah-explicit-resource-declarations (upstream also requires the snapshot
  update excluded by `test/**`), anko-default-function-arguments,
  tengo-callable-instance-isolation, pest-character-class-coalescing,
  bandit-structured-nosec-directives.
Phase 1 adds 7 DeepSWE mutants that upstream accepts and SecureBench rejects
(ink, termenv, happy-dom ×2, sqlfmt, tomlkit, helm). It also finds 5 TB malicious
candidates accepted by upstream and 0 by SecureBench
(distribution-search trailing claim, financial-document-processor path
traversal, git-leak-recovery ×2, headless-terminal #4). Per-row evidence is in
phase1-agreement.csv and phase5-crossgrade.csv.

### I-36 Admitted set changed after the campaign; obsidian-linter-auto-table-of-contents slotted in (2026-09-25)
An audit found three DeepSWE adapters that returned guest-computed verdicts:
- **cattrs-partial-structuring-recovery and tomlkit-toml-table-converters:**
  fixed so the adapters report raw observations and the Oracles compare. All
  12 stored campaign outputs for these rows (3 SecureBench, 3 native each)
  were re-graded with the new code, and every verdict is unchanged.
- **returns-validated-error-accumulation:** its Hypothesis law check cannot
  move host-side. The row is now qualification_pending (not admitted), and
  obsidian-linter-auto-table-of-contents replaces it.

Only the replacement row was run; the other 59 rows were not rerun. It used
the same pins and per-task config as the rest (Codex 0.156.1, gpt-6-luna,
effort max, upstream image digest, 5400 s, 8 GB, `prompt: instructions`):
- 6 agent runs (3 reps × 2 conditions), 19:54–20:58 on 2026-09-25, all failed
  in both conditions;
- its 8 Phase 1 fixed candidates, all agree (the reference passes on both sides);
- its Phase 5 cross-grades, 6/6 agree.

The report now covers the current admitted set. returns' runs, fixed
candidates and cross-grades stay on disk and in the raw CSVs, but are excluded
from every statistic.

Consequence: the replacement row ran about 16 hours after the other rows'
rep 1 and on a quieter host, so its runs are not interleaved in time with the
rest. Its instruction text is byte-identical to upstream.

### I-37 SecureBench agent ran with a replaced HOME (found 2026-09-26; fixed after the campaign)
The Codex harness exported `HOME=/opt/securebench/codex-home` before running
the agent, so in condition B the agent did not see the image's `/root`.
Upstream (condition A) keeps the image's HOME. The Sonnet 5 smoke test found
it: SecureBench fix-git failed because `git merge` had no committer identity
(`/root/.gitconfig` sets it), while native passed the same task.

A scan of the 60 admitted images (python-statemachine's image was not pulled
locally, so not scanned) shows what the agent lost:
- **All 30 DeepSWE images:** `~/.cargo`, `~/.rustup`, `~/.bun`, `~/.rye`,
  `~/.local`, and on the 10 Go rows `~/go`. With HOME moved, `go env GOMODCACHE`
  points at an empty directory (the prebuilt module cache is gone, and the
  network is blocked), and `rustup` reports no default toolchain, so
  `cargo` fails. Checked on prometheus, cattrs and pest.
- **fix-git:** `~/.gitconfig` (git identity).
- **Other TB images:** only `.bashrc`, `.profile`, and pip caches.

Scope: only the agent phase of condition B (Phase 4 pass rates). Verifiers,
Oracles, Phase 1 and Phase 5 do not run the agent harness, so they are
unaffected. It is untested whether this explains any of I-35, but 4 of the 5
"SecureBench stricter" rows (prometheus, task-graph, updo, termenv) are Go
rows.

Fix: the Codex and Claude Code harnesses keep the image's HOME and move only
their own state (`CODEX_HOME`, `CLAUDE_CONFIG_DIR`), as the upstream agents
do. Overlay capture (read-only root filesystem, not used by any admitted row)
still moves HOME to its tmpfs. The Luna runs were not rerun; that is a separate
decision.

### I-38 Silent capture rejections in condition B (found 2026-09-26; fixed after the campaign)
The Sonnet 5 campaign (S-10 in `../2026-09-26-sonnet5/ISSUES.md`) found that
stopped-worktree capture counted untracked files git ignores (cargo
`target/`, uv `.venv` with an absolute `python` symlink), and that the
rejection reason was never logged. In Luna these SecureBench runs graded no
candidate:
- python-statemachine-state-data-scoping reps 1–3 (all cases `candidate_error`);
- fd-deterministic-multi-key-sorting rep 3;
- hf-model-inference reps 2–3 (`candidate_capture_rejected`; cause not recorded).

For these rows the B-vs-A difference came from capture, not verification.
Capture now skips untracked paths git ignores (trusted git dir, workspace as
data), and rejection reasons are logged. The Luna runs were not redone.
