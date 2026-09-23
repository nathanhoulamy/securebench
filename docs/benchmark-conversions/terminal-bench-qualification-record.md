# TerminalBench qualification record — Wave A

This is the current admission record for the 28 implemented TerminalBench v2 rows.
It supersedes the historical Linux qualifications that were marked
`requalification_pending` after the strict-split and Agent-network policy changes.

Run date: 2026-09-22 · branch `split-verification-v2`

## Host and tooling

| Item | Value |
|---|---|
| Platform | `Linux-7.0.0-29-generic-x86_64-with-glibc2.43` |
| Machine | `x86_64` |
| Python | 3.14.4 |
| Docker | 29.7.2 (storage driver `overlayfs`) |
| Driver | [`tools/qualify_rows.py`](../../tools/qualify_rows.py) |
| Machine-readable record | `runs/qualification/terminal-bench-qualification.json` |

Every row ran with `SECUREBENCH_DOCKER_INTEGRATION=1` against its digest-pinned
image. The driver runs each row's focused test file plus that row's cases from
`tests/test_terminal_file_bundle_qualification.py`, and reports a skipped case as
an **evidence gap**, never as a pass.

## Result

| Status | Rows |
|---|---:|
| Gates executed and passed | 26 |
| Evidence gap | 1 |
| No focused test | 1 |
| **Total** | **28** |

684 gate cases passed, 1 skipped, 0 failed, in 599 s of wall-clock Docker time.

Repository suite under `-W error`: **1435 passed, 160 skipped** (previously
1369 / 152; the increase is the new `sqlite-db-truncate` and `vulnerable-secret`
coverage plus three new shared capture contracts).

## Gate 8 — leak check

Inspected after the full sweep:

| Resource | Count |
|---|---:|
| Containers (incl. stopped) | 0 |
| Non-default Docker networks | 0 |
| Docker volumes | 0 |
| Root-owned host paths under the test tree | 0 |

One real leak was found and fixed during this wave. `hf-model-inference`
prepared its reference workspace with a root-writing bind-mounted container and
never tore it down, leaving 63 root-owned host paths across repeated runs that
ordinary teardown could not remove. The test now disposes of that workspace with
`remove_untrusted_tree` and asserts it is gone. This was a gate 8 failure, not a
test nuisance.

## Per-row results

| Row | Status | Gate cases | Seconds |
|---|---|---:|---:|
| bn-fit-modify | complete | 14 | 2.4 |
| cancel-async-tasks | complete | 14 | 128.7 |
| chess-best-move | complete | 16 | 2.9 |
| circuit-fibsqrt | **evidence gap** | 23 (1 skipped) | 73.0 |
| cobol-modernization | complete | 19 | 17.4 |
| code-from-image | complete | 20 | 4.9 |
| constraints-scheduling | complete | 7 | 5.6 |
| count-dataset-tokens | complete | 22 | 10.0 |
| crack-7z-hash | complete | 23 | 7.5 |
| db-wal-recovery | complete | 31 | 5.8 |
| distribution-search | complete | 30 | 10.7 |
| dna-assembly | complete | 35 | 10.7 |
| dna-insert | complete | 33 | 10.6 |
| extract-elf | complete | 21 | 15.3 |
| extract-moves-from-video | complete | 37 | 25.5 |
| feal-linear-cryptanalysis | complete | 26 | 7.7 |
| financial-document-processor | complete | 43 | 8.6 |
| fix-code-vulnerability | complete | 40 | 65.4 |
| fix-git | complete | 27 | 6.2 |
| gcode-to-text | complete | 25 | 5.9 |
| git-leak-recovery | complete | 19 | 5.4 |
| gpt2-codegolf | complete | 18 | 21.6 |
| headless-terminal | complete | 21 | 61.9 |
| hf-model-inference | complete | 25 | 37.5 |
| install-windows-3.11 | **no focused test** | 0 | 0.0 |
| kv-store-grpc | complete | 26 | 29.5 |
| sqlite-db-truncate | complete | 37 | 13.2 |
| vulnerable-secret | complete | 32 | 4.9 |

## Work completed in this wave

1. **`cobol-modernization` gate 2 closed.** Its reference solution previously
   lived at `/tmp/securebench-cobol-reference/program.py`, an ephemeral path that
   no longer existed, so `test_official_reference_passes_real_pinned_evaluations`
   silently skipped and reference success was unproven. A faithful Python port of
   the pinned `src/program.cbl` is now checked in as host-only qualification
   material at `benchmarks/terminal-bench/v2/hidden/cobol-modernization/qualification/reference.py`
   and was validated against the Oracle's independently computed expectations for
   the source case and all three seeded cases before being wired in. The test now
   asserts the file exists rather than skipping, so the gap cannot hide again.

