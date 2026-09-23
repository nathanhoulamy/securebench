# Paper conversion subset

This is the implementation and qualification queue selected on 2026-09-22,
not an admitted benchmark release. The target is ten TerminalBench and ten
DeepSWE conversions. No entry gains admission from selection, a design label,
or synthetic Oracle tests. Final admission remains **Approved** or **Excluded**;
unfinished work stays qualification-pending.

## Selection

TerminalBench uses five artifact and five protocol rows. The detailed
[passive review](paper-terminal-passive-review.md) and
[protocol review](paper-terminal-protocol-review.md) map original scoring
criteria to current evidence and disclose fidelity limits.

| Artifact | Protocol |
|---|---|
| bn-fit-modify | cancel-async-tasks |
| db-wal-recovery | circuit-fibsqrt |
| dna-insert | cobol-modernization |
| financial-document-processor | extract-elf |
| git-leak-recovery | fix-code-vulnerability |

The protocol choices are conditional: `circuit-fibsqrt` has a known mismatch
between the public all-uint32 domain and the source reference's supported
domain. It must not be called pristine against the full public requirement.
Resolve that mismatch or replace it before freezing the release;
`gpt2-codegolf` is the first proposed reserve. The other documented source
coverage limits must also be explicitly assessed, not silently treated as
complete public-contract coverage.

The ranked [DeepSWE selection](paper-deepswe-selection.md) is:

1. go-critic-doc-link-checker
2. termenv-preserve-ansi-resets
3. task-task-graph-export
4. helm-unified-manifest-stream
5. prometheus-typed-label-sorting
6. oxvg-structural-selector-preservation
7. happy-dom-deterministic-intersectionobserver
8. go-git-worktree-merge-conflicts
9. opa-template-string-reconstruction
10. yaegi-go-embed-directives

All ten require protocol evaluation. Parsing an artifact produced by executing
the patched repository does not make the check a passive artifact check. The
three earlier implemented DeepSWE rows are not automatically selected: their
semantic coverage gaps make their total repair cost uncertain. Source test
counts are screening information, not a conversion coverage metric.

## Work order and budget control

First take go-critic through actual stopped-patch capture and fresh-image
base/reference/mutant/malicious evaluation. Use that result to measure cost
before implementing the other nine. Keep expected diagnostics and reference
qualification materials host-only. No paid Agent run is needed for this
deterministic qualification stage.

For each row, record the exact original requirement/assertion, its public
support, the candidate-visible challenge, the independently checked evidence,
the rejection mutant, and any fidelity concession. A material unobservable
requirement or new shared runtime dependency triggers replacement review.
Do not satisfy the target count by weakening the Oracle.

Current TerminalBench evidence includes 119 passed / 21 skipped in the focused
passive tests, and a live Docker circuit/COBOL run with 31 passed / 2 skipped.
The latter two skips are missing reference fixtures, so reference success
remains unproven for that run. See the linked reviews for exact commands and
scope. Skips and infrastructure failures never count as successful rejection.

The eventual report must bind the source commit, row/component/image digests,
effective resource policy, host/runtime identity, commands, results, retained
evidence, fidelity decision, and final admission. No rows in this queue are
currently admitted by this document.
