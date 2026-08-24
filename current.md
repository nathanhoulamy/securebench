# Current SecureBench v2 state

Last reviewed: 2026-08-22

Implementation baseline reviewed: this branch through Output Artifacts, Trusted Helper execution,
git-patch execution, and the locally qualified filesystem-overlay implementation

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
| Passive artifact check using `source.entry` | Implemented for `file_bundle` |
| Artifact check using `source.path` | Implemented for bounded repository-relative `git_patch` paths and absolute paths mapped through fresh overlay roots |
| Registered passive parsers | JSON, UTF-8 text, ICS, and tree-manifest profiles exist |
| Basic protocol check | Implemented with finite JSON, bounded I/O, and a fresh offline container per Challenge |
| Adapter v2 contract | The only supported Adapter format; implemented with typed Challenge/Observation schemas, Evaluation Participants, Trusted Helper requirements, Output Artifacts, and reduced maximums |
| Challenge Evidence | Implemented with host Challenge/Evaluation IDs, correlation checks, and explicit failure source |
| Trusted Helper Catalog | Typed contracts, semantic preflight, reviewed runtime registration, and fail-closed lookup implemented |
| `securebench.http-request-recorder/v1` | Implemented end to end with fresh instances/credentials, internal-only networking, bounded request evidence, and correlated teardown |
| Output Artifacts | Implemented for bounded regular files and directory trees from the same disposable Evaluation |
| `strict-split/v1` | Implemented for file-bundle and git-patch execution and for qualification-gated overlay artifact/protocol paths, including the HTTP recorder Trusted Helper |
| `batched-split/v1` | Registered but explicitly not implemented |
| Host Oracle JSON-lines ABI | Implemented for initialize, artifact evidence, cases, case evidence, and final verdict |
| Sanitized result/provenance and resume validation | Implemented |
| Admission qualification pipeline | Not implemented |
| Result signing | Not implemented |

The reference executable pack currently contains one converted row:
`terminal-bench/constraints-scheduling`. The recommended example documents conform to the row
schema. The HTTP-recorder pattern used by the DeepSWE target example is now supported, while the
filesystem-overlay example remains intentionally non-executable.

## What is already correct for the schema's purpose

- Structural placement is authoritative. Rows cannot relabel a host resource as public without
  moving it across a compiler-enforced pack root.
- Component views are the materialization boundary: Agent gets public; Evaluation gets public plus
  runtime; Oracle gets public plus hidden; results get no live resources.
- Public assets use their declared read-only mounts in both Agent and relevant Evaluation
  runtimes. Runtime resources never enter the Agent container.
- Candidate capture is stopped-state, bounded, content-addressed, and baseline-bound.
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

## Known alignment gaps and design debt

These do not invalidate the current supported slice, but they must not be described as complete
schema support.

1. Only `securebench.http-request-recorder/v1` has an executable Trusted Helper runtime. Other
   helper types must be reviewed, registered with finite contracts, and implemented explicitly.
2. Resource-usage evidence is not yet included in Challenge Evidence.
3. `restricted` and `internet` both currently permit only the tester's explicit domain allowlist;
   only `none` changes the row-level ceiling. This is safe, but the intended semantic distinction
   should be documented or implemented before relying on it for benchmark requirements.
4. The filesystem-overlay implementation is complete on macOS but deliberately non-executable.
   Activation still requires the deferred native root-Linux quota, real-Docker isolation, and leak
   qualification recorded in `next_steps.md`.
5. Pack-local Oracle code is trusted and hash-bound but runs as a sanitized host subprocess, not
   inside a stronger OS sandbox.
6. Assertion-free Adapters, component capability review, base/gold/mutant qualification, and
   semantic-fidelity review remain admission/governance responsibilities rather than mechanically
   proven row-schema properties.
7. Currently executable file-bundle and git-patch Agent workspaces still lack a framework-owned
   disk quota. The overlay path has a quota backend, but it stays disabled pending native
   qualification. Deployment storage isolation remains necessary for active Candidate types.
8. Trusted benchmark resource trees and Git baselines are not subject to a framework-wide
   traversal-entry or subprocess wall-clock ceiling. They are author-controlled and hash-bound,
   rather than Candidate-controlled, but an oversized or malformed admitted pack can still consume
   excessive host resources during compilation, reconstruction, or patch validation.
9. Protocol payloads have per-case and per-component bounds, but there is no framework-owned total
   Evaluation budget yet. In particular, `max_cases`, the sum of per-case time, aggregate Trusted
   Helper evidence, and serialized Oracle request size are not capped across a whole row. A reviewed
   but impractical row can therefore consume excessive time or memory even though each individual
   component remains within its declared maximum.
10. Filesystem-overlay capture uses crash-recoverable transactions and removes unpublished chunks.
    Other Candidate capture paths can still write content-addressed blobs before committing their
    final manifest, so the run output directory still needs a storage quota for long-lived use.

## Verification evidence

At this review pass:

- full warning-strict suite: `498 passed, 6 skipped`;
- complete protocol suite with Docker integration enabled: `34 passed`, including two fresh
  combined recorder/Output Artifact Evaluations, the ordinary fresh Evaluation, and
  clean-repository git-patch replay;
- the Docker pass left no Trusted Helper containers, materialization containers, or Evaluation
  networks behind;
- built-in robustness audit: 5 passed, 0 failed, 0 warnings;
- no author-facing Pydantic field changed in this review, and schema regeneration produced no
  checked-in JSON Schema diff;
- a wheel and source distribution containing the reviewed tester, candidate-store, overlay,
  evidence, Oracle, helper, and artifact paths built successfully;
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
- Before this review pass, the development branch was twenty commits ahead and zero
  commits behind `main`.
- After publication, `origin/split-verification-v2` contains this review and hardening pass.

There is an unrelated malformed local ref named `refs/heads/main 2`; commands using `--all` may
warn or fail on it. Do not alter it without the repository owner's approval.

The following non-documentation paths remain outside this documentation cleanup:

- `benchmarks/terminal-bench/docker/db-wal-recovery/main.db-shm`
- `benchmarks/terminal-bench/docker/db-wal-recovery/main.db-wal`
