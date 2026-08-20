# `qemu-alpine-ssh`

> Portfolio status: See [inventory.csv](../inventory.csv) for the authoritative review decision.

## Source facts

| Field | Value |
|---|---|
| Benchmark | Terminal-Bench 2.0 |
| Source row | [`qemu-alpine-ssh`](https://github.com/harbor-framework/terminal-bench-2/tree/2fd12b88aafdd04a52c298e3940bcb189f9766d6/qemu-alpine-ssh) |
| Source snapshot | `2fd12b88aafdd04a52c298e3940bcb189f9766d6` |
| Difficulty | medium |
| Category | system-administration |
| Tags | sys-admin |
| Agent timeout | 900.0 seconds |
| Verifier timeout | 900.0 seconds |
| Candidate image | `alexgshaw/qemu-alpine-ssh:20251031` |
| Internet allowed | `True` |

## Goal in simple terms

Evaluates the ability to start an Alpine Linux VM in QEMU and configure SSH server access with proper networking and authentication.

### Public instruction, condensed

Start the /app/alpine.iso image in qemu, and then start an ssh server on the alpine linux vm. When you're done, I should be able to run `ssh -p 2222 root@localhost` with password `password123` and be dropped into a shell. On the /app/alpine.iso image, the default username is root with no password.

The complete public instruction remains available in the linked source row. The text above is included only to make this dossier usable during review.

## How the original row is evaluated

Terminal-Bench starts the task environment, allows the agent to work in it, and then invokes the row's verifier entrypoint. The verifier scripts below examine files, processes, services, or other state produced in that environment. Any Python assertion messages and test-function summaries listed here come directly from those verifier files.

### Verifier files

- `tests/test.sh`
- `tests/test_outputs.py`

### Test entrypoint and important commands

- `tests/test.sh`: `apt-get install -y curl sshpass`
- `tests/test.sh`: `curl -LsSf https://astral.sh/uv/0.9.5/install.sh | sh`
- `tests/test.sh`: `-w pytest==8.4.1 \`
- `tests/test.sh`: `-w pytest-json-ctrf==0.3.5 \`
- `tests/test.sh`: `pytest --ctrf /logs/verifier/ctrf.json /tests/test_outputs.py -rA`

### Candidate artifacts, services, or paths referenced by tests

- No absolute candidate paths were extractable automatically.

## What the tests check

### Test functions

- `test_sshpass` — Test that Alpine Linux is running in QEMU with SSH access enabled. This test verifies that: 1. A QEMU virtual machine is successfully running Alpine Linux 2. SSH server is properly configured and accessible on port 2222 3. Root login via…

### Explicit acceptance or failure messages

- Output of ssh is wrong version

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

Exclude the row for now. The original score depends on a live QEMU guest, guest RAM/process state, disk changes, port forwarding, and SSH service state created in the Agent VM. A file-only candidate cannot reproduce that state in a fresh Evaluation VM; disk-identical candidates with different live guests can receive different original scores. Faithful handoff would require a bounded, version-pinned QEMU disk-plus-memory checkpoint and restoration protocol, while black-box SSH alone cannot establish QEMU/Alpine provenance and the fixed response is easily emulated. Hidden tests, expected strings, and scoring could remain host-side, but the implementation burden is disproportionate to the scored behavior. Verdict: exclude; manually approved in the final clean-conversion audit.
