# `crack-7z-hash`

> Review status: **Reviewed with the SecureBench team**.

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

- [ ] Read the complete public instruction.
- [ ] Walk through the verifier entrypoint line by line.
- [ ] Identify every candidate-controlled input consumed by the verifier.
- [ ] Identify every scoring-relevant assertion and expected value.
- [ ] Decide whether the task's intended behavior is fully represented by its tests.
- [ ] Design the split-verification conversion.
- [ ] Record fidelity limitations and the final eligibility decision.

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
