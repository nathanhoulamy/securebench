# DeepSWE conversion playbook

Operational instructions for converting one DeepSWE row to a qualified v2
`repo_patch` row. Read [`AGENTS.md`](../../AGENTS.md) and the
[conversion guide](conversion-guide.md) first; this file adds the concrete
procedure and the defects already found in DeepSWE conversions, so they are not
repeated.

## Inputs

- Upstream source, pinned at `e016041a6ccf8da29906afc9a3f5a8df940a1f78`:
  `/tmp/securebench-paper-deepswe-source/tasks/<task>/`
  - `instruction.md` — the public prompt, used verbatim as `input.instructions`
  - `task.toml` — `docker_image`, `base_commit_hash`, language, repository
  - `tests/test.patch` — the upstream hidden tests. **Qualification material
    only.** Read it to derive behaviour; never mount it, run it as the verifier,
    or copy expected values into the adapter.
  - `tests/config.json` — `f2p_node_ids` / `p2p_node_ids`, the scored tests
  - `solution/solution.patch` — the upstream gold solution
- The row's dossier: `docs/benchmark-conversions/DeepSWE/<task>.md` — the
  reviewed conversion design and fidelity decision.
- Working examples, all qualified against their gold solution:
  `go-critic-doc-link-checker` (Go linter), `fd-deterministic-multi-key-sorting`
  (Rust CLI), `cattrs-partial-structuring-recovery` (Python library),
  `updo-policy-alerting` (Go + HTTP recorder Trusted Helper).

## Files you own

Create only these. **Do not edit** `tasks-v2.jsonl`, `inventory.csv`, other rows'
files, or shared tests — rows are integrated centrally after they qualify.

| Path | Content |
|---|---|
| `benchmarks/deep-swe/v2/staging/<task>.json` | the v2 row, one JSON object |
| `benchmarks/deep-swe/v2/evaluation_inputs/<task>/adapter/` | `adapter.yaml`, adapter, driver sources |
| `benchmarks/deep-swe/v2/hidden/<task>/oracle/` | `oracle.yaml`, `oracle.py`, host-only case data |
| `benchmarks/deep-swe/v2/hidden/<task>/qualification/` | installed by `tools/deepswe_reference.py` |
| `tests/test_deepswe_<task_with_underscores>_v2.py` | the focused qualification test |
| `docs/benchmark-conversions/DeepSWE/<task>.md` | append an "Implemented v2 conversion" section |

## Procedure

1. **Reference material.** Pull the image by the tag in `task.toml`, resolve its
   digest (`docker inspect --format '{{index .RepoDigests 0}}'`), then run
   `python -m tools.deepswe_reference --source <src> --image <digest-ref> <task>`.
2. **Check the image contract.** `/app` must be a clean git repo with
   `HEAD == base_commit_hash`. If not, stop and report a blocker; never change
   the base commit to match the image.
3. **Derive behaviour from `test.patch`.** For every F2P test, record the input,
   the call, and what is asserted. Separate assertions that inspect externally
   observable results (keep) from ones that inspect private implementation
   detail (record as a semantic change, do not smuggle into the adapter).
4. **Write the adapter** (`securebench.adapter/v2`). It receives one challenge,
   exercises the candidate, and returns a bounded, typed observation. It must be
   **assertion-free**: no expected values, no thresholds, no pass/fail.
5. **Write the Oracle** (`securebench.oracle/v1`). It owns every expected value,
   emits challenges one at a time, and compares observations. Emit **at least
   two** challenges so fresh-Evaluation isolation is exercised.
6. **Stage the row** and preflight it (`validate_executable_task`).
7. **Qualify under real Docker** with `tests/deepswe_qualification.py`:
   base fails, gold passes, mutants fail. Iterate until all hold.
8. **Record** the conversion in the dossier.

## Row template

