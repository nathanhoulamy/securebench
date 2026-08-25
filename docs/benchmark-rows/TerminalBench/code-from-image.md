# `code-from-image`

> Review status: **Not reviewed with the SecureBench team**. This file documents the original row only; it does not propose a conversion.

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

- [ ] Read the complete public instruction.
- [ ] Walk through the verifier entrypoint line by line.
- [ ] Identify every candidate-controlled input consumed by the verifier.
- [ ] Identify every scoring-relevant assertion and expected value.
- [ ] Decide whether the task's intended behavior is fully represented by its tests.
- [ ] Design the split-verification conversion.
- [ ] Record fidelity limitations and the final eligibility decision.

## Future conversion notes

Clean passive-artifact conversion. Extract only a bounded regular-file
`/app/output.txt`; keep the hidden digest, checker, and scoring on the host.
The Oracle independently normalizes and compares the exact expected digest.
The original row measures only one fixed image/output pair, not OCR quality,
implementation method, or general image-to-code ability; preserve that as an
explicit limitation.
