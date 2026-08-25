# `gcode-to-text`

> Review status: **Reviewed with the SecureBench team**.

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
| Candidate image | `alexgshaw/gcode-to-text:20251031` |
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

- [ ] Read the complete public instruction.
- [ ] Walk through the verifier entrypoint line by line.
- [ ] Identify every candidate-controlled input consumed by the verifier.
- [ ] Identify every scoring-relevant assertion and expected value.
- [ ] Decide whether the task's intended behavior is fully represented by its tests.
- [ ] Design the split-verification conversion.
- [ ] Record fidelity limitations and the final eligibility decision.

## Future conversion notes

Use passive artifact verification. The public G-code input remains available in the Agent VM. Extract only a bounded regular `out.txt` and have the host-side Oracle reproduce the original whitespace normalization and compare the result with its host-held expected flag. No candidate-controlled code executes during evaluation; hidden tests, the expected flag, scoring logic, and reference material remain outside both VMs. Reject symlinks, devices, oversized files, and unexpected paths. Verdict: clean conversion; confirmed in the final clean-conversion audit.
