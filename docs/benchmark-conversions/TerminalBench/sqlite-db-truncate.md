# `sqlite-db-truncate`

> Portfolio status: See [inventory.csv](../inventory.csv) for the authoritative review decision.

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

## Implemented v2 conversion

- Row: `terminal-bench/sqlite-db-truncate` in `benchmarks/terminal-bench/tasks-v2.jsonl`.
- Candidate: one bounded regular file, `/app/recover.json` (64 KiB maximum).
- Check: passive `securebench.strict-json/v1` artifact parsing; the host-only Oracle owns the eight recovered pairs and the original `> 6` acceptance threshold.
- Image: `alexgshaw/sqlite-db-truncate@sha256:aabac93c93bd1f310e6a6fb893911d7735026ed18491c72133c9196a09092ca4`.
- Source semantics retained: duplicate pairs cannot inflate recovery, unrelated pairs and additional object fields do not affect scoring, and integer/float-equivalent values compare equally.
- Deterministic qualification on 2026-08-24 covers seven-row success, six-row failure, duplicate rejection, candidate verdict-claim irrelevance, strict parsing, schema compilation, and executable preflight.
- Linux image qualification remains to be recorded: missing/base failure, reference success, malformed/oversized/symlink capture rejection, end-to-end Agent run, and cleanup/leak inspection.

Admission status at the time this section was written: qualification pending. **Superseded by the
"Review correction" section below**, which records the Oracle fix required before the Linux matrix
could be trusted, the completed real-Docker qualification, and the final admission status.

## Review correction

`docs/benchmark-conversions/workaround-audit.md` found two divergences from upstream in the
implementation above, and this section records the fix and its re-qualification under real Docker.

### What upstream actually does

The pinned source verifier (`benchmarks/terminal-bench/hidden/sqlite-db-truncate/tests/test_outputs.py:24-31`)
does not type-check rows at all:

```python
soln_tuples = {(item["word"], item["value"]) for item in soln}
data_tuples = {(item["word"], item["value"]) for item in data}
matches = soln_tuples & data_tuples
assert len(matches) > 6, "Did not load data correctly"
```

A row whose `word`/`value` type does not match the expected pair (e.g. a stringified or boolean
`value`) simply fails to equal anything in `soln_tuples`; it is silently absent from the
intersection, not a disqualifying error. Only a row that would make Python's own comprehension
raise — a missing `word`/`value` key (`KeyError`), or an unhashable `value` such as a list/object
that cannot go into the set literal (`TypeError`) — causes the whole upstream test to error out
(equivalent to a full failure). Upstream's agent/verifier timeout is 900 seconds (dossier "Source
facts" table above), not 1200.

### What changed

1. **Oracle scoring
   (`benchmarks/terminal-bench/v2/hidden/sqlite-db-truncate/oracle/oracle.py`).** The Oracle
   previously rejected the *entire* candidate (`invalid_row_type`) the moment any row's `word` was
   not a `str` or `value` was not an `int`/`float`, and separately rejected on non-finite `value`
   (`non_finite_value`, already dead code — `securebench.strict-json/v1` rejects non-finite JSON
   numbers at parse time, so this branch could never fire). Rewrote `RecoveryOracle.evaluate` to
   mirror upstream's set-intersection exactly: build `(word, value)` pairs from the parsed rows with
   no type coercion or type check, and only fail the whole candidate when a row cannot even form a
   comparable pair the way upstream's comprehension would crash on it (missing `word`/`value` key,
   or an unhashable `value`). Benign type mismatches are now silently absent from the intersection,
   exactly like upstream, and the acceptance threshold (`count >= MINIMUM_RECOVERED`, i.e. the
   source's `score > 6`) is unchanged.
2. **Timeout (`benchmarks/terminal-bench/tasks-v2.jsonl`).** `environment.timeout_seconds` for
   `terminal-bench/sqlite-db-truncate` restored from `1200` to upstream's `900`. No split-verification
   overhead was measured that would justify a longer budget for this row (single bounded-file
   capture, no protocol/adapter round-trips), so the extra 300 seconds had no recorded reason and is
   removed rather than justified.
3. **Tests (`tests/test_sqlite_db_truncate_v2.py`).**
   - `stringified_values` and `boolean_values` mutants now expect `insufficient_recovery` instead of
     `invalid_row_type`: with the type check removed, all eight rows mismatch by value and the
     candidate correctly still fails, but now for the upstream-faithful reason (no matches reach the
     threshold), not because the Oracle refused to score the file.
   - Added `unhashable_values` (a `list`-valued `value` on every row) to exercise the new
     "crash-equivalent" `invalid_row_shape` path.
   - Added `test_type_mismatched_row_is_skipped_like_upstream_and_still_passes`: seven correct rows
     plus one extra row with a non-numeric `value` now **passes**, matching upstream (7 matches, over
     the `score > 6` threshold), where the pre-fix Oracle would have rejected the whole candidate.

`trunc.db` being mounted read-only (also noted by the audit) matches the "Input Integrity" contract
used by sibling rows and the source task's own read-only expectation for the corrupted database; it
is not a hidden behavior change and was left as-is.

### Re-qualification under Docker

Deterministic (non-Docker) suite:

```
.venv/bin/python -m pytest -q -W error tests/test_sqlite_db_truncate_v2.py
31 passed, 3 skipped in 1.03s
```

Full repository suite (unaffected by this change):

```
.venv/bin/python -m pytest -q -W error
2079 passed, 413 skipped in 140.76s (0:02:20)
```

Real-Docker qualification against the pinned image
(`alexgshaw/sqlite-db-truncate@sha256:aabac93c93bd1f310e6a6fb893911d7735026ed18491c72133c9196a09092ca4`),
run in the foreground with `SECUREBENCH_DOCKER_INTEGRATION=1`:

```
SECUREBENCH_DOCKER_INTEGRATION=1 .venv/bin/python -m pytest -q -W error tests/test_sqlite_db_truncate_v2.py -k "sqlite"
34 passed in 5.06s
```

which includes, against real containers:

- `test_base_image_without_deliverable_is_rejected_at_capture` — the untouched base image (no
  `/app/recover.json`) fails closed at capture (Gate 1).
- `test_pinned_agent_capture_and_verification[reference]` — the reviewed 8-row reference candidate
  passes end to end (real capture, real `securebench.strict-json/v1` parse, real Oracle).
- `test_pinned_agent_capture_and_verification[below_threshold]` — a 6-row candidate fails.
- Every deterministic mutant, malformed/forged-artifact, and symlink/directory/oversized
  capture-rejection case from the file, plus the new type-mismatched-row-still-passes case.

Shared capture qualification, also under Docker:

```
SECUREBENCH_DOCKER_INTEGRATION=1 .venv/bin/python -m pytest -q -W error tests/test_terminal_file_bundle_qualification.py -k "sqlite"
5 passed, 171 deselected in 1.06s
```

No leftover `sqlite-db-truncate` containers, networks, or volumes remained after these runs
(`docker ps -a` inspected before and after).

### Final status

Admission status: **Approved**. The Oracle now scores exactly as upstream does (same skipping of
type-mismatched rows, same `> 6` / `>= 7` threshold, same tuple comparison), the timeout matches
upstream's 900 seconds, and the full qualification matrix (base failure, reference success,
targeted-mutant rejection, the upstream-parity type-mismatch-row pass, malformed/forged-artifact
rejection, and malicious filesystem-shape rejection) passes under real Docker with no isolation
leaks.
