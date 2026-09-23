# Conversion blockers and open questions

Running note of rows that could not be converted straight through, and of
decisions that need your review. Opened 2026-09-23 during the Wave B/C/D
conversion push.

Nothing here is an admission decision. A row listed as blocked stays
`not_implemented`; a row listed under "needs review" may be implemented and
qualified but has an open question attached.

## Needs your review

### 1. New registered parser: `securebench.opaque-bytes/v1`

**What I did.** `write-compressor`'s deliverable (`data.comp`) is binary, and no
registered parser accepted arbitrary bytes — the registry had only strict-JSON,
UTF-8 text, ICS, strict-CSV, NPY float summary, tree-manifest, and
git-repository. I added a bounded opaque-bytes profile in
`securebench/verification/parsers.py`.

**Why I judged it safe.** It is the narrowest profile in the registry: it
decodes and interprets nothing. It returns `{byte_count, sha256, bytes_base64}`
under a 4 MiB cap. Base64 is transport, not interpretation — the Oracle receives
exactly the captured bytes plus a digest to bind them. There is no
format-specific attack surface because there is no format.

**Why you should look.** The conversion guide says a missing capability needs a
reviewed vertical slice before use, and this expands the shared registry rather
than one row. It also makes it easy for future rows to push format handling into
Oracles instead of reviewed parsers, which is a governance question more than a
safety one.

### 2. Framework fix: non-finite JSON caused an infrastructure error

`strict_json_loads` rejected the bare `Infinity`/`NaN` tokens but accepted a
valid overflow literal such as `1e400`, which parses to `inf`. Canonical
encoding then raised and the framework reported `infrastructure_error` instead
of rejected candidate evidence — a gate 6 (failure ownership) violation
reachable by any candidate on any strict-JSON row. Fixed at the parse boundary
in `securebench/data_formats.py`. Flagging because it silently affected
already-Approved rows.

### 3. Image pinning is host-local for locally built rows

Wave B tasks have no published `alexgshaw/<task>` image, so they are built from
the checked-in Dockerfile and pinned by bare image ID. Immutable, but not
portable. `password-recovery` is worse: its `setup.sh` seeds directory names and
the 4 MiB disk image from `/dev/urandom`, so **every rebuild yields a different
image ID**. Needs either published images or deterministic builds before these
conversions are reproducible off this host. Detail in the
[qualification record](terminal-bench-qualification-record.md).

### 4. Framework fix: capture rejected unchanged baseline symlinks

`_synchronize_stopped_worktree` in `securebench/candidates/capture.py` checked
the target of every symlink in the stopped worktree, including ones the
candidate never touched. The pinned `helm` checkout ships two upstream test
fixtures with absolute targets (`.../frobnitz_with_dev_null/null -> /dev/null`,
`.../symlinks/invalid-symlink -> /non/existing/file`), so every `helm`
submission, gold included, was rejected before verification. Now only symlinks
that differ from the trusted baseline are validated. A symlink the candidate
creates or retargets is still rejected if absolute or escaping, pinned by
`test_candidate_authored_absolute_or_escaping_symlinks_are_still_rejected` in
`tests/test_v2_candidates.py`. Flagging because it relaxes a capture check.

### 5. Editing a test file rejects the whole candidate (affects Approved rows)

`_validate_patch_path` raises `CandidateCaptureError` when a candidate touches
any `exclude_paths` pattern. It does not drop the excluded path. DeepSWE Go and
TypeScript rows exclude `**/*_test.go` or `**/*.test.ts` so that a candidate
cannot ship its own copy of a hidden test. In practice, a correct submission
that adds or fixes a test file therefore scores zero. Coding agents do this
routinely, and upstream graders never penalise it.

Affected Approved rows: `go-critic`, `task-task-graph-export`, `prometheus`,
`termenv`, `etree`, `tengo`, `ink-grid`, `meriyah`, `happy-dom`.

**`expr-try-catch-errors` is held on this, not registered.** Its gold solution
edits `vm/vm_test.go` (call-site fixups for a changed `vm.NewProgram`
signature, needed for `go test` to compile), so capturing the upstream
solution unmodified is rejected. Its test applies only the gold patch's
non-test hunks. The row otherwise qualifies: 16 passed under Docker,
re-verified.

In v2 no hidden test is executed as the verifier, so excluding test paths no
longer protects the verdict. Options:

1. Drop changes under `exclude_paths` from the captured patch instead of
   rejecting the candidate. This is a framework change: the dropped paths
   would be recorded in candidate metadata.
