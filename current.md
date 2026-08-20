# Current SecureBench v2 state

Last reviewed: 2026-08-20

Implementation baseline reviewed: `e311c3a` plus the schema/runtime alignment pass

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
   fresh, offline Evaluation container for every current Oracle-selected case.
9. Internal evidence goes to the host Oracle. Public results contain only bounded diagnostics,
   digests, check summaries, and provenance.
10. The stopped Agent workspace and disposable Evaluation roots are removed.

Candidate-production and capture failures are sent to the Oracle as candidate-error evidence;
the runner does not invent a benchmark score.

## Schema-to-runtime capability matrix

| Schema/design area | Current state |
|---|---|
| Manifest defaults and closed v2 rows | Implemented |
| `repo_patch` and `terminal_task` family contracts | Implemented at schema level |
| Digest-pinned images and Agent timeout/network fields | Implemented |
| Three structural visibility lanes | Implemented and centrally enforced |
| Non-overlapping, symlink-safe resource roots | Implemented |
| `file_bundle` candidate | Implemented end to end, including bounded directory trees |
| `git_patch` candidate | Capture/replay primitives exist; end-to-end harness and verification path is blocked |
| `filesystem_overlay` candidate | Schema only; capture format and engine are not implemented |
| Passive artifact check using `source.entry` | Implemented for `file_bundle` |
| Artifact check using `source.path` | Schema-valid; blocked because patch/overlay execution is not available |
| Registered passive parsers | JSON, UTF-8 text, ICS, and tree-manifest profiles exist |
| Basic protocol check | Implemented with finite JSON, bounded I/O, and a fresh offline container per case |
| Protocol trusted services | Schema-valid; explicitly rejected by preflight |
| Protocol returned artifacts | Schema-valid; explicitly rejected by preflight |
| `strict-split/v1` | Implemented for the current file-bundle/artifact/basic-protocol slice |
| `batched-split/v1` | Registered but explicitly not implemented |
| Host Oracle JSON-lines ABI | Implemented for initialize, artifact evidence, cases, case evidence, and final verdict |
| Sanitized result/provenance and resume validation | Implemented |
| Admission qualification pipeline | Not implemented |
| Result signing | Not implemented |

The reference executable pack currently contains one converted row:
`terminal-bench/constraints-scheduling`. The three recommended example documents conform to the
row schema, but the DeepSWE service example and filesystem-overlay example are intentionally not
executable yet.

## What is already correct for the schema's purpose

- Structural placement is authoritative. Rows cannot relabel a host resource as public without
  moving it across a compiler-enforced pack root.
- Component views are the materialization boundary: Agent gets public; Evaluation gets public plus
  runtime; Oracle gets public plus hidden; results get no live resources.
- Public assets use their declared read-only mounts in both Agent and relevant Evaluation
  runtimes. Runtime resources never enter the Agent container.
- Candidate capture is stopped-state, bounded, content-addressed, and baseline-bound.
- The basic strict protocol path releases one bounded current challenge at a time and constructs a
  fresh Evaluation root/container for every case.
- Adapter stdout is bounded by raw byte count. Truncation and invalid UTF-8 cannot be normalized
  into an acceptable JSON observation.
- Benchmark, adapter, and Oracle authoring documents reject duplicate mapping keys rather than
  accepting parser-dependent last-key-wins behavior. Row JSONL and protocol JSON additionally
  share finite, duplicate-key-free decoding semantics.
- `securebench.strict-json/v1` uses the same finite, duplicate-key-free decoder as protocol
  transport, so passive artifact parsing cannot interpret ambiguous objects differently.
- Directory-tree symlinks are an explicit row-level opt-in. Capture permits only bounded targets
  that resolve inside the same captured tree.
- Oracle and adapter manifests fail closed, and Oracle manifests are validated during preflight
  without starting the process.
- Executable-capability matrix tests prove the registered batched profile, patch and overlay
  candidates, protocol services, and returned protocol artifacts fail preflight while unsupported.
- Only Oracle output controls score, pass/fail, and check outcomes.
- Public result records exclude raw observations, hidden case context, Agent logs, and host paths.

## Known alignment gaps and design debt

These do not invalidate the current supported slice, but they must not be described as complete
schema support.

1. The implemented protocol evidence has `check_id`, `case_index`, and `challenge_digest`, but not
   the full future envelope's host-generated case ID, correlation ID, resource usage, service
   evidence, or returned-artifact evidence.
2. The adapter manifest is intentionally minimal (`abi`, `protocol`, `command`). Typed request and
   observation schemas, topology, service slots, handle injection, and output artifact declarations
   still need versioned component contracts.
3. `restricted` and `internet` both currently permit only the tester's explicit domain allowlist;
   only `none` changes the row-level ceiling. This is safe, but the intended semantic distinction
   should be documented or implemented before relying on it for benchmark requirements.
4. Git-patch primitives are not yet connected to the declared `base_commit`, stopped-workspace
   extraction, generic candidate replay, artifact paths, or protocol evaluation.
5. The filesystem-overlay canonical format and protected-root policy remain intentionally
   unspecified and unimplemented.
6. Pack-local Oracle code is trusted and hash-bound but runs as a sanitized host subprocess, not
   inside a stronger OS sandbox.
7. Assertion-free adapters, component capability review, base/gold/mutant qualification, and
   semantic-fidelity review remain admission/governance responsibilities rather than mechanically
   proven row-schema properties.

## Verification evidence

At the implementation baseline above:

- full suite: `334 passed, 1 skipped`;
- the skipped real-Docker protocol test passed separately with
  `SECUREBENCH_DOCKER_INTEGRATION=1`;
- built-in robustness audit: 5 passed, 0 failed, 0 warnings;
- generated JSON Schemas matched the checked-in files;
- a wheel built successfully and imported outside the repository;
- the live protocol test leaked no new SecureBench container.

Useful commands:

```bash
uv run --no-sync --with pytest python -m pytest -q
.venv/bin/python -m tools.generate_schemas
.venv/bin/python -m securebench.cli audit-self --output-dir /tmp/securebench-audit
SECUREBENCH_DOCKER_INTEGRATION=1 uv run --no-sync --with pytest python -m pytest -q \
  tests/test_v2_protocol_verification.py::test_protocol_check_runs_in_real_fresh_docker_evaluation
```

## Branch and workspace state

- Original branch: `main` at `bf9a108` (`Complete isolated Terminal-Bench conversion`).
- Development branch: `split-verification-v2`.
- `main` is the merge-base and direct ancestor of the development branch.
- Before this alignment pass, the development branch was twelve commits ahead and zero
  commits behind `main`.
- `origin/split-verification-v2` contained all committed work through `e311c3a`.

There is an unrelated malformed local ref named `refs/heads/main 2`; commands using `--all` may
warn or fail on it. Do not alter it without the repository owner's approval.

The following non-documentation paths remain outside this documentation cleanup:

- `benchmarks/terminal-bench/docker/db-wal-recovery/main.db-shm`
- `benchmarks/terminal-bench/docker/db-wal-recovery/main.db-wal`
