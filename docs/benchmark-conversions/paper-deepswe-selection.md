# Provisional DeepSWE conversion selection

This is a bounded implementation-order recommendation, not an admission
decision.  It covers the ten DeepSWE source rows materialized at
`/tmp/securebench-paper-deepswe-source` at snapshot
`e016041a6ccf8da29906afc9a3f5a8df940a1f78`.  Their `instruction.md`,
`tests/test.patch`, `tests/config.json`, verifier scripts, and solution
reference are locally readable.  No runtime qualification was performed for
this selection.  The counts below are the source verifier's F2P/P2P
whitelists, not evidence that a conversion is complete.

The ranking estimates total faithful conversion and qualification effort.  It
weights the independently observable semantic surface, adapter/runtime work,
Oracle work, and trust-boundary risk.  It does not rank by F2P count alone.

## Architecture classification

Every selected row executes candidate-controlled code in an Evaluation VM.
The check is therefore `protocol`, with an artifact observation where the
candidate returns JSON, text, SVG, or a manifest.  In particular, the Helm
design calls its captured manifest a passive artifact
([dossier, lines 120-125](DeepSWE/helm-unified-manifest-stream.md#L120)), but
the command runner executes the candidate to produce it.  The same applies to
the oxvg design ([dossier, lines 114-124](DeepSWE/oxvg-structural-selector-preservation.md#L114)).
Neither is a pure passive-artifact row under the architecture.

## Ranked implementation order

| Rank | Row and source evidence | Core semantic axes and runtime | Main cost or blocker |
|---:|---|---|---|
| 1 | **go-critic-doc-link-checker** — 3 F2P/16 P2P ([dossier, lines 19-20](DeepSWE/go-critic-doc-link-checker.md#L19); source `tests/config.json:3-24`) | Go linter command; local and qualified links, renamed/dot imports, builtins, embedded members, declaration locations, exact diagnostic text. | Lowest surface: ordinary bounded Go module trees and diagnostics. The Oracle still needs independent `go/parser`/`go/types` resolution and location/message normalization; the parent `TestCheckers` and unrelated checker P2P nodes must remain a regression gate. Source instruction is explicit (`tasks/go-critic-doc-link-checker/instruction.md:1-9`), and the hidden patch has positive/negative fixtures (`tests/test.patch:24-297`). The dossier's protocol plan is at lines 106-112. |
| 2 | **termenv-preserve-ansi-resets** — 35/87 ([dossier, lines 19-20](DeepSWE/termenv-preserve-ansi-resets.md#L19)) | Pure Go ANSI operations: token classes/raw bytes, CSI/OSC and hyperlinks, reset reopening, truncation/tails, Unicode widths, style/output/template wrappers, ASCII mode. | No service or filesystem state; a generic operation adapter and byte-level Oracle are straightforward. The surface is broad (instruction `tasks/termenv-preserve-ansi-resets/instruction.md:1-5`; hidden patch 690 lines), so the Oracle must independently handle malformed/partial sequences and width rules. Dossier claims full deterministic fidelity at lines 168-177. |
| 3 | **task-task-graph-export** — 20/17 ([dossier, lines 19-20](DeepSWE/task-task-graph-export.md#L19); source `tests/config.json:3-43`) | Go CLI output: JSON node metadata/locations, dep and command edges, aliases/wildcards/for expansion, reverse graph, cycles, depth groups, longest path, DOT styles, text repeats, status suppression. | No external service; bounded Taskfile trees and independent graph model make a sound protocol+artifact conversion. Oracle/parser work is moderate because all three formats and location/method fields are scored (instruction `tasks/task-task-graph-export/instruction.md:5-21`; dossier lines 151-163). |
| 4 | **helm-unified-manifest-stream** — 5/2 ([dossier, lines 19-20](DeepSWE/helm-unified-manifest-stream.md#L19); source `tests/config.json:3-13`) | Helm command runner over template, install dry-run, upgrade dry-run, and get manifest; full Source ordering, in-file order, hooks, single MANIFEST section, newline and success-line rules (instruction `tasks/helm-unified-manifest-stream/instruction.md:1-12`). | Small feature surface and direct manifest bytes, but release-state setup and four CLI modes add adapter work. The P2P whitelist includes broad `engine.TestFuncs` and the nested-path suite (`tests/config.json:10-13`); preserve them as explicit regression evidence rather than silently dropping them. |
| 5 | **prometheus-typed-label-sorting** — 17/28 ([dossier, lines 19-20](DeepSWE/prometheus-typed-label-sorting.md#L19)) | Go PromQL vector sort; precedence across numeric/duration/bytes/semver/IP/CIDR/timestamp/natural classes, arbitrary precision, signs/exponents, invalid fallbacks, ties and descending/secondary labels (instruction `tasks/prometheus-typed-label-sorting/instruction.md:24-28`). | Output is a clean ordered vector and has no service dependency, but the independent comparator must faithfully implement every typed domain and precision boundary. Dossier lines 139-151 describe the required Oracle and bounds. |
| 6 | **oxvg-structural-selector-preservation** — 6/62 ([dossier, lines 19-20](DeepSWE/oxvg-structural-selector-preservation.md#L19)) | Rust optimizer returns SVG; preserve descendant/child/adjacent-sibling selector anchors while optimizing unrelated groups, empty containers, and the existing optimizer jobs (instruction `tasks/oxvg-structural-selector-preservation/instruction.md:1-5`). | Candidate execution plus Rust/cargo/nextest runtime. Independent bounded SVG/CSS parsing and selector matching are substantial; 62 P2P nodes cover many optimizer jobs (`tests/config.json:11-70`). Use protocol with an independently parsed artifact, not passive bytes alone. |
| 7 | **happy-dom-deterministic-intersectionobserver** — 14/9 ([dossier, lines 19-20](DeepSWE/happy-dom-deterministic-intersectionobserver.md#L19)) | TypeScript DOM engine; async callback batches, observation order, thresholds, root/rootMargin, viewport/element geometry, zero-area ratios, lifecycle suppression and constructor errors (instruction `tasks/happy-dom-deterministic-intersectionobserver/instruction.md:1-27`). | No external service, but Node/TypeScript plus event-loop timing and geometry scheduling need a carefully bounded scenario driver. Dossier lines 154-160 require exact callback/record/timing correlation; avoid wall-clock-only assertions. |
| 8 | **go-git-worktree-merge-conflicts** — 17/2 ([dossier, lines 19-20](DeepSWE/go-git-worktree-merge-conflicts.md#L19)) | Go repository driver; fast-forward/3-way merges, overlap and repeated-line conflicts, add/add/delete-modify/file-directory cases, conflict markers, index stages, MERGE_HEAD, status, resolution and commit parents (instruction `tasks/go-git-worktree-merge-conflicts/instruction.md:24-28`). | Low P2P count hides high state complexity. The Oracle must independently parse worktree bytes, index stages/blob hashes, refs and commit parents, and prove dirty-merge non-mutation. Dossier lines 111-117 call for these checks. |
| 9 | **opa-template-string-reconstruction** — 5/4 ([dossier, lines 19-20](DeepSWE/opa-template-string-reconstruction.md#L19)) | Go OPA partial evaluation and CLI source output; residual and nested template strings, generated bindings, support modules and `PartialResult` reuse (instruction `tasks/opa-template-string-reconstruction/instruction.md:1-3`). | Only nine scored nodes, but faithful Oracle checking needs an independent Rego parser/evaluator for residual semantics and source representability. OPA build/runtime is heavy. Dossier lines 115-123 explicitly require partial-result reuse, CLI formatting and semantic re-evaluation. |
| 10 | **yaegi-go-embed-directives** — 38/58 ([dossier, lines 19-20](DeepSWE/yaegi-go-embed-directives.md#L19); source `tests/config.json:3-70`) | Go interpreter protocol over a virtual source filesystem; string/`[]byte`/`embed.FS`, glob cardinality, hidden files and `all:`, directories, sorted/read-only FS operations, init timing, errors and legacy regressions (instruction `tasks/yaegi-go-embed-directives/instruction.md:3-21`). | Highest cost: candidate and supplied interpreted programs execute in Evaluation, with filesystem and interpreter resource bounds. Oracle must correlate stdout/errors and many `io/fs` operations without trusting guest assertions. Dossier lines 161-170 require this full surface. |

## Reserves

These are approved clean designs in the dossiers but their source task
directories were not among the ten materialized for this screening.  Materialize
and preflight them before replacing a ranked row.

1. **etree-xml-diff-patch** — 52/15 ([dossier, lines 19-20](DeepSWE/etree-xml-diff-patch.md#L19)).  It has a direct XML/artifact boundary and no service dependency, but diff/patch/reverse/three-way merge, XPath selectors, metadata, nil behavior, and an independent XML Oracle are broad ([lines 166-172](DeepSWE/etree-xml-diff-patch.md#L166)).
2. **helm-array-merge-strategies** — 47/12 ([dossier, lines 19-20](DeepSWE/helm-array-merge-strategies.md#L19)).  It can reuse Helm build infrastructure, but chart/subchart/global scopes, CLI precedence, upgrade modes and lint warnings make its semantic surface materially wider than unified manifest streaming ([lines 24-28](DeepSWE/helm-array-merge-strategies.md#L24)).

## Selection limits

The dossier conversion notes are design claims.  They do not establish base
failure, reference success, mutant rejection, malicious-candidate rejection,
runtime qualification, or admission.  Each selected row remains
qualification-pending until those checks run with a fresh Evaluation VM and a
host-side Oracle.  In particular, the source verifier's F2P/P2P report is
evidence about the original co-located test harness, not evidence that a new
adapter or synthetic observation preserves the same semantics.
