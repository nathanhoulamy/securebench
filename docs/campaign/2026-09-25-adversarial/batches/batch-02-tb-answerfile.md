# Batch 2 — remaining 13 Terminal-Bench answer-file rows (analytical)

Rows: bn-fit-modify, chess-best-move, code-from-image, constraints-scheduling,
count-dataset-tokens, extract-moves-from-video, feal-linear-cryptanalysis,
mteb-leaderboard, mteb-retrieve, protein-assembly, raman-fitting,
rstan-to-pystan, write-compressor.

Method: static-candidate analysis of the upstream `test_outputs.py` vs the
SecureBench Oracle (`benchmarks/terminal-bench/v2/hidden/<row>/oracle/oracle.py`)
and the candidate spec. No candidate obtains a pass on one architecture and not
the other by exploiting the split-verification boundary, so none was Docker-graded
as an attack. Findings:

## No architectural divergence

- **9/13 — answer baked into both graders (shared weakness).** The expected
  answer (or the discriminating value) is a literal constant in *both* the
  upstream test and the Oracle, because the Oracle is a host-side reimplementation
  of the same upstream test. A static file of the known answer passes both, but
  this is not native-vs-SecureBench: both are equally affected, and it reflects a
  benchmark-design choice (answer embedded in the grader), not the verification
  architecture. Rows: bn-fit-modify, chess-best-move, code-from-image,
  count-dataset-tokens, extract-moves-from-video, feal-linear-cryptanalysis,
  mteb-leaderboard, mteb-retrieve, protein-assembly, raman-fitting. (10 rows,
  including rstan-to-pystan below.)
  - Examples: chess-best-move `move.txt` = `e2e4 g2g4`; count-dataset-tokens
    substring `79586`; feal & extract-moves embed the full expected transcript in
    the test file; raman-fitting's 8 fit constants; protein-assembly's 5 target
    protein sequences.
  - Note: SecureBench does keep the answer *host-side* (the Oracle is never in the
    environment), so an agent cannot read it at runtime from the Oracle — but the
    same value also lives in the public upstream test, so secrecy is not improved
    for these rows.

- **constraints-scheduling — no divergence (genuine).** No literal answer; both
  recompute the required slot from the input calendars (native from `/app` copies
  guarded by a SHA256 integrity check, the Oracle from trusted host mounts). A
  candidate must contain the genuinely-correct slot; neither is foolable.

## Fidelity divergences (not attacks)

- **rstan-to-pystan — Oracle strictly weaker.** Answer ranges are baked into both
  (so it is also a "constant" row). Additionally, native runs a
  `test_r_rstan_not_installed` environment check that the Oracle deliberately
  drops (documented as an approved semantic change). A solution that reached the
  numbers by installing R/RStan would pass SecureBench and fail native. This is a
  case where **SecureBench is more lenient than native**, reported honestly.
- **write-compressor — engine divergence (genuine task).** Native compiles and
  runs the real `decomp.c` C decoder; the Oracle runs a Python re-implementation
  with extra safety bounds (MAX_UNARY_BITS, buffer checks) absent from the C
  code. A genuinely-correct `data.comp` passes both, but adversarial/edge-case
  streams could be accepted by the C decoder and rejected by the Oracle (or vice
  versa). No non-solving static pass on either side.
- **distribution-search** (batch 1) is the same shape: Oracle npy parser rejects
  trailing bytes / non-float dtype that native's `np.load` tolerates.

## Tally

Native attacks: 0. SecureBench attacks: 0. Shared-weakness (both pass a known
constant): 10 rows. Genuine/only-fidelity-divergence: 3 rows (constraints,
write-compressor; rstan also has the weaker-Oracle note).
