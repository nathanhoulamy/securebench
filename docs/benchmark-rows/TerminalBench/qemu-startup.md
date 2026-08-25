# `qemu-startup`

> Review status: **Reviewed with the SecureBench team**.

## Source facts

| Field | Value |
|---|---|
| Benchmark | Terminal-Bench 2.0 |
| Source row | [`qemu-startup`](https://github.com/harbor-framework/terminal-bench-2/tree/2fd12b88aafdd04a52c298e3940bcb189f9766d6/qemu-startup) |
| Source snapshot | `2fd12b88aafdd04a52c298e3940bcb189f9766d6` |
| Difficulty | medium |
| Category | system-administration |
| Tags | sys-admin |
| Agent timeout | 900.0 seconds |
| Verifier timeout | 900.0 seconds |
| Candidate image | `alexgshaw/qemu-startup:20251031` |
| Internet allowed | `True` |

## Goal in simple terms

Evaluates the agent's ability to configure and start a QEMU virtual machine with telnet-accessible serial console, requiring knowledge of QEMU command-line options, network configuration, and system readiness verification.

### Public instruction, condensed

Start the /app/alpine.iso image in qemu in such a way that I can connect to it via `telnet 127.0.0.1 6665`. When I run telnet I will expect to see the login prompt; I'll log in. You should just get me to this point. Start the image in the background and leave it running. Block until it's ready.

The complete public instruction remains available in the linked source row. The text above is included only to make this dossier usable during review.

## How the original row is evaluated

Terminal-Bench starts the task environment, allows the agent to work in it, and then invokes the row's verifier entrypoint. The verifier scripts below examine files, processes, services, or other state produced in that environment. Any Python assertion messages and test-function summaries listed here come directly from those verifier files.

### Verifier files

- `tests/test.sh`
- `tests/test_outputs.py`

### Test entrypoint and important commands

- `tests/test.sh`: `apt-get install -y curl expect`
- `tests/test.sh`: `curl -LsSf https://astral.sh/uv/0.9.5/install.sh | sh`
- `tests/test.sh`: `-w pytest==8.4.1 \`
- `tests/test.sh`: `-w pytest-json-ctrf==0.3.5 \`
- `tests/test.sh`: `pytest --ctrf /logs/verifier/ctrf.json /tests/test_outputs.py -rA`

### Candidate artifacts, services, or paths referenced by tests

- `/tmp/data.txt`

## What the tests check

### Test functions

- `test_version` — Test that Alpine Linux is running in QEMU and accessible via telnet. This test verifies that: 1. QEMU successfully started Alpine Linux in the virtual machine 2. Alpine Linux is configured to accept telnet connections on port 6665 3. Root…

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

Exclude the row for now. The original score depends on a live QEMU guest, guest RAM/process state, disk changes, and a telnet serial endpoint left running in the Agent VM. A file-only candidate cannot reproduce that state in a fresh Evaluation VM, and disk-identical candidates with different live guests can receive different original scores. Faithful conversion would require a bounded, version-pinned disk-plus-memory checkpoint and restoration protocol; black-box telnet observations alone cannot establish QEMU/Alpine provenance and the fixed kernel response can be emulated. Hidden tests, expected strings, and scoring could remain host-side, but the conversion cost is disproportionate to the scored behavior. Verdict: exclude; manually approved in the final clean-conversion audit.
