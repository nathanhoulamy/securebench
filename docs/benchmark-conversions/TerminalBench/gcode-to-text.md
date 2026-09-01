# `gcode-to-text`

> Portfolio status: See [inventory.csv](../inventory.csv) for the authoritative review decision.

## Source facts

| Field | Value |
|---|---|
| Benchmark | Terminal-Bench 2.0 |
| Source row | [`gcode-to-text`](https://github.com/harbor-framework/terminal-bench-2/tree/2fd12b88aafdd04a52c298e3940bcb189f9766d6/gcode-to-text) |
| Source snapshot | `2fd12b88aafdd04a52c298e3940bcb189f9766d6` |
| Difficulty | medium |
| Category | file-operations |
| Tags | file-operations |
| Agent timeout | 900.0 seconds |
| Verifier timeout | 900.0 seconds |
| Candidate image | `alexgshaw/gcode-to-text@sha256:0979ef40c6a3e8c4e7ab5b6c2524c74625a84799e15cd45dd98dcf83b11efd4d` |
| Internet allowed | `True` |

## Goal in simple terms

Tests the agent's ability to extract and decode text from a 3D printer G-code file by parsing movement commands, rendering them visually, and performing OCR.

### Public instruction, condensed

I have provided a file called text.gcode. This is a gcode file for a Prusa MK4s. I'm trying to print some text onto an existing object. When I run the print, what will the text show? Write the output to /app/out.txt

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

- `/app/out.txt`

## What the tests check

### Test functions

- `test_hello_file_exists` — Test that out.txt file exists in the current directory.
- `test_hello_file_content` — Test that out.txt contains exactly the flag.

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

## Implemented v2 conversion

The conversion uses passive artifact verification. The public G-code remains in
the pinned Agent image, while the expected decoded text and all verdict logic
remain host-only.

### Candidate and input boundary

The Linux/amd64 image is pinned to
`alexgshaw/gcode-to-text@sha256:0979ef40c6a3e8c4e7ab5b6c2524c74625a84799e15cd45dd98dcf83b11efd4d`.
Its `/app/text.gcode` public challenge is 1,661,422 bytes with reviewed SHA-256
`17f1dfca4f3b02bf8917c02b32688282b92af51e4d1351cde0f814cbe85c6193`.

The stopped Candidate is exactly one regular `/app/out.txt`, capped at 4 KiB.
The 1.6 MiB input, caches, renderings, OCR scripts, packages, logs, processes,
connections, and credentials do not cross the Agent boundary.

### Passive evidence and host Oracle

The artifact check uses `securebench.utf8-text/v1` with the same 4 KiB bound.
The host-only Oracle reproduces `Path.read_text().strip()` by applying Python
universal-newline translation and Unicode `str.strip()`, then compares the
result with the host-held expected text. Expected bytes, assertions, score, and
verdict logic never enter the Agent or an Evaluation VM. Candidate content is
never imported or executed.

This deliberately accepts every source-accepted leading/trailing ASCII or
Unicode whitespace form, including CR/LF variants, while rejecting changed
case, internal substitutions, explanatory prefixes/suffixes, empty content,
and forged text or structured verdict claims.

### Semantic fidelity and limitations

The original verifier scores only existence of `/app/out.txt` and exact decoded
text after text-mode normalization and stripping. The v2 Candidate and Oracle
preserve that complete scored surface. The method used to decode or render the
G-code is intentionally unobservable in both versions.

Invalid UTF-8 fails in the v2 parser rather than raising inside the source
verifier. Both reject it; only the internal failure category changes. The input
is intentionally public because interpreting it is the task itself, and it
contains no separate verifier fixture or trusted answer file.

### Qualification evidence

- Qualification working tree: branch `split-verification-v2`, based on
  `fa23d3969b9cc61aefac8a2ff3a4a2c969e94d71` plus the pending financial,
  `fix-code-vulnerability`, `fix-git`, and compatibility refinements.
- Host: 2026-09-01, Linux `7.0.0-29-generic` x86_64, Docker 29.7.2,
  Linux/amd64 image.
- Focused warning-strict deterministic qualification passes
  `20 passed, 5 skipped, 87 deselected`; skips are Docker-gated.
- The consolidated exact-image Linux matrix passes
  `25 passed, 87 deselected`.
- The absent baseline output fails capture. The reviewed reference passes the
  original two source assertions, stopped capture, host Oracle, and exact
  Candidate replay.
- Wrong-case, internal-substitution, explanatory-prefix/suffix, empty,
  forged-verdict, invalid-UTF-8, duplicate/uncorrelated, missing, symlink,
  directory, and oversized Candidates fail or cannot affect scoring.
- The complete warning-strict repository suite passes
  `997 passed, 109 skipped`. Terminal and self audits pass `89/89`; unchanged
  DeepSWE passes `13/13`; the isolated row audit passes `5/5`, all without
  warnings.
- The API-key-backed `gpt-5.6-luna` smoke uses `reasoning_effort: none`, captures
  one bounded ten-byte output, completes verification without infrastructure
  error, and is correctly rejected because it reports `SHAPE-BOX`. Candidate
  digest:
  `sha256:23bbd89a0fa21af9532cbdcf44e081c6f30f41dc6dba823e3a0bf942e8eabf05`;
  row digest:
  `sha256:100452e8ddb6859566a635257062c2b87b2be715093ac6f653dbdee00dfa7a9c`;
  verification digest:
  `sha256:d664720f4d09c313a79a5f07170ab79d973434ab4d6446200e73e967e5425d2f`;
  execution digest:
  `sha256:074fb4d6fdae8b6b252c823498a4332343de4fb6e524f521ee73fbdbe9ffd7d2`.
- Harness teardown prunes the task image and leaves no row container, network,
  volume, Agent, or task-specific process.

### Final qualification decision

**Approved — Clean conversion / no intelligence impact.** The single bounded
stopped artifact and host-owned exact-text Oracle preserve the complete source
verifier semantics without executing Candidate code or trusting its claims.
