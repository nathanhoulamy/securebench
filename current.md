# Current SecureBench v2 state

Last reviewed: 2026-09-02

Implementation baseline reviewed: this branch through Output Artifacts, HTTP
request/event-ledger/process-supervisor Trusted Helper execution, git-patch
execution, the locally qualified filesystem-overlay implementation, and the
subsequent architecture-wide overlay integration review, plus the compact
qualification matrix and Terminal conversions through `gpt2-codegolf`

Active development branch: `split-verification-v2`

## Executive assessment

The implementation is structurally consistent with the recommended row schema. It uses the
schema's intended separation of concerns:

- families define the public Agent workflow, not the verifier;
- one replayable candidate crosses the Agent/Evaluation boundary;
- checks are either passive `artifact` checks or active `protocol` checks;
- the compiler centrally assigns `public`, `evaluation_inputs`, and `hidden` visibility;
- only the host Oracle determines correctness and emits the final verdict.

The runtime is deliberately narrower than the author-facing schema. This is safe because
`validate_executable_task()` rejects schema-valid but unsupported combinations before Agent
execution. The current implementation should therefore be described as a sound first vertical
slice, not as complete support for every schema branch.

## Sources of truth

- Design target: [`docs/split-verification/schema.md`](docs/split-verification/schema.md)
- Executable example: [`docs/split-verification/examples/executable.yaml`](docs/split-verification/examples/executable.yaml)
- Target-architecture examples: [`docs/split-verification/examples/target-architecture.yaml`](docs/split-verification/examples/target-architecture.yaml)
- Executable Pydantic models: [`securebench/schemas/benchmark.py`](securebench/schemas/benchmark.py)
- Generated JSON Schemas: [`schemas/`](schemas/)
- Runtime capability gate: [`securebench/execution_profiles.py`](securebench/execution_profiles.py)
- Security guarantees and limitations: [`docs/split-verification/security-model.md`](docs/split-verification/security-model.md)
- Benchmark conversion portfolio: [`docs/benchmark-conversions/`](docs/benchmark-conversions/)
- Conversion implementation guide: [`docs/benchmark-conversions/conversion-guide.md`](docs/benchmark-conversions/conversion-guide.md)

The Pydantic models are the executable schema source of truth. The design document includes
future-facing contracts that are schema-valid but not necessarily executable yet.

## Implemented execution path

1. A v2 manifest and JSONL rows are loaded into closed Pydantic models.
2. Manifest defaults are applied and family/candidate compatibility is validated.
3. Pack resources are resolved below three non-overlapping, symlink-safe source roots.
4. The compiler assigns resources to component-safe visibility views and computes baseline and
   verification digests over actual resource contents.
5. Execution preflight rejects unsupported candidates, checks, parsers, profiles, mounts, and
   component manifests before candidate production.
6. A fresh Docker Agent environment receives only the prompt and public material. The candidate
   capture policy and verification graph are not added to its prompt.
7. After the Agent container stops, trusted capture exports only the declared bounded candidate
   into a content-addressed store.
8. Artifact checks parse hostile bytes passively. Protocol checks reconstruct the candidate in a
   fresh Evaluation container for every current Oracle-selected Challenge. Evaluations without
   helpers have no network; an Evaluation using the HTTP recorder receives only an internal Docker
   network shared with its fresh helper instance.
9. Internal evidence goes to the host Oracle. Public results contain only bounded diagnostics,
   digests, check summaries, and provenance.
10. The stopped Agent workspace and disposable Evaluation roots are removed.

Candidate-production and capture failures are sent to the Oracle as candidate-error evidence;
the runner does not invent a benchmark score.

## Schema-to-runtime capability matrix

