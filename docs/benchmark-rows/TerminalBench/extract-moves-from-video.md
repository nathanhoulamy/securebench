# `extract-moves-from-video`

> Review status: **Reviewed with the SecureBench team**.

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

- [ ] Read the complete public instruction.
- [ ] Walk through the verifier entrypoint line by line.
- [ ] Identify every candidate-controlled input consumed by the verifier.
- [ ] Identify every scoring-relevant assertion and expected value.
- [ ] Decide whether the task's intended behavior is fully represented by its tests.
- [ ] Design the split-verification conversion.
- [ ] Record fidelity limitations and the final eligibility decision.

## Future conversion notes

Use passive artifact verification. Extract a bounded `solution.txt` candidate and have the host-side Oracle compute the original Levenshtein similarity against its host-held expected transcript and apply the 90% threshold. The Evaluation VM receives no expected transcript, hidden verifier, or scoring logic, and no candidate-controlled code executes. This preserves the original verifier's semantics, while video-faithfulness beyond reference-text similarity remains outside the benchmark. Verdict: clean conversion.
