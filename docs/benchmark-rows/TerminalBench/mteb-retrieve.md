# `mteb-retrieve`

> Review status: **Reviewed with the SecureBench team**.

## Source facts

| Field | Value |
|---|---|
| Benchmark | Terminal-Bench 2.0 |
| Source row | [`mteb-retrieve`](https://github.com/harbor-framework/terminal-bench-2/tree/2fd12b88aafdd04a52c298e3940bcb189f9766d6/mteb-retrieve) |
| Source snapshot | `2fd12b88aafdd04a52c298e3940bcb189f9766d6` |
| Difficulty | medium |
| Category | data-science |
| Tags | data-processing, data-science, mteb |
| Agent timeout | 1800.0 seconds |
| Verifier timeout | 1800.0 seconds |
| Candidate image | `alexgshaw/mteb-retrieve:20251031` |
| Internet allowed | `True` |

## Goal in simple terms

Evaluates the agent's ability to perform semantic text retrieval using MTEB embeddings, computing cosine similarities and correctly ranking documents to find the 5th most similar match to a query.

### Public instruction, condensed

Given the query "terminal-bench" retrieve the document with the 5th highest cosine similarity among the texts at /app/data.txt, where each line is a separate document, using the bge-small-zh-v1.5 embedding model at revision 7999e1d3359715c523056ef9478215996d62a620. Write the resulting line to /app/result.txt. You have the mteb package at version 1.36.8 installed.

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

- `/app/result.txt`

## What the tests check

### Test functions

- `test_result_exists` — Result exists
- `test_data_matches` — Data matches

### Explicit acceptance or failure messages

- result.txt file does not exist
- result.txt should contain exactly one line
- result.txt contains unexpected value

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

Use passive artifact verification. The public retrieval data and model information remain available in the Agent VM. Extract the bounded one-line `result.txt` and compare it in the host-side Oracle with the host-held expected fifth-ranked document, reproducing the original stripping and exact-string predicate. Candidate-controlled code need not execute during evaluation; hidden tests, the expected answer, scoring logic, and reference solution remain outside both VMs. The original exact-answer assertion is fully externally observable and semantically unchanged. Verdict: clean conversion; confirmed in the final clean-conversion audit.
