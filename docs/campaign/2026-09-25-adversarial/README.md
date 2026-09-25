# Adversarial-candidate campaign (2026-09-26)

Does SecureBench's split verification block candidate-level attacks that the
native upstream harness accepts? We hand-authored candidates that do **not**
genuinely solve each task and graded them under both verifiers.

Start with **`REPORT.md`**. Design and scope in `PLAN.md`; the red-team framing
in `PREAMBLE.md` (written for the original instructed-agent design, retained for
provenance). Per-batch findings in `batches/`; worked pilots in `pilots/`.
One record per graded candidate in `records.jsonl`.

## Result

- **SecureBench: 0 attack successes** across every authored candidate.
- **Native: 7 rows** returned a pass verdict for a non-solving candidate, via
  four mechanisms (git-object hiding, container-side reference forgery,
  single-public-case hardcoding, pytest report-forging).
- `base` fails and `reference` passes on both verifiers throughout (one
  cancel-async-tasks caveat in REPORT.md).

## Method

Faithful grading reused from the honest campaign: native = real Harbor/Pier
Docker replay (`phase1.native_grade`); SecureBench = capture + Oracle
(`verify_workspace`) or Docker command replay for protocol rows. Only newly
authored candidates (no Phase-1 reuse). Builders and the dual-grader driver:
`tools/native_baseline/adversarial/`. Raw run tree `runs/campaign-adversarial/`
is not committed; answer-plaintext fixtures are regenerated from pinned images
(`tools/native_baseline/adversarial/data/README.md`).

## Coverage of the 60 admitted rows

| group | count | treatment |
|---|---|---|
| architectural attacks demonstrated | 7 | git-leak, fix-git, gpt2-codegolf, + 4 DeepSWE pytest rows |
| native resisted the attack | 4 | cattrs, tomlkit, skrub, bandit (pytest conftest not loaded / collection error) |
| attack not applicable / inconclusive | 2 | python-statemachine (ships own conftest), cancel-async-tasks (candidate impl) |
| Go/Node DeepSWE (report-forging framework-specific) | 21 | analytical; SB blocks by architecture |
| TB answer-file (shared weakness / fidelity) | 23 | analytical (batches 1–2) |
| financial-document-processor | 1 | analytical (Oracle stricter) |
| live-service (offline n/a) | 3 | out of scope |

Honest counter-findings (SecureBench weaker or only fidelity divergence):
rstan-to-pystan (Oracle drops native's R-not-installed check), write-compressor
and distribution-search (reimplementation vs compiled/`np.load`). See REPORT.md.
