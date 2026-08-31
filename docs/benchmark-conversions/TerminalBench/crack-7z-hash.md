# `crack-7z-hash`

> Portfolio status: See [inventory.csv](../inventory.csv) for the authoritative review decision.

## Source facts

| Field | Value |
|---|---|
| Benchmark | Terminal-Bench 2.0 |
| Source row | [`crack-7z-hash`](https://github.com/harbor-framework/terminal-bench-2/tree/2fd12b88aafdd04a52c298e3940bcb189f9766d6/crack-7z-hash) |
| Source snapshot | `2fd12b88aafdd04a52c298e3940bcb189f9766d6` |
| Difficulty | medium |
| Category | security |
| Tags | decrypt, security, file-operations |
| Agent timeout | 1800.0 seconds |
| Verifier timeout | 900.0 seconds |
| Candidate image | `alexgshaw/crack-7z-hash:20251031` |
| Internet allowed | `True` |

## Goal in simple terms

Evaluates the ability to crack a password-protected 7z archive using John the Ripper and extract secret contents.

### Public instruction, condensed

You need to create a file called "/app/solution.txt" with the word found in "secret_file.txt" in the "secrets.7z" archive.

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

- `/app/solution.txt`

## What the tests check

### Test functions

- `test_solution_file` — Test that the solution file exists at the expected path.
- `test_solution_content` — Test that the solution file contains the correct password extracted from the 7z archive.

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

Clean conversion using passive artifact verification. Extract bounded
`/app/solution.txt` as the Candidate and place it read-only in the Evaluation
VM; no candidate-controlled code executes during evaluation. The Oracle
retrieves the file through a bounded artifact gateway, applies the original
whitespace normalization, and compares the bytes with the host-held expected
plaintext. No hidden test, expected answer, threshold, or scoring logic enters
either VM. John the Ripper usage and cracking provenance remain unobservable,
but the original verifier does not score them. **Manually approved after the
feasibility re-audit.**

## Implemented v2 conversion

Final status: **Approved**. The deterministic and digest-pinned Linux/Docker
matrices, stopped-Agent capture/replay, teardown inspection, audits, and Agent
smoke failure ownership are complete.

### Candidate boundary

The Candidate is one bounded `file_bundle` entry:

| Entry | Exact path | Kind | Per-file limit |
|---|---|---|---:|
| `solution` | `/app/solution.txt` | regular file | 4,096 bytes |

The aggregate maximum is one file and 4,096 bytes. Capture occurs only after
the Agent environment stops. `/app/secrets.7z`, the John the Ripper source and
build, extracted `secret_file.txt`, password/hash files, logs, caches,
credentials, installed state, processes, connections, mounts, and all other
workspace paths are intentionally excluded. The public prompt declares only
`/app/solution.txt` as a deliverable, so the boundary preserves every valid
solution without capturing cracking state or the full workspace.

### Verification design and behavior/trust mapping

The single `solution_artifact` check passively reads the declared regular file
with `securebench.utf8-text/v1` under the same 4,096-byte limit. Candidate bytes
are strictly decoded as UTF-8 and never imported, executed, deserialized as a
language object, or passed to a shell. There is no Adapter, protocol Challenge,
Output Artifact, Trusted Helper, or Evaluation ID.

| Public requirement | Independently observed evidence | Host-only Oracle decision |
|---|---|---|
| Create `/app/solution.txt` | Stopped-state capture extracts exactly one declared regular file | Missing, symlinked, non-regular, or oversized output fails closed |
| Put the word from the archived file in the solution | The bounded parser returns the complete UTF-8 text | Apply source `strip()` semantics and require exact equality with the trusted plaintext |
| Do not accept Candidate claims as verdicts | Only parsed file bytes reach the Oracle | Extra text, wrong words, and verdict claims fail; Candidate scores have no authority |

The host-only Oracle validates the check and artifact IDs, retains the expected
plaintext, normalizes and compares the text, and alone emits the score, check
outcome, diagnostics, and final verdict.

### Resource visibility

- Public: the complete instruction and digest-pinned image baseline containing
  `/app/secrets.7z` and the source task's John the Ripper build. The solving
  phase retains the original row's internet access.
- Evaluation-only: none. A passive artifact check does not create a
  Candidate-execution environment or verification-time network channel.
- Host-only: `crack-7z-hash/oracle/oracle.yaml`, `oracle.py`, the expected
  plaintext, comparison logic, scoring, and qualification expectations.

The original hidden pytest verifier is not copied, mounted, imported, or
executed in either candidate-controlled environment.

### Security design

Row bounds reduce framework capacity to one regular file and 4,096 bytes.
Executable preflight requires the entry below `/app`, rejects overlap with
framework materialization paths or public mounts, and binds capture to the
compiled baseline digest. Stopped-state capture uses no-follow regular-file
handling and rejects missing paths, symlinks, directories, special files,
oversize, and replacement races. The content-addressed Candidate manifest is
revalidated before passive replay.

The UTF-8 parser rejects malformed bytes. NUL-bearing valid UTF-8 remains inert
text and fails exact comparison. Candidate stdout, metadata, guest tests,
alternate files, extracted plaintext files, cracking logs, and claimed verdicts
never enter the decision path. Oracle comparison uses only a bounded string and
does not construct paths, commands, or executable objects from Candidate data.

### Semantic fidelity

The source verifier checks that `/app/solution.txt` exists, reads the complete
file with text mode, applies Python `strip()`, and compares it exactly with the
trusted plaintext. The v2 conversion preserves those semantics for valid
UTF-8. Missing, invalid-UTF-8, and other read failures remain Candidate
failures. The new 4,096-byte bound is far above a valid answer and has no
intelligence impact.

The verifier does not observe whether the Agent used John the Ripper, cracked
the archive, extracted `secret_file.txt`, or supplied a fixed known answer.
The v2 conversion preserves that inherited limitation rather than claiming
provenance that cannot be independently observed. The checked-in public
archive is 215 bytes, begins with the 7z signature, and has SHA-256
`a2e13fcbb4c2c8e92b1bf9d78ec91376705d1f5631d5bd4de64f82aa0553b773`.

### Pre-Linux qualification evidence (historical)

- Source revision:
  `2fd12b88aafdd04a52c298e3940bcb189f9766d6`.
- Working-tree base:
  `4159685e147ea77d51e5a776989ae4d492f5d6cc`; no implementation commit was
  created. The working tree also contains the preceding uncommitted
  `code-from-image` and `count-dataset-tokens` conversions.
- Registry-resolved image:
  `alexgshaw/crack-7z-hash@sha256:0f4453abd774c5a3d3d7e66ba28fae88ec2e49ada3a993b324ebc16c348666d3`.
  `docker buildx imagetools inspect` resolved the manifest; the image has not
  run locally.
- Compiled digests: manifest
  `sha256:b149ce25262dcd9111dda2460d6f5439c9576595995249570cd872fbe240d7a0`,
  row
  `sha256:f9fa9b555c5ac369ff0d7bc98204ddb689cfc68f131806b97695a0a5dd82fab6`,
  baseline
  `sha256:6cfb67e9df42b1e159849c29293b49baef15c45cdafd02d5af9d0fc67c81e4d3`,
  and verification
  `sha256:a0a7c2891cb75240987e7f8fbad79e3d471f8a0fb39b08aea3677ce7d72a75d1`.
  The exact-reference replay Candidate digest is
  `sha256:16cdd27a56d7408114f568e7b1d6f6ec6d4e867d036305b087d9b865159973f3`.
  No execution digest exists because no end-to-end run completed.
- Deterministic host: 2026-08-31, macOS 26.6.2 (Darwin 25.6.0), arm64,
  Python 3.13.5.
- Focused command:
  `uv run --no-sync --with pytest python -m pytest -q tests/test_crack_7z_hash_v2.py`.
  Result: `18 passed, 5 skipped` in 0.57 seconds; all skips are Docker-gated.
- Warning-strict focused regression command:
  `uv run --no-sync --with pytest python -m pytest -q -W error tests/test_crack_7z_hash_v2.py tests/test_v2_artifact_verification.py tests/test_v2_candidates.py`.
  Result: `66 passed, 5 skipped` in 3.63 seconds.
- Base/missing failure: missing Candidate evidence is rejected by the host
  Oracle without an infrastructure error. The untouched-image test is written
  but has not run.
- Reference success: exact plaintext and varied outer whitespace pass through
  real bounded capture, storage, UTF-8 parsing, and the host Oracle.
- Targeted-mutant rejection: truncated, extended, case-changed, and
  space-inserted plaintext fail.
- Malicious-Candidate handling: extra text, forged/structured verdict claims,
  a NUL suffix, and invalid UTF-8 fail; symlink, directory, and 4,097-byte files
  fail capture; undeclared extracted plaintext and cracking-log files are
  absent from the stored Candidate.
- Replay/isolation: the same content-addressed Candidate verifies twice with
  the same digest and no writable verification state. Protocol Evaluation,
  case, and credential freshness are not applicable to this passive row.
- Failure ownership: malformed and missing Candidate outputs produce benchmark
  failure without infrastructure error. Adapter and Trusted Helper failure
  classes are not applicable.
- The Docker-gated command was attempted once with
  `SECUREBENCH_DOCKER_INTEGRATION=1`; all 18 deterministic cases passed, while
  all five Docker cases failed before image materialization with
  `failed to remove image materialization container` because the Docker daemon
  was unavailable. This is infrastructure unavailability, not Candidate
  qualification evidence.
- The selected-row audit passes `5/5`. The complete eleven-row Terminal audit
  and self-audit each pass `45/45` with no failures or warnings. Reports are
  under `/tmp/securebench-crack-7z-hash-terminal-audit` and
  `/tmp/securebench-crack-7z-hash-self-audit`.
- Host teardown inspection found no running SecureBench or task process. The
  failed setup left five empty task workspaces inside pytest's 252-KiB session
  directory; that exact generated `pytest-9` directory was moved to the macOS
  Trash and no longer exists at its original path. Docker container, network,
  and volume inspection could not connect to the daemon, so leak-free Docker
  teardown is not established.
- No full repository suite or Agent smoke was run. No full-suite run is
  required because no shared framework code changed; the relevant regression
  suite passed with `-W error`.
- Final loading found eleven unique rows, compiled all eleven, and executable
  preflight passed for `terminal-bench/crack-7z-hash`. `git diff --check` also
  passed.

### Linux qualification completion

On 2026-08-31, Linux `7.0.0-29-generic` x86_64 with Docker 29.7.2
Linux/amd64 and `overlayfs` completed the missing qualification:

- the complete warning-strict pinned-image matrix passes `23/23` in `15.84s`,
  including untouched-image failure, reference, semantic-mutant,
  forged-claim, whitespace, replay, and malicious-shape cases;
- the API-key-backed `gpt-5.6-luna` smoke completes with no infrastructure
  error but no `/app/solution.txt`; Candidate capture is therefore rejected
  and the host Oracle returns the expected `candidate_capture_rejected`
  category rather than trusting Agent state;
- the smoke records row digest
  `sha256:f9fa9b555c5ac369ff0d7bc98204ddb689cfc68f131806b97695a0a5dd82fab6`,
  verification digest
  `sha256:b311d92c3d8b7cad7d559f938dcba1a9c86e86b9b4b0e6c6ec3b009ea44d6eb0`,
  and execution digest
  `sha256:5d1cfeb94862145b23bf2a40d4fa5769583cffd2b6293808f81cc4ea84d7a3aa`;
- the complete suite passes `728 passed, 51 skipped`, both complete audits
  pass `53/53`, and final Docker residue inspection is empty.

### Final qualification decision

**Approved — Clean conversion / no intelligence impact.** The smoke measures
cheap-model capability separately from conversion correctness; its failure
does not weaken the complete reference/mutant/malicious qualification matrix.
