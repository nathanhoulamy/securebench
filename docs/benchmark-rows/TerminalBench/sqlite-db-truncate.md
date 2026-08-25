# `sqlite-db-truncate`

> Review status: **Reviewed with the SecureBench team**.

## Source facts

| Field | Value |
|---|---|
| Benchmark | Terminal-Bench 2.0 |
| Source row | [`sqlite-db-truncate`](https://github.com/harbor-framework/terminal-bench-2/tree/2fd12b88aafdd04a52c298e3940bcb189f9766d6/sqlite-db-truncate) |
| Source snapshot | `2fd12b88aafdd04a52c298e3940bcb189f9766d6` |
| Difficulty | medium |
| Category | debugging |
| Tags | file-operations |
| Agent timeout | 900.0 seconds |
| Verifier timeout | 900.0 seconds |
| Candidate image | `alexgshaw/sqlite-db-truncate:20251031` |
| Internet allowed | `True` |

## Goal in simple terms

Evaluates the ability to recover data from a corrupted SQLite database using binary file analysis and data recovery techniques.

### Public instruction, condensed

I have a sqlite database in /app/trunc.db that was corrupted through binary truncation. Recover as many of the rows as possible, and create a JSON file in /app/recover.json. The output should have the format [{"word": "testwordXY", "value": M}, {"word": "testwordZZ","value": N}, ...]

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

- `/app/recover.json`

## What the tests check

### Test functions

- `test_json_data` — Json data

### Explicit acceptance or failure messages

- Did not load data correctly

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

Use passive artifact verification. Extract the bounded `recover.json` and compare its parsed `(word, value)` pairs in the host-side Oracle with the Oracle's secret recovered-row set and threshold; keep the corrupted database as challenge data only, and keep expected rows, the score rule, tests, and reference recovery out of both VMs. No candidate-controlled code executes during evaluation, and the Oracle trusts only the parsed artifact. Verdict: clean conversion; auto-approved under the first-pass policy.