| Schema/design area | Current state |
|---|---|
| Manifest defaults and closed v2 rows | Implemented |
| `repo_patch` and `terminal_task` family contracts | Implemented |
| Digest-pinned images and Agent timeout/network fields | Implemented |
| Three structural visibility lanes | Implemented and centrally enforced |
| Non-overlapping, symlink-safe resource roots | Implemented |
| `file_bundle` candidate | Implemented end to end, including bounded directory trees |
| `git_patch` candidate | Implemented end to end with exact clean-commit baselines and canonical stopped-state capture |
| `filesystem_overlay` candidate | Capture, transactional storage, fresh replay, and normal harness integration implemented; native execution remains qualification-gated |
| Passive artifact check using `source.entry` | Implemented for whole `file_bundle` entries and bounded regular-file `source.subpath` selection inside directory trees |
| Artifact check using `source.path` | Implemented for bounded repository-relative `git_patch` paths and absolute paths mapped through fresh overlay roots |
| Registered passive parsers | JSON, UTF-8 text, ICS, strict CSV, bounded scalar-float NPY summaries, tree-manifest, and hook-free bounded Git-repository profiles exist |
| Basic protocol check | Implemented with finite JSON, bounded I/O, and a fresh offline container per Challenge |
| Adapter v2 contract | The only supported Adapter format; implemented with typed Challenge/Observation schemas, Evaluation Participants, Trusted Helper requirements, Output Artifacts, and reduced maximums |
| Challenge Evidence | Implemented with host Challenge/Evaluation IDs, correlation checks, and explicit failure source |
| Trusted Helper Catalog | Typed contracts, semantic preflight, reviewed runtime registration, and fail-closed lookup implemented |
| `securebench.http-request-recorder/v1` | Implemented end to end with fresh instances/credentials, internal-only networking, bounded request evidence, and correlated teardown |
| `securebench.append-only-event-ledger/v1` | Implemented end to end with fresh instances/credentials, a closed nonce/event/data append interface, host-monotonic timestamps, bounded attempt evidence, and correlated teardown |
| `securebench.process-supervisor/v1` | Implemented as a host-only Evaluation launch owner with no guest credential, an allowlisted bounded signal schedule, and externally captured lifecycle/timing evidence |
| Output Artifacts | Implemented for bounded regular files and directory trees from the same disposable Evaluation |
| `strict-split/v1` | Implemented for file-bundle and git-patch execution and for qualification-gated overlay artifact/protocol paths, including all three registered Trusted Helpers |
| `batched-split/v1` | Registered but explicitly not implemented |
| Host Oracle JSON-lines ABI | Implemented for initialize, artifact evidence, cases, case evidence, and final verdict |
| Sanitized result/provenance and resume validation | Implemented |
| Admission qualification pipeline | Not implemented |
| Result signing | Not implemented |

The executable reference packs currently contain twenty-four Terminal-Bench rows
and three DeepSWE rows. The twenty-one incremental conversions from `bn-fit-modify`
through `gpt2-codegolf` are Approved after deterministic,
pinned-image, stopped-capture, adversarial, teardown, and model-backed
qualification. The twenty-one rows share a declarative `file_bundle`
capture-qualification matrix while retaining semantic, parser, asset-identity,
and replay evidence in focused row tests; the financial row extends that proof
to bounded directory entries and passive nested-file selection. The fix-code
row adds a two-file artifact/protocol Candidate, while `fix-git` masks
an image-bundled answer leak and adds exact-path Git ownership compatibility.
The `gcode-to-text` row returns to the one-file passive pattern with exact
source text normalization. `git-leak-recovery` adds passive, bounded,
configuration-sanitized inspection of loose and packed Git objects plus exact
declared nested-repository ownership compatibility. The intervening `feal-differential-cryptanalysis`,
`filter-js-from-html`, `fix-ocaml-gc`, and `git-multibranch` entries remain
Excluded because faithful adaptive Oracle interaction, trusted dynamic browser
verdicts, an independent bounded compiler/runtime scenario runner, and isolated
multi-participant system-service verification, respectively, are unavailable.
`gpt2-codegolf` adds bounded C compilation and two-case GPT-2 continuation
execution, including a private guard against the source verifier's fixed-output
shortcut. The first-wave control,
`sqlite-db-truncate`, and `vulnerable-secret` remain
qualification-pending in their dossiers and checklist; an inventory-level
Approved review disposition is not a completed runtime qualification. The
recommended example documents conform to the row schema. The HTTP-recorder
pattern used by the DeepSWE target example is now supported, while the
filesystem-overlay example remains intentionally non-executable.