```json
{
  "id": "deep-swe/<task>",
  "family": "repo_patch",
  "input": {"repo": "<owner/name>", "base_commit": "<40-hex>", "instructions": "<instruction.md verbatim>"},
  "environment": {
    "image": "public.ecr.aws/d3j8x8q7/swe-bench-202605@sha256:<digest>",
    "workdir": "/app", "timeout_seconds": 5400,
    "agent_network": {"mode": "none", "allowed_domains": []}
  },
  "verification": {
    "candidate": {"type": "git_patch", "max_patch_bytes": 16777216,
                  "max_changed_files": 2048, "max_changed_bytes": 134217728,
                  "allow_paths": [],
                  "exclude_paths": ["tests/**", "test.sh", "securebench/**", "**/test-results/**",
                                    "<language test globs, e.g. **/*_test.go, **/test_*.py, **/*.test.ts>",
                                    "<every path test.patch touches>"]},
    "resources": {
      "runtime": {"<name>_adapter": {"path": "<task>/adapter", "mount": "/opt/securebench/adapters/<task>"}},
      "host": {"task_oracle": {"path": "<task>/oracle"}}
    },
    "checks": [{"id": "<snake_case>_behavior", "type": "protocol",
                "adapter": "runtime.<name>_adapter", "protocol": "securebench.<task>/v1",
                "challenge": {"source": "host.task_oracle", "max_cases": <n>, "max_case_bytes": <bytes>},
                "limits": {"seconds_per_case": <s>, "observation_bytes_per_case": <bytes>}}],
    "oracle": "host.task_oracle"
  },
  "metadata": {"source_dataset": "datacurve-ai/deep-swe", "source_revision": "e016041a6ccf8da29906afc9a3f5a8df940a1f78",
               "source_task_id": "<task>",
               "conversion": {"verdict": "clean|semantic_change", "intelligence_impact": "none|low|...",
                              "dossier": "docs/benchmark-conversions/DeepSWE/<task>.md"}}
}
```

DeepSWE declares `network_mode = "no-network"` for the agent, so
`agent_network` is `none`. `exclude_paths` must cover every path that
`test.patch` touches, so a candidate can never ship its own copy of a hidden
test; the framework adds protected paths of its own on top. Compare an existing staged/registered row before
inventing a field; the schema is closed and rejects unknown keys.

## Defects already found — do not repeat them

Every one of these was in a row that looked finished and was caught only by
replaying the gold solution:

1. **Evaluation `/tmp` is mounted `noexec`.** Never build into or execute from
   `/tmp`. Put `CARGO_TARGET_DIR`, `GOTMPDIR`, `GOCACHE`, compiled drivers and
   scratch executables under a directory in `/app` (for example
   `tempfile.TemporaryDirectory(dir="/app")`). `/app` is the writable,
   exec-capable reconstructed workspace and is disposable.
2. **Invoke the tool exactly as upstream's harness does.** `fd`'s adapter passed
   a positional path together with `--strip-cwd-prefix`, which `fd` rejects, so
   it failed on every correct implementation. Read the upstream test helper
   (`TestEnv`, fixtures, conftest) and reproduce its working directory,
   arguments and environment.
3. **Check the real API at the base commit before calling it.** `cattrs`'s
   adapter passed `forbid_extra_keys` to `BaseConverter`, which does not accept
   it. Inspect signatures inside the pinned image.
4. **No `from __future__ import annotations` in Python adapters that define
   classes locally.** Postponed annotations become unresolvable strings, and
   libraries that introspect types fail on correct code.
5. **Do not invent requirements.** `cattrs`'s Oracle demanded that new partial
   errors be picklable and that `error_map` be populated with detailed
   validation off. Neither is in the instruction or any upstream test, and both
   rejected the gold solution. Every Oracle check must trace to the public
   instruction or an upstream assertion. Note the mode each upstream assertion
   runs under and scope the check the same way.

6. **The image's build caches are read-only in Evaluation.** Pointing
   `GOCACHE` at `/root/.cache/go-build` fails every build with
   `read-only file system`, followed by misleading secondary errors such as
   `package text/template is not in std` — do not chase those. Copy the warm
   cache into the per-invocation workspace under `/app` and point `GOCACHE`
   there, as `go-critic`'s adapter does. The same applies to other toolchains'
   caches.
7. **Absence checks on generated text need a disjoint alphabet.** An Oracle
   check that a forbidden character does not appear must draw that character
   from an alphabet nothing else in the challenge can contain. `termenv`'s
   randomly chosen lowercase letter sometimes also appeared in a lowercase URL
   carried verbatim in the same text, failing a correct implementation.
8. **Verify each mutant actually discriminates.** Before relying on a mutant
   case, apply the mutant to the gold patch and confirm the case fails.
   `bandit`'s first statement-span case passed under the very bug it targeted,
   because the finding's own line already sat inside the suppressed region.
9. **Expectations recorded from the gold solution are acceptable only for
   fields upstream asserts.** Recording expected outputs by running the gold
   patch is convenient, but compare only the fields the instruction or an
   upstream test constrains (for `bandit`: finding `(test_id, line)` and the
   `nosec` / `skipped_tests` counts), never the whole gold output.

10. **JavaScript/TypeScript: bare imports resolve from the importing file's
    own path.** A driver run from the adapter mount cannot find `react` or any
    other package, because nothing above `/opt/securebench/adapters/...` has a
    `node_modules`; `cwd` and `NODE_PATH` do not help under ESM. Copy the driver
    into `tempfile.TemporaryDirectory(dir="/app")` and run that copy, import
    project sources by absolute path (`/app/src/...`), and set `TMPDIR` to an
    `/app` directory because `tsx`/esbuild need exec-capable scratch space.
    Pinned DeepSWE TypeScript images ship dependencies in `/app/node_modules`
    and run TS directly with `node --import=tsx` (see `ink-grid-box-layout`).