2. **`sqlite-db-truncate` and `vulnerable-secret` gained focused tests.** Both
   were implemented with no `tests/test_<row>_v2.py`, so their row-specific
   mutants, malicious candidates, and Oracle decisions were unproven. Each now
   covers preflight and visibility, source-constant stability, reference success,
   preserved source quirks, targeted semantic mutants, malformed and forged
   artifacts, malicious filesystem shapes, missing-deliverable scoring, exact
   replay, and pinned-image Docker capture.

3. **Three shared capture contracts added** for `sqlite-db-truncate`,
   `vulnerable-secret`, and `constraints-scheduling`, which were the only
   `file_bundle` rows absent from `tests/test_terminal_file_bundle_qualification.py`.

4. **`extract-elf` gate closed without weakening it.** Its source-reference
   conformance test skipped because the host has no Node.js. It now falls back to
   a digest-pinned `node` image, so conformance against the pinned source
   reference is actually proven. The comparison itself is unchanged.

5. **Gate 8 leak in `hf-model-inference` fixed** (see above).

6. **A qualification driver** (`tools/qualify_rows.py`) now runs the matrix per
   row and emits a machine-readable record. Admission tooling remains deferred:
   this driver records evidence, it does not decide admission.

## Wave B — new conversions (2026-09-22 / 2026-09-23)

Eight design-only rows were converted and qualified, taking the pack from 28 to
36 executable rows and TerminalBench from 23 to **31 Approved**.

`password-recovery` was later moved from Approved to `reproducibility_pending`,
leaving **30 Approved**. Its gates all pass, but its image cannot be rebuilt
reproducibly (see the image-pinning caveat below), so its admission waits on a
published image or a deterministic build.

| Row | Check | Parser | Agent network | Gate cases |
|---|---|---|---|---:|
| `password-recovery` | artifact | `securebench.utf8-text/v1` | `none` | 32 |
| `log-summary-date-ranges` | artifact | `securebench.strict-csv/v1` | `none` | 30 |
| `raman-fitting` | artifact | `securebench.strict-json/v1` | `restricted` (pypi) | 40 |
| `protein-assembly` | artifact | `securebench.utf8-text/v1` | `restricted` (rcsb, fpbase, pypi) | 37 |
| `write-compressor` | artifact | `securebench.opaque-bytes/v1` | `none` | 30 |
| `mteb-leaderboard` | artifact | `securebench.utf8-text/v1` | `restricted` (hf, pypi) | 31 |
| `mteb-retrieve` | artifact | `securebench.utf8-text/v1` | `restricted` (hf, pypi) | 31 |
| `rstan-to-pystan` | artifact | `securebench.utf8-text/v1` | `restricted` (pypi) | 45 |

Two rows needed a real reference solution built from scratch, because none
existed in the repo:

- **`protein-assembly`** — the Oracle translates the candidate's gBlock itself
  with the standard genetic code rather than trusting any candidate claim. The
  reference was produced by reverse-translating the fusion protein under the
  50-nucleotide GC-window constraint
  (`v2/hidden/protein-assembly/qualification/build_reference.py`) and then
  **validated against the real source verifier running real Biopython** in a
  container, which passed. A test pins the source's asymmetric tolerance for
  linker length and the GC band, and records that a 20-residue poly-glycine
  linker is genuinely rejected because glycine codons are all at least 2/3 GC —
  an interaction between two source constraints, not a converter artifact.

- **`write-compressor`** — the Oracle reimplements the public `decomp.c` range
  decoder in memory-safe Python; every out-of-bounds access the C program would
  perform becomes an explicit rejection. The reference was generated by
  compiling the upstream `main.rs` with `rustc -O` inside the pinned image
  (2264 bytes, under the 2500-byte rule), confirming the gcc-built C decoder
  reproduces `data.txt` from it, and then confirming the Python decoder produces
  **byte-identical output**. A separate check found that dropping the final byte
  still decodes in *both* implementations — the decoder stops after the encoded
  token count and reads 255 past EOF — so that is recorded as fidelity rather
  than removed as a failing mutant.

Each carries a focused test file, a `RowCaptureContract` entry in the shared
file-bundle qualification suite, and a host-only Oracle that reproduces the
source verifier's predicate exactly:

- **password-recovery** — membership of the secret after `strip()` + `split("\n")`,
  so a correct guess among incorrect ones passes and an inner-line-padded guess
  does not. The secret is never in either environment.
- **log-summary-date-ranges** — exact header, exactly fifteen rows, positional
  comparison, counts compared as strings. A mutant reproducing the naive
  substring severity counter (the log corpus deliberately contains a WARNING
  whose message text includes the word "ERROR") is rejected.
- **raman-fitting** — eight parameters with the source's *asymmetric* tolerance
  kinds preserved: `G.x0` is absolute (±5) while `2D.x0` is relative (±5%).
  A test asserts that asymmetry against both the Oracle and the source verifier,
  because collapsing it to one kind is the obvious fidelity error here.

