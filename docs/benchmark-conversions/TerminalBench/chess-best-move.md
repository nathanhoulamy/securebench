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

- [ ] Read the complete public instruction.
- [ ] Walk through the verifier entrypoint line by line.
- [ ] Identify every candidate-controlled input consumed by the verifier.
- [ ] Identify every scoring-relevant assertion and expected value.
- [ ] Decide whether the task's intended behavior is fully represented by its tests.
- [ ] Design the split-verification conversion.
- [ ] Record fidelity limitations and the final eligibility decision.

## Future conversion notes

Clean passive-artifact conversion. Extract only a bounded regular-file
`/app/move.txt`; do not place the hidden checker or expected move set in the
Evaluation VM. The host Oracle parses the whitespace-separated tokens and
compares them with its trusted expected set, preserving the exact multiset
`{g2g4, e2e4}` while rejecting extra, missing, duplicate, symlink, or oversized
artifacts.