2. Keep rejection, but narrow each row's `exclude_paths` to the exact files
   `test.patch` touches.
3. Keep the current behaviour and tell the Agent in the public instruction not
   to modify test files. This changes the task.

Recommendation: option 1. It keeps hidden tests out of the candidate without
penalising correct work, and it needs no per-row edits.

### 6. Some Approved DeepSWE rows drop F2P assertions as "consolidations"

Reviewing `csstree` surfaced a rule the earlier rows did not follow. Its
agent dropped F2P assertions (for example `border-right`/`-bottom`/`-left`)
on the grounds that the gold patch handles them with the same mechanism as
`border-top`. That says nothing about an arbitrary candidate, so the row was
sent back, and the playbook now requires bundling instead of dropping (#24).

Several rows admitted before this rule record consolidations that may drop
F2P nodes rather than fold them into a bundled case. Dossiers indicate this
for:

- `meriyah`: nested-block contexts reduced to 3 representatives; a
  non-await for-of variant dropped.
- `mashumaro`: some collision checks exercised in one flatten mode only.
- `true-myth`: the empty-input edge (10 nodes) tested once; the zip
  first/second-operand pair collapsed.

Each needs an audit mapping F2P node to Oracle check. Any genuine drop gets
added back as a bundled step and re-qualified. They stay Approved meanwhile:
none of the drops loosens a check that is made, they only omit some. Flagging
for your call on whether to demote them until audited.

## Evaluation runtimes: what the images actually lack

A `protocol` check runs its adapter **inside the Evaluation runtime built from
the row's own pinned image** (`protocol.py:268` uses `task.environment.image`).
The original Terminal-Bench verifier had no such constraint: its `run-tests.sh`
bootstraps `uv`, which downloads a self-contained CPython over the network at
verification time. Split verification makes that dependency visible, because the
Evaluation runtime is deliberately networkless.

### Two different needs, which are easy to conflate

1. **The adapter's own language.** Our adapters are Python. Where it is missing,
   it is missing only because upstream downloaded an interpreter instead of
   baking one into the image.
2. **The candidate's toolchain** — gcc, pdflatex, rustc, ffmpeg. This is almost
   always *already present*, because the agent needed it to solve the task.

Measured across the 28 remaining TerminalBench design-only rows that have a
Dockerfile:

| | Rows |
|---|---:|
| Image already has Python — needs nothing | **17** |
| Image has no Python — needs a vendored interpreter | **11** |

And in those 11, the candidate's toolchain is present anyway: `polyglot-c-py`
installs `gcc`, `polyglot-rust-c` installs `rustc g++`, `overfull-hbox` installs
`texlive-latex-base`, `path-tracing` installs `ffmpeg gcc curl`. So vendoring a
single interpreter covers the whole set; there is no separate "gcc problem".

### Proof that vendoring works

`resources.runtime` already compiles to `evaluation_inputs` — read-only bind
mounts visible to the Evaluation container and never to the Agent — and the
mounts carry no `noexec`. Demonstrated directly: a CPython tree extracted from
`python:3.13-slim` (35 MB), mounted read-only into the Python-less `regex-log`
image, started and ran `re.findall` correctly.

Mechanically it is a second runtime resource plus a command change:

```yaml
      python_runtime:
        path: _runtimes/cpython-3.13
        mount: /opt/securebench/runtimes/python
```
```yaml
command: ["/opt/securebench/runtimes/python/bin/python3", "./adapter.py"]
```

Today's manifests say `command: ["python3", ...]`; since that does not begin with
`./` it passes through unchanged and resolves on the container `PATH`, which is
exactly why it failed.

### Open decisions

1. **Vendor an interpreter** (narrower). Adds a ~35 MB pinned artifact to the
   repo, and means row behaviour depends on a mounted interpreter that is not in
   the image digest — which needs its own pinning story, since the row claims a
   digest-pinned Evaluation. Use a portable `python-build-standalone` build, not
   the glibc-coupled tree tested here, which would break on Alpine-based images.
2. **Let a row declare a separate evaluation image** (cleaner, larger). This is a
   core schema change. It is also *not* a global "evaluate on a Python image":
   the choice is per row, because some candidates depend on packages installed in
   their task image, and all 93 DeepSWE `repo_patch` rows must evaluate on the
   repo image since the repository *is* the image at `base_commit`. Note also
   that `baseline_digest` includes the image, so splitting the two forces a
   decision about which image the candidate's replay baseline binds to.

### Worked example already built

`regex-log` is complete and validated — assertion-free adapter with a `SIGALRM`
guard against catastrophic backtracking, an Oracle holding the source's exact
25-line corpus and nine expected dates extracted by AST, and a reference pattern
that reproduces that list exactly. **No row is registered**, because nothing in
its bare `ubuntu:24.04` image can apply a Python regular expression. Under
option 1 it is roughly a manifest line plus a mount entry. See
`benchmarks/terminal-bench/v2/hidden/regex-log/qualification/BLOCKED.md`.

### Upstream task-design problems, not conversion problems

- `merge-diff-arc-agi-task` installs nothing at all, yet the task is to
  initialise a git repo and merge two bundles. The **agent** must `apt-get
  install git` over the network to solve it. Broken upstream.
- `sparql-university` needs `rdflib`, a pure-Python package that bundles
  alongside a vendored interpreter.

## Missing source material: 9 rows have no Dockerfile

These design-only rows have no `benchmarks/terminal-bench/docker/<task>/`
directory at all, so their images cannot be inspected or built and the rows
cannot be converted regardless of the runtime decision:

`adaptive-rejection-sampler`, `build-pmars`, `build-pov-ray`,
`compile-compcert`, `configure-git-webserver`, `mailman`,
`nginx-request-logging`, `pypi-server`, `sqlite-with-gcov`.

The source material needs materialising from the pinned Terminal-Bench revision
before any of them can be attempted.

## Blocked rows

### `multi-source-data-merger` — needs a Parquet parser

The scored deliverable is `/app/merged_users.parquet`. Verification needs the
row values, so opaque bytes are not enough: something must read Parquet.

Options: (a) register a bounded Parquet parser, which is a real format parser
over hostile bytes and a much larger attack surface than opaque-bytes;
(b) decode Parquet inside the Oracle from opaque bytes, which moves the same
risk host-side but keeps it out of the shared registry; (c) exclude.

My inclination is (b) with a strictly bounded reader, but this is a genuine
trust-surface decision and I did not want to make it unilaterally.

### `sanitize-git-repo` — exceeds the git parser bounds by two orders of magnitude

I measured the actual repository inside the built image (`/app/dclm`):

| Quantity | Actual | `securebench.git-repository/v1` bound | Over by |
|---|---:|---:|---:|
| Git objects | 1,163 | 512 | 2.3x |
| Largest blob | 45,940,626 B (~44 MiB) | 262,144 B (256 KiB) | 175x |
| `.git` on disk | 52 MB | 1 MiB total object bytes | ~50x |
| Worktree | 61 MB | — | — |

So the row cannot use the existing parser, and raising the bounds far enough
would weaken them for `git-leak-recovery`, which is currently **Approved**. That
is not a trade I should make unilaterally.

Three further wrinkles:

1. The dossier proposes applying an extracted patch to the original repository
   in a fresh Evaluation, which is a `protocol` shape, while the row is filed as
   passive artifact verification. These disagree and need reconciling.
2. A `repo_patch` family row with a `git_patch` candidate looks like the natural
   fit — the task really is a repository modification — but the family requires
   `environment.workdir` to be a clean repo at `base_commit`, and here the clone
   sits at `8df3c81f…` while the source verifier diffs against the *ancestor*
   `d6987af0…`. Those are different commits, so the mapping is not mechanical.
3. The image build clones from GitHub at build time, so the pinned image depends
   on an external repository staying available, and the build is not hermetic.

The scored surface is actually small — five literal secrets absent from three
named files, those three files matching fixture content exactly, and no other
*tracked* file differing from the base commit. A narrower candidate could carry
just those three files plus enough evidence for the "nothing else changed"
rule, but designing that evidence is the open question.

### `install-windows-3.11` — implemented, no focused test

Carried over from Wave A. It has a row and a capture contract but no
`tests/test_install_windows_3_11_v2.py`, so its mutants, malicious candidates,
and Oracle decisions are unproven. It cannot be admitted until that exists.

## Remaining passive-artifact row: `llm-inference-batching-scheduler`

Researched and confirmed **fully decidable from output bytes** — the source
verifier never executes candidate code, only reads two JSONL plans and runs a
closed-form analytical cost model over them. The public `cost_model.py` and the
hidden `cost_model_for_tests.py` are functionally identical (comments stripped),
so the Oracle can port it 1:1.

Not done for one reason: **gate 2 needs a reference plan and none exists.** The
shipped `baseline_packer.py` is deliberately far worse than the pass thresholds
(bucket 1 cost 2.48e12 against a 3.0e11 limit). Producing a reference means
actually solving the shape-aware bin-packing optimisation well enough to clear
eight thresholds. That is a genuine piece of work, not a transcription, and it
is the honest reason this row is still `not_implemented`.

Note also that no JSONL parser is registered; `securebench.utf8-text/v1` with
per-line decoding in the Oracle is the faithful fit, matching what the source
verifier itself does.

## Carried over from Wave A

The four fidelity-parked rows (`circuit-fibsqrt`, `cobol-modernization`,
`extract-elf`, `fix-code-vulnerability`) are tracked separately in the
[fidelity review queue](fidelity-review-queue.md).

## DeepSWE

### Source material is now complete, but lives in `/tmp`

All 113 DeepSWE tasks are available at the pinned revision `e016041a` in a
blobless checkout of `github.com/datacurve-ai/deep-swe` at
`/tmp/securebench-paper-deepswe-source`. It was previously a sparse checkout of
only the ten paper-selected tasks; the sparse filter was removed to fetch the
rest. **`/tmp` does not survive a reboot.** Every conversion copies what it
needs (the gold patch, provenance, licences) into
`benchmarks/deep-swe/v2/hidden/<task>/qualification/`, so completed rows do not
depend on it, but unconverted rows do. Re-create it with
`git clone --filter=blob:none https://github.com/datacurve-ai/deep-swe && git -C deep-swe checkout e016041a6ccf8da29906afc9a3f5a8df940a1f78`.

### Seven trusted-external-state rows need Trusted Helper types that do not exist

Only three Trusted Helper types are registered: the HTTP request recorder (fixed
response), the append-only event ledger, and the process supervisor. The
reviewed designs for these rows each require a new, programmable host-owned
service:

| Row | Helper the reviewed design requires |
|---|---|
| `goreleaser-retry-publish-auditing` | programmable HTTP and object-store **fault** services (status, `Retry-After`, transport failures, per-attempt ledger) |
| `kcp-go-multiplexed-kcp-streams` | **byte relay** between two candidate peers, with release gates |
| `igel-persist-feature-schema` | **probe-model service** returning unpredictable per-case results |
| `bandit-incremental-cache-control` | **witness broker** whose response changes between scans, to prove a genuine cache hit |
| `claude-code-by-agents-recursive-delegation` | **provider broker** streaming scripted tool-use events |
| `ofetch-per-origin-circuit-breaker` | scripted HTTP **origins** with delays and failures (dossier: major redesign) |
| `query-persist-restored-query-state` | host-owned **persistence service** and callback ledger (dossier: major redesign) |

The conversion guide requires a reviewed contract, bounds, failure ownership,
adversarial tests and a real-Docker isolation test before any new helper type is
registered, so these were not improvised. Several of them are variations on one
capability — a *scriptable* HTTP origin with a host ledger — so a single new
helper type would likely unblock `goreleaser`, `ofetch`, `igel`,
`claude-code-by-agents` and `bandit-incremental-cache-control` together.

`awilix-async-container-initialization` and `aiomonitor-task-snapshots-diff`
were assessed and are **not** blocked:

- `awilix` fits the `cancel-async-tasks` pattern with the existing append-only
  event ledger (plus the process supervisor for launch and timeout). Ordering,
  concurrency limits, level barriers and rollback order are unforgeable only if
  recorded outside the candidate's JS isolate, so a parent adapter process owns
  the ledger credential and hands the candidate opaque RPC stubs. The dossier's
  "callback barriers" and "failure injection" are adapter-local behaviour, as in
  the precedent, not helper capabilities.
- `aiomonitor` needs no helper at all: every upstream assertion is a return
  value, exception, formatted string or HTTP response from a call the adapter
  makes itself. The adapter must still only *report* those; expectations stay
  in the Oracle, derived from the workload it places in the challenge.

### Framework flakes under concurrent Docker load (needs investigation)

While several conversions qualified in parallel on one host, two conversions
each saw a single transient **infrastructure** error that did not recur on
retry:

- `ConfigError: Private Docker network ... is not isolated`, raised by the
  isolation preflight in `securebench/docker_network.py` (seen by
  `ink-grid-box-layout`);
- `evaluation_cleanup_failed` during sandbox teardown (seen by
  `narwhals-rolling-window-suite`).

Both were reported correctly as infrastructure failures, never as candidate
verdicts, so no row was mis-scored — the failure-ownership model worked. But an
isolation check that fails spuriously under load is worth understanding before
the paper reports throughput, and it should be reproduced deliberately (many
concurrent protocol evaluations) rather than dismissed as noise. Every row was
re-verified with a clean run before integration.
