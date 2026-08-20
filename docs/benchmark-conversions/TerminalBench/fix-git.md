# `fix-git`

> Portfolio status: See [inventory.csv](../inventory.csv) for the authoritative review decision.

## Source facts

| Field | Value |
|---|---|
| Benchmark | Terminal-Bench 2.0 |
| Source row | [`fix-git`](https://github.com/harbor-framework/terminal-bench-2/tree/2fd12b88aafdd04a52c298e3940bcb189f9766d6/fix-git) |
| Source snapshot | `2fd12b88aafdd04a52c298e3940bcb189f9766d6` |
| Difficulty | easy |
| Category | software-engineering |
| Tags | coding, version-control |
| Agent timeout | 900.0 seconds |
| Verifier timeout | 900.0 seconds |
| Candidate image | `alexgshaw/fix-git:20251031` |
| Internet allowed | `True` |

## Goal in simple terms

Evaluates the ability to recover lost Git commits from a detached HEAD state and merge them back into the master branch.

### Public instruction, condensed

I just made some changes to my personal site and checked out master, but now I can't find those changes. Please help me find them and merge them into master.

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

- `/app/personal-site/_includes/about.md`
- `/app/personal-site/_layouts/default.html`
- `/app/resources/patch_files/about.md`
- `/app/resources/patch_files/default.html`

## What the tests check

### Test functions

- `test_about_file` — Test that the about file content is correct
- `test_layout_file` — Test that the layout file content is correct

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

Clean conversion using passive artifact verification. Remove
`resources/patch_files` from the Agent VM because those files expose separate
gold copies; the unreachable commit remains legitimate challenge state inside
the supplied repository. Extract the two bounded final files, or the bounded
final repository state if useful, as the Candidate and place it read-only in
the Evaluation VM. The Oracle independently compares the target-file bytes
with host-held expected versions and trusts no candidate-reported Git status.
Reflog use, merge ancestry, and recovery method remain unobservable, but the
original verifier does not score them. **Manually approved after the
feasibility re-audit.**
