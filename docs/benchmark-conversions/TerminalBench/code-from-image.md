# `code-from-image`

> Portfolio status: See [inventory.csv](../inventory.csv) for the authoritative review decision.

## Source facts

| Field | Value |
|---|---|
| Benchmark | Terminal-Bench 2.0 |
| Source row | [`code-from-image`](https://github.com/harbor-framework/terminal-bench-2/tree/2fd12b88aafdd04a52c298e3940bcb189f9766d6/code-from-image) |
| Source snapshot | `2fd12b88aafdd04a52c298e3940bcb189f9766d6` |
| Difficulty | medium |
| Category | software-engineering |
| Tags | ocr |
| Agent timeout | 1200.0 seconds |
| Verifier timeout | 1200.0 seconds |
| Candidate image | `alexgshaw/code-from-image:20251031` |
| Internet allowed | `True` |

## Goal in simple terms

Evaluates an agent's ability to extract code from an image using OCR or vision models, implement the pseudocode logic with cryptographic hashing, and produce the correct output.

### Public instruction, condensed

You're given an image of a pseudocode snippet at `/app/code.png`. Implement the intended logic of that snippet in any language and produce the same final value it would print. Write the result to `/app/output.txt`. - Hint: - For helping you make sure your solution is correct, the correct answer starts with `bee26a`

The complete public instruction remains available in the linked source row. The text above is included only to make this dossier usable during review.

## How the original row is evaluated

Terminal-Bench starts the task environment, allows the agent to work in it, and then invokes the row's verifier entrypoint. The verifier scripts below examine files, processes, services, or other state produced in that environment. Any Python assertion messages and test-function summaries listed here come directly from those verifier files.

### Verifier files

- `tests/test.sh`
- `tests/test_outputs.py`

### Test entrypoint and important commands

- `tests/test.sh`: `curl -LsSf https://astral.sh/uv/0.9.5/install.sh | sh`
- `tests/test.sh`: `-w pytest==8.4.1 \`
- `tests/test.sh`: `-w pytest-json-ctrf==0.3.5 \`
- `tests/test.sh`: `pytest --ctrf /logs/verifier/ctrf.json /tests/test_outputs.py -rA`

### Candidate artifacts, services, or paths referenced by tests

- `/app/output.txt`

## What the tests check

### Test functions

- `test_output_file_exists` — Verify the output file exists
- `test_output_is_correct` — Verify the output is correct

### Explicit acceptance or failure messages

- No literal Python assertion messages were extractable; inspect the verifier commands and source files listed below.

These messages are an inventory aid, not a substitute for reading the verifier. Assertions constructed dynamically, checks performed by external programs, and shell exit-code checks may not have a literal message.

## Questions for our later review

- [x] Read the complete public instruction.
- [x] Walk through the verifier entrypoint line by line.
- [x] Identify every candidate-controlled input consumed by the verifier.
- [x] Identify every scoring-relevant assertion and expected value.
- [x] Decide whether the task's intended behavior is fully represented by its tests.
- [x] Design the split-verification conversion.
- [x] Record fidelity limitations and the current qualification status.

## Future conversion notes

Clean passive-artifact conversion. Extract only a bounded regular-file
`/app/output.txt`; keep the hidden digest, checker, and scoring on the host.
The Oracle independently normalizes and compares the exact expected digest.
The original row measures only one fixed image/output pair, not OCR quality,
implementation method, or general image-to-code ability; preserve that as an
explicit limitation.

## Implemented v2 conversion

Final status: **Implemented — qualification pending**. The deterministic
conversion and qualification matrix are complete, but the real digest-pinned
Linux/Docker matrix has not run because the local Docker daemon was
unavailable. This row must not be marked Approved until that matrix and final
leak inspection pass.

### Candidate boundary

The single Candidate is a `file_bundle` containing exactly one declared entry:

| Entry | Exact path | Kind | Per-file limit |
|---|---|---|---:|
| `output` | `/app/output.txt` | regular file | 4,096 bytes |

The bundle permits at most one file and 4,096 aggregate bytes. Capture occurs
only after the Agent environment stops. The public `/app/code.png`, any
implementation source, installed packages, logs, caches, test output,
credentials, processes, connections, mounts, and every other workspace path
are intentionally excluded. The public prompt declares only
`/app/output.txt` as a deliverable, so the boundary admits every valid solution
allowed by the prompt while avoiding capture of the complete workspace.

### Verification design and behavior/trust mapping

The row uses one passive `artifact` check, `output_artifact`. It reads the
declared `output` entry with `securebench.utf8-text/v1` under the same 4,096-byte
limit. Candidate bytes are decoded as strict UTF-8 and are never imported,
executed, deserialized as a language object, or passed to a shell. There is no
Evaluation Adapter, protocol Challenge, Output Artifact, Trusted Helper, or
Evaluation ID because Candidate behavior does not need to execute during
verification.

| Public requirement | Independently observed evidence | Host-only Oracle decision |
|---|---|---|
| Create `/app/output.txt` | Stopped-state capture extracts the exact declared regular file | Missing, symlinked, non-regular, or oversized output fails closed |
| Produce the value printed by the image pseudocode | The bounded UTF-8 parser returns the Candidate's text | `text.strip()` must equal the trusted 64-character digest |
| Allow incidental outer whitespace | The parser preserves decoded text for Oracle normalization | Python `str.strip()` reproduces the original verifier's normalization |
| Do not accept claims in place of the answer | Only parsed artifact text reaches the Oracle | Prefixes, suffixes, forged verdicts, structured claims, NULs, and wrong digests fail |

The Oracle manifest and implementation are host-only. It validates the check
and artifact IDs, retains the exact expected digest, performs the comparison,
and alone emits the score, check outcome, diagnostics, and final verdict.
Candidate stdout, metadata, filenames other than the exact captured path, and
Candidate-authored pass/fail values have no authority.

### Resource visibility

- Public: the complete instruction and the pinned image baseline containing
  `/app/code.png`. The source-controlled public image is 95,041 bytes with
  SHA-256
  `f4d0330407b363a9ef03d563e5c2ffd24aa76345f997613741f9fc0935354305`.
- Evaluation-only: none. A passive artifact check creates no Candidate
  execution environment.
- Host-only: `code-from-image/oracle/oracle.yaml`, `oracle.py`, the exact
  expected digest, scoring logic, qualification expectations, and failure
  classification.

The original hidden verifier and its case data are neither copied nor mounted
into an Agent or Evaluation environment.

### Security design

The row reduces framework capacities to one regular file and 4,096 bytes.
Schema validation and executable preflight require the file to reside under
`/app`, prevent overlap with framework materialization paths or public mounts,
and bind capture to the compiled baseline digest. Stopped-state capture uses
no-follow regular-file handling, rejects symlinks, directories, special files,
oversized content, replacement races, and missing paths, and stores a
content-addressed replayable manifest. Passive observation revalidates the
stored Candidate and parser contract.

Strict UTF-8 rejects malformed encodings. NUL-bearing but otherwise valid
UTF-8 remains plain text and fails exact comparison, matching the source
verifier. Extra output, the public six-character hint alone, JSON or textual
verdict claims, and appended identifiers cannot influence the result. The
Candidate never receives Oracle code or the hidden exact digest through a
verification resource. There is no runtime networking, helper credential,
child process, filesystem output collection, or cross-case writable state to
attack during passive verification.

### Semantic fidelity

For well-formed UTF-8, the conversion preserves the source verifier exactly:
read the complete file, apply Python `strip()`, and require equality with
`bee26a133f103b9ecda444c70ec22cafef6e31a3de7af6d047974dc90ce3defe`.
The source's preceding `startswith("bee26a")` assertion is redundant because
exact equality implies it; dropping that separate diagnostic has no
intelligence impact. The 4,096-byte bound is a hardening distinction absent
from the source verifier, but it is far above the 64-character answer and does
not exclude a valid solution. Invalid UTF-8 failed the original verifier by
exception and remains a Candidate failure.

The public image was independently interpreted as hashing its own bytes,
concatenating the first SHA-256 digest with its first ten bytes and
`b"0000TBENCH-SALT"`, then hashing again. Recomputing that behavior from the
source-controlled image yields the host expectation. As inherited from the
source task, the benchmark accepts a fixed correct output and cannot establish
whether the Agent used OCR, vision, a particular implementation language, or
the displayed algorithm. It measures one fixed image/output pair and does not
test general image-to-code behavior. This is an original limitation, not a v2
semantic change.

### Qualification evidence actually obtained

- Source revision:
  `2fd12b88aafdd04a52c298e3940bcb189f9766d6`.
- Working-tree base:
  `4159685e147ea77d51e5a776989ae4d492f5d6cc`; no implementation commit was
  created.
- Registry-resolved image:
  `alexgshaw/code-from-image@sha256:2be9cdb746ed18c1b2b1404032efae0b2235a1b8fc479ef17730c95409d89f76`.
  `docker buildx imagetools inspect` resolved the manifest, but the image has
  not been run locally.
- Compiled digests: manifest
  `sha256:b149ce25262dcd9111dda2460d6f5439c9576595995249570cd872fbe240d7a0`,
  row
  `sha256:8376c4081d0e9c0d4011136d535446a2e2e6310563b05c2c1149f28d1517fb23`,
  baseline
  `sha256:8c5871c8e7ca54aeea1e517e30dadab98fd50536f34266d239f3e3389cf0f421`,
  and verification
  `sha256:5419590a8cbc213387d098b1e203ef10e192ce5956d91ec23a4ad142a52c3754`.
  The exact-reference replay Candidate digest is
  `sha256:eb764c37f7bb3c1edda130469f6875726fe7b799e2513757d886e5662a2d2362`.
  No execution digest exists because no end-to-end run completed.
- Deterministic host: 2026-08-31, macOS 26.6.2 (Darwin 25.6.0), arm64,
  Python 3.13.5.
- Focused command:
  `uv run --no-sync --with pytest python -m pytest -q tests/test_code_from_image_v2.py`.
  Result: `16 passed, 4 skipped` in 0.58 seconds; the four skips are the
  Docker-gated base/reference/mutant/forged-claim cases.
- Focused capture/artifact regression command:
  `uv run --no-sync --with pytest python -m pytest -q tests/test_code_from_image_v2.py tests/test_v2_artifact_verification.py tests/test_v2_candidates.py`.
  Result: `64 passed, 4 skipped` in 3.48 seconds.
- Base/missing failure: missing Candidate evidence is rejected by the host
  Oracle without an infrastructure error. The untouched pinned image test is
  written but has not run.
- Reference success: the exact digest and outer-whitespace variants pass
  through real bounded file-bundle capture, storage, passive parsing, and the
  host Oracle. The public `code.png` independently recomputes the same digest.
- Targeted-mutant rejection: public-prefix-only, wrong final nibble,
  case-changed digest, appended forged verdict, and structured verdict claim
  all fail with `incorrect_output`.
- Malicious-Candidate rejection: valid UTF-8 with a NUL suffix and invalid
  UTF-8 fail as Candidate evidence; symlink, directory, and 4,097-byte output
  shapes fail capture. An unrelated workspace log is excluded from the stored
  one-entry Candidate.
- Replay/isolation: the same content-addressed Candidate verifies twice with
  the same Candidate digest and no writable verification state. Protocol-case
  Evaluation and credential freshness are not applicable to this passive row.
- Failure ownership: missing or malformed Candidate output produces a failed
  benchmark result with no infrastructure error. Adapter and Trusted Helper
  failure classes are not applicable because neither component exists.
- The Docker-gated command was attempted once with
  `SECUREBENCH_DOCKER_INTEGRATION=1`; its deterministic portion passed 16
  tests, while all four Docker cases failed before image materialization with
  `failed to remove image materialization container` because the Docker daemon
  was unavailable. This is unavailable infrastructure, not qualification
  evidence for or against the Candidate.
- The selected-row static audit passes `5/5`. The complete nine-row Terminal
  audit and self-audit each pass `37/37` with no failures or warnings. Reports
  are under `/tmp/securebench-code-from-image-terminal-audit` and
  `/tmp/securebench-code-from-image-self-audit`.
- Host teardown inspection found no running SecureBench or task process. The
  failed daemon setup left four empty task workspaces inside pytest's own
  172-KiB session directory; that exact generated `pytest-3` directory was
  moved to the macOS Trash and no longer exists at its original path. Docker
  container, network, and volume inspection could not connect to the daemon,
  so leak-free Docker teardown is not established.
- The full warning-strict suite and an Agent smoke have not been run for this
  working tree. No full-suite run is required by the conversion guide because
  no shared framework code changed; the relevant focused regression suite did
  run with `-W error` and passed `64 passed, 4 skipped`.
- Final row loading compiled all nine unique tasks, executable preflight passed
  for `terminal-bench/code-from-image`, and `git diff --check` passed. A Ruff
  binary was not present in the locked local environment, so no Ruff result is
  claimed.

### Known limitations and remaining work

Run the complete real digest-pinned Linux/Docker matrix: untouched-image
failure; stopped-Agent reference success; targeted prefix mutant and forged
verdict rejection; malicious file-shape rejection through stopped capture;
exact Candidate replay; failure-ownership checks; and leak-free teardown. Then
repeat the one-row and complete Terminal configuration audits and self-audit on
the qualifying Linux revision, then repeat the final diff review. An Agent
smoke is optional qualification evidence and must be
attempted at most once after deterministic and Docker qualification pass.
Until the mandatory Docker evidence exists, the status remains
**Implemented — qualification pending**.