## What is already correct for the schema's purpose

- Structural placement is authoritative. Rows cannot relabel a host resource as public without
  moving it across a compiler-enforced pack root.
- Component views are the materialization boundary: Agent gets public; Evaluation gets public plus
  runtime; Oracle gets public plus hidden; results get no live resources.
- Public assets use their declared read-only mounts in both Agent and relevant Evaluation
  runtimes. Runtime resources never enter the Agent container.
- A nested `/app` workdir may use a reviewed read-only public sibling mount to
  mask image-bundled answer material; writable sibling mounts and parent
  traversal remain rejected.
- Agent harnesses add process-local Git `safe.directory` entries only for the
  exact configured workdir and declared directory-tree Candidate roots,
  preserving bounded existing entries and rejecting ambiguous configuration
  rather than using a wildcard.
- Candidate capture is stopped-state, bounded, content-addressed, and baseline-bound.
- Filesystem-overlay public assets mounted below captured roots must select an existing baseline
  node with the same file/directory kind. Capture proves the underlying target subtree and required
  mount parents remain unchanged after Agent execution.
- The basic strict protocol path releases one bounded current Challenge at a time and constructs a
  fresh Evaluation root/container for every Challenge.
- Adapter stdout is bounded by raw byte count. Truncation and invalid UTF-8 cannot be normalized
  into an acceptable JSON observation.
- Tester, benchmark, Adapter, and Oracle YAML reject duplicate mapping keys rather than accepting
  parser-dependent last-key-wins behavior. Row JSONL, protocol JSON, resume records, and stored
  candidate manifests share finite, duplicate-key-free decoding semantics.
- `securebench.strict-json/v1` uses the same finite, duplicate-key-free decoder as protocol
  transport, so passive artifact parsing cannot interpret ambiguous objects differently.
- Directory-tree symlinks are an explicit row-level opt-in. Capture permits only bounded targets
  that resolve inside the same captured tree.
- Host/container path boundaries use conservative Unicode-normalized, case-folded comparisons for
  visibility roots, protected paths, generated materialization paths, mount collisions, and Git
  allow/exclude policies. Exact Linux workdir containment is still required where Docker mapping
  semantics depend on it.
- Executable preflight enforces framework capacities above row-authored bounds: 10,000 files and
  256 MiB for file bundles, 2,048 changed files / 128 MiB changed content / 16 MiB canonical patch
  for Git patches, and 10,000 entries / 256 MiB per passive artifact check.
- Oracle and adapter manifests fail closed, and Oracle manifests are validated during preflight
  without starting the process.
- Executable-capability matrix tests prove the registered batched profile, qualification-gated
  overlay candidate, and unknown Trusted Helper types fail preflight while unsupported. Overlay
  tests also prove the backend probe precedes Agent startup and is bound to the exact storage root.
- Adapter v2 validates closed typed Challenge and Observation values, exact Evaluation
  Participants, Trusted Helper requirements, Output Artifact declarations, and row limits against
  Adapter hard maximums before Candidate execution.
- Adapter v2 is the sole execution path. Other Adapter formats fail preflight; there is no weaker
  compatibility path with ambiguous Adapter/Candidate failure handling.
- SecureBench creates opaque Challenge and Evaluation IDs. Challenge Evidence rejects nested
  Trusted Helper or Output Artifact evidence carrying either ID from another Evaluation.
