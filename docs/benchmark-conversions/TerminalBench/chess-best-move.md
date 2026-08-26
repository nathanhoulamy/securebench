# `chess-best-move`

> Portfolio status: See [inventory.csv](../inventory.csv) for the authoritative review decision.

## Source facts

| Field | Value |
|---|---|
| Benchmark | Terminal-Bench 2.0 |
| Source row | [`chess-best-move`](https://github.com/harbor-framework/terminal-bench-2/tree/2fd12b88aafdd04a52c298e3940bcb189f9766d6/chess-best-move) |
| Source snapshot | `2fd12b88aafdd04a52c298e3940bcb189f9766d6` |
| Difficulty | medium |
| Category | games |
| Tags | games |
| Agent timeout | 900.0 seconds |
| Verifier timeout | 900.0 seconds |
| Candidate image | `alexgshaw/chess-best-move:20251031` |
| Internet allowed | `True` |

## Goal in simple terms

Evaluates the agent's ability to analyze a chess position from an image, use a chess engine to find the best move(s), and handle multiple valid solutions.

### Public instruction, condensed

The file chess_board.png has an image of a chess board. It is currently white to move. Write the best move for white to play to /app/move.txt in the form [src][dst], for example, e2e4 or h1h8. If there are multiple winning moves, print them all, one per line.

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

- `/app/move.txt`

## What the tests check

### Test functions

- `test_move_correct` — Test that the chess engine finds the optimal checkmate-in-one moves. This test verifies that the chess engine correctly identifies both possible checkmate-in-one moves in a specific position: - g2g4: Pawn move that delivers checkmate -…

### Explicit acceptance or failure messages

- File is wrong

These messages are an inventory aid, not a substitute for reading the verifier. Assertions constructed dynamically, checks performed by external programs, and shell exit-code checks may not have a literal message.

## Questions for our later review

- [x] Read the complete public instruction.
- [x] Walk through the verifier entrypoint line by line.
- [x] Identify every candidate-controlled input consumed by the verifier.
- [x] Identify every scoring-relevant assertion and expected value.
- [x] Decide whether the task's intended behavior is fully represented by its tests.
- [x] Design the split-verification conversion.
- [x] Record fidelity limitations and the final eligibility decision.

## Future conversion notes

Clean passive-artifact conversion. Extract only a bounded regular-file
`/app/move.txt`; do not place the hidden checker or expected move set in the
Evaluation VM. The host Oracle parses the whitespace-separated tokens and
compares them with its trusted expected set, preserving the exact multiset
`{g2g4, e2e4}` while rejecting extra, missing, duplicate, symlink, or oversized
artifacts.

## Implemented v2 conversion

Final status: **Approved**. The conversion is a passive artifact check; no
Candidate code runs during verification and no Evaluation Adapter or Trusted
Helper is required.

### Behavior and trust mapping

| Public requirement | Independently observed evidence | Host-only Oracle decision |
|---|---|---|
| Produce `/app/move.txt` | Stopped-state capture extracts one bounded regular file and the UTF-8 parser returns its text | Missing, non-regular, oversized, or invalid UTF-8 output fails closed |
| Report every winning move | The Oracle applies the source checker's `strip().split()` tokenization | The exact multiset is `e2e4` and `g2g4` |
| Permit either ordering and ordinary whitespace | Parsed text retains Candidate bytes until Oracle tokenization | Token order and whitespace layout do not affect the verdict |
| Reject incomplete or claimed results | Tokens are compared without consuming Candidate metadata or stdout | Missing, extra, duplicate, case-changed, wrong, and verdict-claim tokens fail |

The Agent runs in the digest-pinned source image, where the public 37,022-byte
PNG remains at `/app/chess_board.png`. Only `/app/move.txt` crosses the stopped
Agent boundary. The image, installed packages, logs, processes, and all other
workspace state are absent from the Candidate. Verification passively reads at
most 4,096 bytes and never imports or executes Candidate content.

This preserves the original check exactly for well-formed text: Python's
default UTF-8 `read_text()`, then `strip().split()`, followed by sorted-list
equality. The finite file bound is tighter than the source verifier but far
above any valid two-move answer and therefore has no intelligence impact.
Invalid UTF-8 was an exception/failure in the source and remains a Candidate
failure. The conversion intentionally does not independently recompute chess
optimality from the image; the source task itself fixes one position and one
expected move multiset, which remains host-only Oracle data.

### Qualification evidence

- Source revision: `2fd12b88aafdd04a52c298e3940bcb189f9766d6`.
- Conversion implementation commit:
  `c3958a188db6565afed2a8de311c20bb036d7bdb` (base
  `42341234fc9ea426368423a57c376d55ff5a6254`).
- Pinned image:
  `alexgshaw/chess-best-move@sha256:bb447f94d9e2a8ed879f85c85a514b213b7418f9fe11fd7b2428a0b0e436e647`
  (`linux/amd64`, workdir `/app`). The image contains a PNG-signature board
  asset of 37,022 bytes.
- Deterministic qualification passes reference answers in both orders and
  varied whitespace; missing/base, missing/extra/duplicate/wrong/case-changed
  moves, forged verdict tokens, invalid UTF-8, symlink, directory, and
  oversized artifacts fail as intended: `14 passed, 2 skipped` without Docker.
- Pinned-image qualification proves the untouched image fails Candidate
  capture and a reference answer passes stopped-Agent capture and host-only
  replay: `16 passed` in `2.25s` with Docker integration enabled.
- The one-row robustness audit passes `5/5`; the complete six-row Terminal
  configuration audit passes `25/25` with no warnings.
- The full warning-strict repository suite passes `577 passed, 19 skipped`.
- An API-key-backed `gpt-5.6-luna` / `reasoning_effort: none` smoke completed
  without infrastructure error. The model wrote only `d2h6`, so the Oracle
  correctly returned score `0.0` and `incorrect_move_set`; model skill is not a
  conversion requirement for this smoke. The durable result is
  `runs/terminal-bench-v2-chess-smoke/results.jsonl`, with Candidate digest
  `sha256:a09e8e1eb482032565f1614b67007809bf0f15c0e01c9740351b634c70bff358`,
  row digest
  `sha256:0d35e8a0ea1b241a1a799973e22c6f26efa725e870b4e287d46dfaa7a8c103aa`,
  verification digest
  `sha256:f83e61514512ca63d4d83da36d7ddab7a5ccfef966b2ed8b6dd0b942a2e85702`,
  and execution digest
  `sha256:074fb4d6fdae8b6b252c823498a4332343de4fb6e524f521ee73fbdbe9ffd7d2`.
- Final teardown inspection found no SecureBench container, network, volume,
  Evaluation root, or Trusted Helper state.