### New registered parser: `securebench.opaque-bytes/v1`

`write-compressor`'s deliverable is binary and no registered parser accepted
arbitrary bytes. A bounded opaque-bytes profile was added: it decodes and
interprets nothing, returning `{byte_count, sha256, bytes_base64}` under a 4 MiB
cap, so the Oracle owns the format and does its own memory-safe decoding. It is
the narrowest profile in the registry. Because it expands the shared registry,
it is flagged for review in
[`conversion-blockers.md`](conversion-blockers.md).

### Framework defect found and fixed

While qualifying `raman-fitting`, a candidate-triggerable **infrastructure
error** was found in the strict-JSON path. `strict_json_loads` rejected the bare
`Infinity`/`NaN` tokens but accepted a syntactically valid overflow literal such
as `1e400`, which Python parses to `inf`. Canonical encoding then raised, and the
framework reported `infrastructure_error` instead of rejected candidate evidence.

Any candidate on any `securebench.strict-json/v1` row could trigger this, which
breaks gate 6 (failure ownership): candidate-controlled bytes must fail closed as
candidate evidence. Fixed at the parse boundary in
`securebench/data_formats.py` with a `parse_float` hook that rejects non-finite
results; `1e308` still parses. This hardened every already-Approved strict-JSON
row, not just the new one.

### Image pinning caveat

The three Wave B tasks have no published registry image — `alexgshaw/<task>`
does not exist for them — so they are built from the checked-in Dockerfile and
pinned by bare image ID (`sha256:...`) rather than repository digest
(`name@sha256:...`). Both forms are immutable and schema-valid, but a bare image
ID is **host-local**: another machine cannot pull it.

`password-recovery` is worse than the others: its `setup.sh` seeds directory
names, filenames, and the 4 MiB disk image from `/dev/urandom`, so **every
rebuild produces a different image ID**. Its pin is valid for this host only and
is not reproducible elsewhere. Publishing these images, or making the builds
deterministic, is required before the conversions are portable. This is recorded
rather than worked around.

### `rstan-to-pystan` carries a documented semantic change

Five of its six source tests are numeric range checks over four CSV files and
are reproduced exactly, including the source's two different parsing styles
(raw `split(",")[0]` for the scalars, `csv.reader` column 0 for the vectors).

The sixth shells out to `R` and `R --slave -e "library(rstan)"` inside the
candidate's own filesystem to prove the agent never installed R. That is a
property of the environment, not of any captured artifact, so it is **dropped**,
as the dossier approves. Using an Evaluation image without R was rejected: it
would make absence a property of the harness rather than evidence about the
candidate. A candidate that reached these numbers by installing R would pass
here and fail the original. The row is recorded as `semantic_change`, and a test
asserts the drop is documented in the Oracle.

## Outstanding

### `circuit-fibsqrt` — evidence gap (parked)

Gate 2 is unproven: no reference netlist exists, and producing one means
synthesising gates for `fib(isqrt(n)) mod 2^32`. The row also has a domain
mismatch against its public prompt. Both are recorded in the
[fidelity review queue](fidelity-review-queue.md#circuit-fibsqrt--domain-mismatch--missing-reference).
Its other 23 gate cases pass.

Note: `benchmarks/terminal-bench/docker/circuit-fibsqrt/gates.txt` was checked
and is the identity starter stub shipped to the agent (`out_i = out_i`), not a
reference solution. It is correctly public and is not a leak.

### `install-windows-3.11` — no focused test

The row is implemented and carries a shared capture contract, but has no
`tests/test_install_windows_3_11_v2.py`. Its semantic mutants, malicious
candidates, and Oracle decisions are unproven. It cannot be admitted until that
test exists.

### Transient failure seen and explained

An earlier sweep reported `git-leak-recovery` failing one case. That sweep ran
concurrently with a separate full Docker suite competing for the daemon. The row
passes consistently in isolation and in the final clean sweep. Recorded here so
the discarded result is not mistaken for a defect.

## Admission

Gates 1–6 executed and passed for 26 rows and gate 8 is clean. Gate 7 (semantic
fidelity) rests on each row's dossier record and, for the paper subset, on the
[passive](paper-terminal-passive-review.md) and
[protocol](paper-terminal-protocol-review.md) reviews.

Four rows have an open fidelity question and stay pending by decision, not by
defect: `circuit-fibsqrt`, `cobol-modernization`, `extract-elf`, and
`fix-code-vulnerability` (see the [fidelity review queue](fidelity-review-queue.md)).

| Disposition | Rows |
|---|---:|
| **Approved** | 23 |
| Pending — fidelity decision deferred | 3 |
| Pending — evidence gap + fidelity | 1 (`circuit-fibsqrt`) |
| Pending — no focused test | 1 (`install-windows-3.11`) |

This record covers the 28 implemented rows only. The other 45 approved
TerminalBench designs remain `design_only`.