- Adapter-declared Output Artifacts are collected only after the one-shot Evaluation process exits.
  Regular files and directory trees are bounded before parsing, cannot traverse parent symlinks or
  reserved framework paths, and are correlated to the same Challenge and Evaluation. Candidate
  artifact failures remain Oracle evidence; collector/parser contract failures fail as framework
  infrastructure errors.
- The built-in HTTP recorder is registered as one contract/runtime pair. Every Evaluation creates
  a fresh internal Docker network, helper container, host state directory, and credential. The
  Adapter receives only the helper type, internal URL, and scoped authorization value.
- Recorder request count, target, headers, bodies, response settings, evidence bytes, and lifecycle
  operations are bounded. Authorization headers are redacted, the data-plane server exposes no
  control route, and the host revalidates row-reduced limits, hashes, sequence, and Challenge/
  Evaluation correlation before evidence reaches the Oracle.
- Helper containers have no published port or upstream network. Cleanup and helper-crash failures
  are classified as Trusted Helper infrastructure errors rather than Candidate evidence.
- Docker lifecycle calls used to create and remove persistent sandboxes, materialization
  containers, egress infrastructure, and provider relays have finite framework timeouts. Oracle
  teardown uses bounded terminate/kill/reap steps, and an unreaped Oracle becomes a sanitized
  infrastructure result.
- Candidate-reported failures are distinct from Adapter, Trusted Helper, and framework
  infrastructure failures. The public result format remains unchanged.
- For `repo_patch`, the digest-pinned image workdir must be a clean Git repository at the row's
  full `base_commit` before the Agent starts. Capture derives a binary-capable canonical patch from
  the stopped workspace using trusted Git state; it never consumes an Agent-authored patch file.
- Git patches replay only onto that same clean commit for every protocol case. Passive path
  artifacts are read from a separately reconstructed repository without importing or executing
  candidate code.
- Only Oracle output controls score, pass/fail, and check outcomes.
- Public result records exclude raw observations, hidden case context, Agent logs, and host paths.
- Resume revalidates complete filesystem-overlay manifests and chunks and can reuse a matching
  overlay Candidate; changing the quota capacity remains bound into execution provenance.

## Known alignment gaps and design debt

These do not invalidate the current supported slice, but they must not be described as complete
schema support.

1. Only the HTTP request recorder, append-only event ledger, and process
   supervisor have executable Trusted Helper runtimes. Other helper types must
   be reviewed, registered with finite contracts, and implemented explicitly.
2. Resource-usage evidence is not yet included in Challenge Evidence.
3. `restricted` and `internet` both currently permit only the tester's explicit domain allowlist;
   only `none` changes the row-level ceiling. This is safe, but the intended semantic distinction
   should be documented or implemented before relying on it for benchmark requirements.
4. The filesystem-overlay implementation is complete on macOS but deliberately non-executable.
   Activation still requires the deferred native root-Linux quota, real-Docker isolation, and leak
   qualification recorded in `next_steps.md`. That pass must also prove real image include roots,
   configured root Agent identity, canonical baseline permission semantics, and nested public-mount
   behavior before the source-controlled gate is enabled.
5. Pack-local Oracle code is trusted and hash-bound but runs as a sanitized host subprocess, not
   inside a stronger OS sandbox.
6. Assertion-free Adapters, component capability review, base/gold/mutant qualification, and
   semantic-fidelity review remain admission/governance responsibilities rather than mechanically
   proven row-schema properties.

The two operational hardening items that are consciously accepted and deferred during the first
conversion pilot are documented separately below. They are not reasons to weaken preflight or the
split-verification boundary.

## Accepted deferred operational hardening

The project is proceeding with a small, supervised Linux conversion pilot before addressing the
following two issues. Both are known availability/storage risks, not ways for a Candidate to see
hidden evaluation material or make its own verdict authoritative.

### Framework-owned quota for active Agent workspaces

