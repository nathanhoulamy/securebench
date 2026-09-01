# `extract-moves-from-video`

> Portfolio status: See [inventory.csv](../inventory.csv) for the authoritative review decision.

## Source facts

| Field | Value |
|---|---|
| Benchmark | Terminal-Bench 2.0 |
| Source row | [`extract-moves-from-video`](https://github.com/harbor-framework/terminal-bench-2/tree/2fd12b88aafdd04a52c298e3940bcb189f9766d6/extract-moves-from-video) |
| Source snapshot | `2fd12b88aafdd04a52c298e3940bcb189f9766d6` |
| Difficulty | hard |
| Category | file-operations |
| Tags | file-operations, web, video-processing |
| Agent timeout | 1800.0 seconds |
| Verifier timeout | 1800.0 seconds |
| Candidate image | `alexgshaw/extract-moves-from-video:20251031` |
| Internet allowed | `True` |

## Goal in simple terms

Evaluates the agent's ability to download a YouTube video, extract text commands through OCR or transcription, and produce a formatted text file with 90% accuracy.

### Public instruction, condensed

Download this video of someone playing zork. https://www.youtube.com/watch?v=ZCbvyPbhRfA. Then transcribe the entire contents of the text, and create a file /app/solution.txt that has all the moves they input, one per line, in the format 'n' or 'get bag' etc.

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

- `test_solution_file_exists` — Test that the solution file exists
- `test_solution_content_similarity` — Test that the solution file content is similar to the expected solution

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
- [x] Record fidelity limitations and the final eligibility decision.

## Reviewed conversion design

Use passive artifact verification. Extract a bounded `solution.txt` candidate and have the host-side Oracle compute the original Levenshtein similarity against its host-held expected transcript and apply the 90% threshold. The Evaluation VM receives no expected transcript, hidden verifier, or scoring logic, and no candidate-controlled code executes. This preserves the original verifier's semantics, while video-faithfulness beyond reference-text similarity remains outside the benchmark. Verdict: clean conversion.

## Implemented v2 conversion

### Behavior mapping

| Public/source requirement | Passive evidence | Host-only decision |
|---|---|---|
| Create `/app/solution.txt` | One bounded regular-file Candidate entry is captured after the Agent stops | Missing, symlink, directory, or oversized shapes fail closed |
| Provide text moves | The registered UTF-8 parser returns exact hostile Candidate text without executing it | Invalid UTF-8 fails as Candidate evidence |
| Match the recorded moves with at least 90% source similarity | The whole parsed string is the only scored observation | The Oracle applies text-mode newline translation, character-level Levenshtein distance, and the source threshold |

The v2 row captures exactly `/app/solution.txt` as a one-file `file_bundle`,
with a 16,384-byte entry and aggregate bound. Its only check is the passive
`solution_artifact` check using `securebench.utf8-text/v1` with the same byte
limit. The solving image is pinned to
`alexgshaw/extract-moves-from-video@sha256:14a9dcca7d08ce53c5a0ed9fbd663a996ef28f207c199ed69d9ccf6064f8b184`.

No new framework capability, Adapter, Trusted Helper, Output Artifact, or
Evaluation execution was required. The row uses the existing stopped
`file_bundle` capture, passive UTF-8 parser, and host Oracle path, and adds one
declarative record to the compact shared Terminal capture matrix.

### Oracle boundary and bounds

The host Oracle owns a byte-for-byte copy of the source verifier's expected
transcript: 1,346 UTF-8 bytes, 1,346 characters, 280 lines, a final newline,
and SHA-256
`218abc48833a22f05d5655c157c81121cc5edf333059c2c34a65788e1065eceb`.
The copy is integrity-checked before scoring and never enters the Agent VM.

Python's source verifier opens the Candidate in default text mode, so CRLF and
bare-CR sequences are translated to LF before comparison. The Oracle performs
the same translation explicitly, then uses the source recurrence for
character-level Levenshtein distance. The source predicate
`100 * (1 - distance / max_length) >= 90` is equivalently enforced as
`distance * 10 <= max_length`; qualification checked equivalence across every
possible maximum length up to the row's byte bound. A length-difference lower
bound rejects obviously impossible Candidates before dynamic programming,
while every Candidate close enough to pass is evaluated with the full exact
recurrence. This keeps hostile worst-case work bounded without changing any
verdict.

### Resource visibility and security properties

- Public: the complete prompt, YouTube URL, and digest-pinned Ubuntu image.
  The Agent retains internet access; the Linux tester allowlist now includes
  `youtube.com`, `googlevideo.com`, and `ytimg.com`, matching the existing
  production Codex tester policy for this source task.
- Evaluation-only: none. Candidate content is never executed during
  verification.
- Host-only: `oracle.yaml`, `oracle.py`, and the pinned expected transcript.
  The threshold, comparison logic, expected text, and verdict remain on the
  host.

The durable Candidate excludes downloaded video, OCR/transcription scripts,
packages, caches, logs, processes, connections, credentials, and the rest of
the workspace. The original hidden pytest verifier is host-side qualification
input only and is never mounted or executed as the v2 verifier.

### Semantic fidelity

The conversion preserves the source's complete observable predicate:
case-sensitive whole-string comparison, character rather than line edits,
universal-newline translation, final-newline contribution, normalization by
the longer string, and an inclusive 90% threshold. Exact reference, CRLF,
small NUL-bearing edits, a 149-character append, and a 134-character suffix
deletion pass both source and v2 semantics. A 150-character append and a
135-character deletion are the adjacent failing boundaries.

The public prompt asks for one move per line and describes transcription of a
specific video, but the source verifier does not inspect the video, validate
individual lines, or measure move-level accuracy. For example, replacing all
line endings with spaces fails only because it creates 280 character edits,
and arbitrary extra text can pass while it remains inside the global edit
budget. The conversion deliberately preserves this inherited character-level
metric rather than claiming stronger video faithfulness. It also preserves
apparent reference spellings such as `drpo boat` and `emeral`; correcting them
can consume the same edit budget as any other change.

Strict UTF-8 and regular-file/no-follow capture narrow only malformed
encodings and unusable filesystem shapes. The 16 KiB bound is more than twelve
times the reference size and excludes no plausible move transcript. These are
contract-aligned hardenings with no expected intelligence impact.

### Qualification evidence

- The implementation and qualification are committed with the combined row
  batch at `fa23d3969b9cc61aefac8a2ff3a4a2c969e94d71` on branch
  `split-verification-v2`.
- Host: 2026-09-01, Linux `7.0.0-29-generic` x86_64, Docker 29.7.2
  Linux/amd64, with 184 GiB free during qualification.
- Focused deterministic command:
  `.venv/bin/python -m pytest -q -W error tests/test_extract_moves_from_video_v2.py tests/test_terminal_file_bundle_qualification.py -k 'extract-moves-from-video or extract_moves_from_video'`.
  Result: `30 passed, 7 skipped, 63 deselected`; skips are Docker-gated.
- Digest-pinned Linux command: the same command with
  `SECUREBENCH_DOCKER_INTEGRATION=1`. Result: `37 passed, 63 deselected`.
- Base failure and capture hardening: the untouched image has no declared
  Candidate; missing, symlink, directory, and oversized shapes fail closed.
- Reference and source fidelity: the checked-in host transcript is exactly
  equal to `SOLUTION` from the source verifier. Ten exact, newline, threshold,
  truncation, line-loss, case, order, and NUL variants produce the same source
  and Oracle distances and decisions.
- Targeted-mutant rejection covers the first append/delete beyond 90%, lost
  line breaks, changed case, reordered moves, empty text, and invalid UTF-8.
  Forged JSON verdict text cannot influence host scoring.
- Exact Candidate replay returns the same digest and verdict, and an unrelated
  downloaded-video file is excluded from the stored Candidate.
- The complete warning-strict suite passes `845 passed, 75 skipped`. Schema
  regeneration and `git diff --check` pass. Complete Terminal and self audits
  pass `69/69`, and the unchanged DeepSWE audit passes `13/13`, all without
  warnings. The isolated one-row audit passes `5/5`.
- The isolated API-key-backed `gpt-5.6-luna` smoke uses
  `reasoning_effort: none` and completes without infrastructure error. It
  produces no `/app/solution.txt`, so Oracle-owned Candidate-error handling
  correctly rejects it as `candidate_capture_rejected`, with no Candidate
  digest. Row digest:
  `sha256:e305443dcf2ec5ed9cc5b6dd540c78828034bf374e7ac0252885652bf752c9ae`;
  verification digest:
  `sha256:f4d8439bb6e77f274cb6d53d51e49ab2dd9265fe09298bdf940bb073ed4c0583`;
  execution digest:
  `sha256:d76fbf3a86c6007492e78df23761b40be47573214126b2eb7c53bf4464379c24`.
- Final inspection finds no surviving SecureBench container, network, volume,
  Agent process, downloader, or row-specific process. The configured image
  pruning removes the benchmark image.

### Final qualification decision

**Approved — Clean conversion / no intelligence impact.** The passive path
preserves the source's complete scoring behavior while keeping the expected
transcript, edit threshold, scoring logic, and final verdict solely on the
host and never executing Candidate content.
