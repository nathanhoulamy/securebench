# `sqlite-with-gcov`

> Portfolio status: See [inventory.csv](../inventory.csv) for the authoritative review decision.

## Source facts

| Field | Value |
|---|---|
| Benchmark | Terminal-Bench 2.0 |
| Source row | [`sqlite-with-gcov`](https://github.com/harbor-framework/terminal-bench-2/tree/2fd12b88aafdd04a52c298e3940bcb189f9766d6/sqlite-with-gcov) |
| Source snapshot | `2fd12b88aafdd04a52c298e3940bcb189f9766d6` |
| Difficulty | medium |
| Category | system-administration |
| Tags | software-installation, system |
| Agent timeout | 900.0 seconds |
| Verifier timeout | 900.0 seconds |
| Candidate image | `alexgshaw/sqlite-with-gcov:20251031` |
| Internet allowed | `True` |

## Goal in simple terms

Evaluates the ability to compile SQLite from source with gcov instrumentation and make it available in the system PATH.

### Public instruction, condensed

Compile SQLite in /app/sqlite with gcov instrumentation and make it available in the PATH. The SQLite source snapshot is pre-vendored at /app/vendor/sqlite-fossil-release.tar.gz; use it instead of fetching sources over the network.

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

- `/app/sqlite`

## What the tests check

### Test functions

- `test_sqlite_compiled` — Test that sqlite was compiled successfully.
- `test_sqlite_in_path` — Test that sqlite is available in the PATH.
- `test_gcov_enabled` — Test that gcov instrumentation is enabled in the SQLite binary.

### Explicit acceptance or failure messages

- SQLite version output is empty
- sqlite3 not found in PATH
- Failed to run SQLite
- No .gcda files found, gcov instrumentation may not be enabled
- No .gcno files found, gcov instrumentation may not be enabled

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

Use black-box challenge/response supplemented by passive artifact verification;
no instrumentation-observer pattern is required. Place the candidate SQLite
build tree in the Evaluation VM, invoke only its `sqlite3` binary against
bounded SQL challenges, and return externally captured version/query output,
status, and bounded filesystem artifacts. The host Oracle independently checks
the responses and the presence of `.gcda` and `.gcno` files. This preserves the
original check, which does not establish the files' provenance or prove that
the exercised binary was genuinely gcov-instrumented; strengthening that claim
would require redesign rather than trusting guest metadata. Hidden tests,
expected outputs, scoring, and reference binaries stay out of both VMs, and
the Oracle ignores every in-VM success claim. Verdict: clean conversion;
auto-approved under the first-pass policy.