The declared `file_bundle` and `git_patch` limits are enforced when SecureBench captures the
stopped Agent workspace. They bound the Candidate that crosses into Evaluation, but they do not
bound all bytes the Agent can write while it is working. An Agent can therefore create a very large
irrelevant file and consume the host-backed workspace even when the final declared Candidate is
small or is later rejected. If the underlying filesystem fills first, other rows or host services
can be disrupted before stopped-state capture applies its limits.

The overlay backend already has a hard quota design, but overlay execution is still disabled
pending native qualification and that quota does not protect the currently executable
`file_bundle` and `git_patch` paths. The eventual fix should either give those active workspaces a
framework-owned hard quota or require SecureBench to prove an equivalent deployment-owned isolated
storage boundary before starting the Agent. Exhausting a working quota should be reported as a
Candidate resource failure; inability to establish the promised boundary should fail before Agent
execution.

For the conversion pilot this risk is explicitly accepted. Run a small number of reviewed rows on
the dedicated Linux machine, start with one worker, use a separately bounded or monitored run
volume, and inspect free space between runs. This is an operational mitigation, not the final
framework guarantee. The framework change is deferred until conversion experience justifies the
common quota interface.

### Transactional publication for non-overlay Candidates

`file_bundle` and `git_patch` capture store content-addressed blobs before publishing the final
Candidate manifest. If capture is rejected, interrupted, or fails after one or more blob writes,
those blobs may remain without a manifest that references them. Each attempted Candidate remains
individually bounded at capture time and an orphan cannot be resumed or evaluated as a valid
Candidate, so this does not compromise scoring or test separation. Repeated failed runs can still
accumulate unused data in a long-lived output store.

Filesystem-overlay capture already stages its chunks transactionally and removes unpublished
content on failure. The preferred later fix is to give `file_bundle` and `git_patch` equivalent
staging and atomic publication semantics. A reference-aware garbage collector is a possible
fallback, but is more difficult because content-addressed blobs may legitimately be shared by
multiple published manifests and must never be removed while referenced.

For the conversion pilot this risk is also explicitly accepted. Use per-pilot output directories
on monitored storage and retain or discard them deliberately after reviewing results. Do not add an
unsafe blob-deletion shortcut. Transactional non-overlay capture remains future operational
hardening rather than a prerequisite for writing and qualifying the first converted rows.

## Verification evidence

At this review pass:

- full warning-strict suite: `1028 passed, 116 skipped`;
- complete protocol and Trusted Helper suite with Docker integration enabled:
  `54 passed, 1 skipped`, including fresh ordinary/recorder Evaluations,
  clean-repository git-patch replay, authenticated event-ledger traffic, external
  signal delivery, and leak-free teardown;
- `cancel-async-tasks` pinned-image qualification: the 14-test deterministic,
  reference, mutant, credential-forgery, premature-cancellation, and stopped-
  Agent capture/replay matrix passes;
- `cancel-async-tasks` API-key-backed `gpt-5.6-luna` smoke: score `1.0`, no
  infrastructure error, both protocol checks and all five cases passed;
  focused sandbox and live helper regression passes `81/81` after credential
  isolation, signal-readiness synchronization, and interruption cleanup
  hardening;
- `chess-best-move` passive qualification: `16/16` deterministic and pinned-
  image cases pass; its API-key-backed Luna smoke completed without
  infrastructure error and the Oracle correctly rejected the model's lone
  incorrect `d2h6` token;
- `circuit-fibsqrt` hybrid qualification: `24/24` deterministic and pinned-
  image cases pass, including the official reference across 32 fresh
  Evaluations and rejection of constant, identity, and one-line reference
  mutants plus a real out-of-bounds parser attack; its API-key-backed Luna
  smoke captured one bounded circuit,
  completed all 32 cases without infrastructure error, and was correctly
  rejected for `incorrect_output`;
