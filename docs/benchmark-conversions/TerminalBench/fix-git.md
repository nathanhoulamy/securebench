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
| Candidate image | `alexgshaw/fix-git@sha256:61e431c00c58df652287aadce5457634d9f9330cfdd153ebdf2802df0d540119` |
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

- [x] Read the complete public instruction.
- [x] Walk through the verifier entrypoint line by line.
- [x] Identify every candidate-controlled input consumed by the verifier.
- [x] Identify every scoring-relevant assertion and expected value.
- [x] Decide whether the task's intended behavior is fully represented by its tests.
- [x] Design the split-verification conversion.
- [x] Record fidelity limitations and the final eligibility decision.

## Implemented v2 conversion

The conversion uses passive artifact verification. It preserves the source
repository, detached commit, reflog, branch, starting directory, prompt, and
network policy, but prevents the Agent from reading the source image's separate
gold-copy directory.

### Agent environment and Candidate boundary

The Linux/amd64 image is pinned to
`alexgshaw/fix-git@sha256:61e431c00c58df652287aadce5457634d9f9330cfdd153ebdf2802df0d540119`.
A reviewed read-only public directory masks `/app/resources`; it contains only
an inert `.keep` file, so `/app/resources/patch_files` is absent during Agent
execution. The intended lost commit remains recoverable at
`650dba427e0a9dcd118f41a4c5e35c8017550a5a` through the repository's reflog.

The stopped Candidate is one bounded `file_bundle` containing exactly:

- `/app/personal-site/_includes/about.md`; and
- `/app/personal-site/_layouts/default.html`.

Each regular file is capped at 16 KiB; the combined Candidate is capped at two
files and 32 KiB. Git metadata, reflogs, branches, task inputs, the masked gold
directory, packages, logs, processes, connections, and credentials do not cross
the Agent boundary.

### Passive evidence and host Oracle

Both Candidate entries are parsed with `securebench.utf8-text/v1`. The
host-only Oracle reproduces the source verifier's binary `read().strip()`
semantics by UTF-8 encoding each observation, stripping only the byte values
that Python `bytes.strip()` removes at both edges, and comparing a hidden
SHA-256 identity. This intentionally accepts source-accepted leading/trailing
ASCII spaces, tabs, CR/LF, vertical tabs, and form feeds, while rejecting
Unicode whitespace that the binary source verifier does not strip.

The reviewed stripped identities are
`b672b690b9fd43c901ed5a385ebbca7cf3546716f1fead228136b1c326f1de6b`
for `about.md` and
`fb3fad17b83338002f5fd6a99ea1ec3a662cea570f9fff9240b8abc1861be655`
for `default.html`. The source verifier uses MD5 only as an equality mechanism;
using hidden SHA-256 identities preserves its accepted byte set except for
theoretical MD5 collision Candidates, which are intentionally rejected as
security hardening with no expected intelligence impact. No Candidate code is
imported or executed.

### Generic Linux compatibility additions

This row exposed two framework-level compatibility gaps:

- a nested workdir such as `/app/personal-site` can now receive an explicit
  read-only public mount at a sibling path under the same `/app` root; writable
  sibling mounts remain rejected; and
- every Agent harness adds exact `safe.directory` entries for its configured
  workdir and declared directory-tree Candidate roots through bounded
  process-local Git configuration. Existing entries are preserved, ambiguous
  or excessive configurations fail closed, and the unsafe wildcard
  `safe.directory=*` is never used.

These additions remove Docker bind-mount ownership noise and let Git behave as
it does in the source image without exposing or trusting additional state.

### Semantic fidelity and limitations

The original verifier compares only the stripped bytes of the two target files.
It does not inspect branch ancestry, merge commits, the reflog, repository
cleanliness, or the recovery method. The v2 Candidate and Oracle preserve
exactly that scored surface. A Candidate may therefore reconstruct the correct
files without producing a merge commit, just as it can in the source row.

The v2 UTF-8 parser rejects invalid UTF-8 before the Oracle, while the source's
binary comparison would simply reject those bytes as unequal. This changes the
internal failure category, not acceptance. Masking the source image's gold
copies removes an unintended answer leak; the legitimate Git recovery evidence
and original starting directory remain unchanged.

### Qualification evidence

- Qualification working tree: branch `split-verification-v2`, based on
  `fa23d3969b9cc61aefac8a2ff3a4a2c969e94d71` plus the pending financial and
  `fix-code-vulnerability` refinements and this conversion.
- Host: 2026-09-01, Linux `7.0.0-29-generic` x86_64, Docker 29.7.2,
  Linux/amd64 image.
- Focused warning-strict deterministic qualification passes
  `36 passed, 5 skipped, 121 deselected`; the skips are Docker-gated.
- The consolidated exact-image Linux matrix passes
  `41 passed, 121 deselected`.
- The untouched master files fail. The reviewed reflog recovery, merge attempt,
  conflict resolution from the lost commit, stopped capture, and exact replay
  pass. The original source verifier's two assertions pass against that same
  reconstructed reference.
- Partial about-only and layout-only recoveries, changed content, forged text
  and structured verdicts, Unicode-edge-whitespace tricks, invalid UTF-8,
  duplicate/uncorrelated evidence, and missing, symlink, directory, and
  oversized Candidate forms fail or cannot affect scoring.
- The complete warning-strict repository suite passes
  `977 passed, 104 skipped`. Terminal and self audits pass `85/85`; unchanged
  DeepSWE passes `13/13`; the isolated row audit passes `5/5`, all without
  warnings.
- The API-key-backed `gpt-5.6-luna` smoke uses `reasoning_effort: none`, captures
  both bounded files, completes verification without infrastructure error, and
  is correctly rejected because it leaves both files unchanged. Candidate
  digest:
  `sha256:b5f2a8faf4305db55a89ccb0cf515152940faeb03803971746c761bed0ea61fd`;
  row digest:
  `sha256:fc5f40de7b8f75f77c7c0cb8e95311c27f5517a0c0c3ca183052daa16a47e2fb`;
  verification digest:
  `sha256:04713fdb4c73bec9e1652ff69484a5bdaee18fc98689795893c643dcb54a48c4`;
  execution digest:
  `sha256:074fb4d6fdae8b6b252c823498a4332343de4fb6e524f521ee73fbdbe9ffd7d2`.
- Harness teardown prunes the task image and leaves no row container, network,
  volume, Agent, or task-specific process.

### Final qualification decision

**Approved — Clean conversion / no intelligence impact.** The two-file stopped
Candidate, masked answer leak, exact source-byte semantics, and host-owned
Oracle preserve the original scored behavior without trusting Candidate Git
claims or guest verdicts.