11. **Pick test inputs that separate near-miss implementations.** `ink-grid`'s
    first `fr` cases used container widths that divide evenly, so `floor` and
    `ceil` gave identical layouts and a rounding mutant passed. Choose sizes,
    counts and values where the plausible wrong implementation diverges.

12. **The adapter schema language has no union or nullable type.**
    `JsonValueSchema` array items take exactly one type, so "array of
    number-or-null" cannot be declared. Carry such values as a bounded
    JSON-encoded string field (`values_json`), as `cattrs` and `narwhals` do,
    and have the Oracle decode it strictly.

13. **An adapter crash surfaces only as an opaque `adapter_failed`.** When
    that happens, reproduce the adapter directly inside a container of the
    pinned image with the real mount layout (`python3 ./adapter.py <
    request.json`) to see the traceback the harness wraps. A common cause:
    `shutil.copytree` into a directory already created with `mkdir`.
14. **Evaluation containers have 1 GB of memory.** Driving a feature through a
    heavyweight test harness package (for example Prometheus'
    `util/teststorage`, which pulls in all of `tsdb`) can take minutes to
    compile and get the adapter OOM-killed. Build the smallest harness that
    exercises the scored code path — harness plumbing is not the code under
    test — and record the substitution in the dossier.
15. **Protocol observations are capped at 1 MiB.** `observation_bytes_per_case`
    and `maximums.observation_bytes` above `MAX_PROTOCOL_OBSERVATION_BYTES`
    fail `validate_executable_task` ("Protocol observation bound exceeds the
    Evaluation output capacity"). Size the bound to the real payload.
16. **Oracle `case_context` must be JSON-serialisable.** It crosses the
    Oracle/harness boundary in the `next_case` response. A lambda or other
    callable there crashes the Oracle subprocess, whose stderr is discarded,
    so the only symptom is `oracle_exited`. Encode checks as data
    (`{"op": "len_eq", "n": 3}`) and interpret them in `evaluate_case`.
17. **Not every TypeScript image ships `tsx`.** `meriyah` has `vite-node`
    (needed: `const enum` defeats Node's type stripping); `happy-dom` has
    neither and uses `.js`-names-for-`.ts` imports, so its driver runs as a
    vitest test file copied into the project's `test/` tree, exchanging
    challenge and observation through scratch files. Check the image first.
18. **Decode candidate output against an exact key set.** `JSON.stringify`
    silently drops `undefined` fields, so a base-commit stub missing a getter
    yields an incomplete object. Reject missing or extra keys in the adapter
    instead of reading with defaults, or an incomplete observation looks valid.

19. **Check whether the gold solution edits an excluded path.** Capture
    rejects the whole candidate on any `exclude_paths` edit (see
    conversion-blockers §5). If `solution.patch` touches a test file, finish
    qualification using only its non-test hunks, and report STATUS: HELD
    naming the file, so the row waits for that decision.

20. **Never loosen an upstream assertion.** `returns` first accepted "at
    least 14" passing laws where upstream names 16 specific law tests. Where
    upstream pins an exact set, count, value or tolerance, the Oracle pins the
    same, no looser and no stricter. A tighter tolerance than upstream's (`1e-6`
    where upstream checks `< 0.01`) can reject correct work upstream accepts.
    If upstream looks too strict, keep its check and record the concern.

21. **A challenge must not carry its own grading assertion.** `ts-pattern`'s
    first type probes embedded `Expect<Equal<..., Expected>>` and
    `@ts-expect-error`, which puts the expected answer inside the Evaluation.
    Send assertion-free probes. Report diagnostics as `(code, line)` pairs, or
    write usage that compiles only if the property holds. The Oracle decides
    which lines must fail. Drop anything checkable only by naming the expected
    type, and record the drop.

22. **Some packages write to `$HOME` on import.** `import skrub` creates
    `~/skrub_data` at module import, and `/root` is read-only in Evaluation,
    so every case failed even for the gold solution. Point such paths at
    scratch space before importing (`SKB_DATA_DIRECTORY`, `XDG_CACHE_HOME`,
    `MPLCONFIGDIR`, …), and check for this when gold fails uniformly.
23. **Match the upstream test file's real location in `exclude_paths`.**
    Package-nested tests (`skrub/tests/…`, `meta/tests/…`) are not matched by
    `tests/**`. Use `**/tests/**` or the exact paths from `test.patch`.

24. **Bundle F2P assertions; never drop them.** "The gold patch uses the same
    mechanism for `border-right` as for `border-top`" says nothing about an
    arbitrary candidate. Every F2P assertion must be checked. To keep the
    Evaluation count reasonable, put several assertions in one case: one
    driver run returning several results. Only assertions on private,
    unobservable state may be dropped, and each drop is recorded.

25. **Namespaced ids grow past schema bounds.** Bundling scenarios and
    prefixing ids with the scenario name pushed one id to 67 bytes against a
    64-byte `max_utf8_bytes`, failing only the case holding that scenario.
    Size id bounds for the longest prefixed id, and run Gate 2 over all cases.

26. **Never wait with `until ! pgrep -f "<pattern>"` loops.** The loop's own
    command line contains the pattern, so `pgrep -f` always matches itself
    and the loop never exits. Nine such orphaned waiters piled up during
    `helm`. Run tests in the foreground instead (see "Running Docker
    qualification without being interrupted").

27. **pnpm projects need a pnpm-aware module resolver.** Dependencies live
    under `node_modules/.pnpm/…` and are not hoisted, so plain `node` or
    `ts-node` fails with `MODULE_NOT_FOUND`. Check the runner resolves them
    (jest and vitest do), not just that it is installed.

## Acceptance criteria

A row is ready for integration only when, under
`SECUREBENCH_DOCKER_INTEGRATION=1`:

- **Gate 1** — the unmodified base commit **fails**, with no infrastructure error.
- **Gate 2** — the upstream gold solution **passes**, across at least two fresh
  Evaluations with distinct Evaluation IDs, every evidence item `observed`.
- **Gate 3** — at least **three targeted real-code mutants fail** under Docker:
  the gold patch plus one hand edit each, a plausible near-miss on a distinct
  semantic axis taken from `test.patch` (not syntax errors). Include the generic
  "drop the largest non-test file" mutant too. Oracle-level synthetic mutants
  may be added but do not count toward the three.
- **Gate 4** — forged or malformed adapter observations are rejected by the
  Oracle (a unit-level test driving the Oracle directly is fine).
- **Visibility** — `reference.patch`, `qualification`, and the Oracle never
  appear in `task.view_for("agent")` or `task.view_for("evaluation_runtime")`,
  and the adapter never appears in the agent view.
- **Fidelity** — every Oracle check traces to the instruction or `test.patch`;
  every dropped or narrowed upstream assertion is listed in the dossier section.

**Never make the gold solution pass by weakening a check that upstream really
asserts.** If a correct upstream assertion rejects the gold solution, that is a
finding — report it. If the only way to pass is to accept the base commit, the
Oracle is wrong.

## Running Docker qualification without being interrupted

Run every Docker-backed pytest invocation as a **single synchronous** shell
call with a long timeout (up to 600000 ms), and split the file with `-k` so
each invocation finishes inside ten minutes (base; gold; mutants in small
groups; then the whole file). Do not launch pytest in the background and then
wait across idle turns — conversions that did so were repeatedly handed back
mid-run with nothing new verified. Each case is a fresh container, so with
other conversions sharing the host, a 30-case gold replay can take several
minutes.

## When to stop and report a blocker

Stop, leave the row un-staged, and report precisely when:

- the image does not contain the repository at `base_commit`;
- the feature needs a Trusted Helper type that is not registered;
- the scored behaviour cannot be observed without running the hidden tests
  themselves or without network access;
- the gold solution fails for a reason that is not a conversion defect;
- the task needs a missing runtime or toolchain in the Evaluation image.

A precise blocker is a valid outcome. A row that passes by weakening the Oracle
is not.

## Working alongside other conversions

Several conversions run on the same host at once.

- Never run `docker system prune`, `docker image prune`, `docker rmi`, or
  `docker builder prune`, and never remove containers you did not start.
- Run only your own test file, never the whole suite.
- Never delete or edit files you did not create; never commit.
- A single transient infrastructure error (network isolation preflight,
  evaluation cleanup) under load is retried once; if it recurs, report it.
- Keep case counts reasonable — each case is a fresh container. Consolidate
  near-duplicate upstream axes and list every consolidation in the dossier.

## Report format

Your final message must contain, in order:

1. `STATUS: QUALIFIED` or `STATUS: BLOCKED`.
2. The exact final pytest summary line from a full Docker run of your file.
3. Each gate and the test names that demonstrate it.
4. Each real-code mutant and the upstream assertion it targets.
5. Fidelity: every upstream assertion dropped, narrowed or consolidated, and
   why; the verdict (`clean` / `semantic_change`) and intelligence impact.
6. Any defect you hit that this playbook does not already list.
7. Every file you created.

If you are interrupted before finishing, report exactly which gates are
verified and what remains, and leave the staging file in place.