- `cobol-modernization` protocol qualification: `19/19` deterministic and
  pinned-image cases pass, including the upstream reference across four fresh
  Evaluations and rejection of no-op, fixed-output, forged-verdict, and
  symlink-output Candidates; its API-key-backed Luna smoke produced exactly
  one bounded `program.py` and passed all four host-owned scenarios with score
  `1.0` and no infrastructure error;
- `code-from-image` passive qualification: `20/20` deterministic and
  pinned-image cases pass; its Luna smoke produced the exact bounded output and
  passed with score `1.0`;
- `count-dataset-tokens` passive qualification: `22/22` deterministic and
  pinned-image cases pass; the first Agent attempt exposed the missing
  Hugging Face domains in the Linux tester allowlist, and the corrected retry
  passed with score `1.0` and no infrastructure error;
- `crack-7z-hash` passive qualification: `23/23` deterministic and
  pinned-image cases pass; its Luna smoke produced no Candidate and was
  correctly rejected without infrastructure error;
- `db-wal-recovery` passive qualification: `31/31` deterministic and
  pinned-image cases pass; its Luna smoke produced no Candidate and was
  correctly rejected without infrastructure error;
- `distribution-search` passive qualification: `30/30` deterministic and
  pinned-image cases pass, including the reusable strict NPY parser and
  KL-axis mutants; its bounded Luna Candidate was correctly rejected for
  `forward_kl_out_of_tolerance` without infrastructure error;
- `dna-assembly` passive qualification: the focused deterministic suite passes
  `45 passed, 5 skipped` and the pinned-image row matrix passes `35/35`,
  including Primer3 2.6.1 Tm conformance, source-semantics comparison, assembly
  mutants, stopped capture, and malicious file shapes; its bounded Luna
  Candidate was correctly rejected for `missing_bsai_site` without
  infrastructure error;
- `dna-insert` passive qualification: the focused deterministic suite passes
  `28 passed, 5 skipped` and the pinned-image row matrix passes `33/33`,
  including source-positional quirks, insertion-boundary derivation, Tm and
  overlap mutants, stopped capture, and malicious file shapes; its Luna smoke
  produced no Candidate and was correctly rejected without infrastructure
  error;
- `extract-elf` protocol qualification: the focused deterministic suite passes
  `14 passed, 7 skipped` and the pinned-image row matrix passes `20 passed, 1
  skipped`, including the exact source reference across four fresh
  Evaluations, 75%-coverage and wrong-word mutants, forged output, stdout
  flooding, stopped capture, and malicious file shapes; its API-key-backed
  Luna smoke passed all four cases with score `1.0` and no infrastructure
  error;
- `extract-moves-from-video` passive qualification: the focused deterministic
  suite passes `30 passed, 7 skipped` and the pinned-image row matrix passes
  `37/37`, including exact source-transcript identity, universal-newline
  behavior, both adjacent edit-distance threshold boundaries, semantic
  mutants, stopped capture, and malicious file shapes; its Luna smoke produces
  no Candidate and is correctly rejected without infrastructure error;
- `feal-linear-cryptanalysis` passive qualification: the focused deterministic
  suite passes `19 passed, 7 skipped` and the pinned-image row matrix passes
  `26/26`, including exact source-token identity, delimiter-free and reordered
  source-accepted outputs, missing/changed/hexadecimal mutants, stopped
  capture, and malicious file shapes; its Luna smoke produces no Candidate and
  is correctly rejected without infrastructure error;
- `financial-document-processor` passive qualification: the generic nested
  directory-file selector passes `93/93` focused framework tests, the focused
  row suite passes `37 passed, 6 skipped`, and its pinned-image matrix passes
  `43/43`; exact source document identities and values, pandas 2.3.2 default-NA
  VAT behavior, directory placement,
  source-accepted set/CSV quirks, numeric/path mutants, stopped directory
  capture, passive nested summary parsing, and malicious tree shapes are
  covered; its bounded Luna Candidate reaches all four artifacts and is
  correctly rejected for `incorrect_invoice_placement` without infrastructure
  error;
- `fix-code-vulnerability` hybrid qualification: the focused deterministic
  suite passes `29 passed, 11 skipped`, and its pinned Linux matrix passes
  `40/40`; the untouched vulnerable source fails with a correct report, the
  reference passes all five fresh Evaluations and exact replay, and the
  original upstream-plus-hidden verifier passes `373/373`; its Luna smoke
  captures both bounded files and passes all five protocol cases without
  infrastructure error; the host correctly rejects its unrelated source edit
  and incorrect report;
- `fix-git` passive qualification: the focused warning-strict suite passes
  `36 passed, 5 skipped` and its pinned Linux matrix passes `41/41`; the gold
  directory is masked from the Agent, the untouched branch fails, and the real
  reflog recovery plus merge-conflict resolution passes the original two
  assertions and exact replay. Partial, forged, Unicode-whitespace, invalid-
  UTF-8, and malicious-shape Candidates fail; its Luna smoke captures both
  unchanged files without infrastructure error and is correctly rejected;
- `gcode-to-text` passive qualification: the focused warning-strict suite
  passes `20 passed, 5 skipped` and its pinned Linux matrix passes `25/25`;
  the 1,661,422-byte public input identity, source Unicode-whitespace and
  universal-newline behavior, exact reference replay, semantic mutants, and
  malicious file shapes are covered. Its Luna smoke produces bounded
  `SHAPE-BOX` output without infrastructure error and is correctly rejected;
- `git-leak-recovery` passive qualification: the focused warning-strict suite
  passes `27 passed, 4 skipped` and its pinned Linux matrix passes `31/31`;
  loose and packed objects, reachability, preserved history and worktree
  identity, hostile Git configuration, alternates, stopped replay, and
  malicious capture shapes are covered. Its API-key-backed Luna smoke passes
  both bounded artifacts with score `1.0` and no infrastructure error;
- `gpt2-codegolf` protocol qualification: all 18 focused deterministic and
  pinned-Linux tests pass, including the upstream reference, two fresh model
  cases, fixed-output, compiler/runtime, output-flood, forked-pipe-holder, and
  malicious capture/observation cases. Its API-key-backed Luna smoke completes
  without infrastructure error and is correctly rejected for incorrect output;
- the Docker pass left no Trusted Helper containers, materialization containers, Evaluation
  networks, or overlay volumes behind;
- complete Terminal configuration and self-audits: `97/97` passed with no
  failures or warnings;
- the generated Trusted Helper contract schema was refreshed for the reviewed
  HTTP and host-only access/credential modes, and its regeneration check passes;
- compile checks and `git diff --check` passed.

Useful commands:

```bash
uv run --no-sync --with pytest python -m pytest -q
.venv/bin/python -m tools.generate_schemas
.venv/bin/python -m securebench.cli audit-self --output-dir /tmp/securebench-audit
SECUREBENCH_DOCKER_INTEGRATION=1 uv run --no-sync --with pytest python -m pytest -q \
  tests/test_v2_protocol_verification.py -k 'real_fresh_docker or fresh_internal_docker'
```

## Branch and workspace state

- Original branch: `main` at `bf9a108` (`Complete isolated Terminal-Bench conversion`).
- Development branch: `split-verification-v2`.
- `main` is the merge-base and direct ancestor of the development branch.
- At the pulled `e716f6d` baseline, the development branch was thirty-two commits ahead and zero
  commits behind `main`.
- After publication, `origin/split-verification-v2` contains this review and hardening pass.

There is an unrelated malformed local ref named `refs/heads/main 2`; commands using `--all` may
warn or fail on it. Do not alter it without the repository owner's approval.

The following non-documentation paths remain outside this documentation cleanup:

- `benchmarks/terminal-bench/docker/db-wal-recovery/main.db-shm`
- `benchmarks/terminal-bench/docker/db-wal-recovery/main.db-wal`
