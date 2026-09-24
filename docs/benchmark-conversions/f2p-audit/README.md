# F2P coverage audit (2026-09-24)

A read-only audit of whether each admitted DeepSWE row's Oracle checks every
upstream F2P assertion on its own exact input and at upstream's strength
(playbook #24 and #20). The 22 rows below exclude the 8 rows already mapped
one-to-one: meriyah, true-myth, mashumaro, csstree, tomlkit,
obsidian-linter-scoped-ignore-markers, anko and tengo-callable. Per-node
detail is in `group-{a,b,c,d}.md`.

| Row | Nodes | Covered | Weaker | Stricter | Missing | Fix effort |
|---|---:|---:|---:|---:|---:|---|
| tengo-destructuring-bindings | 91 | 91 | 0 | 0 | 0 | clean |
| ink-grid-box-layout | 25 | 25 | 0 | 0 | 0 | clean |
| etree-xml-diff-patch | 52 | 51 | 1 | 0 | 0 | trivial |
| sqlfmt-create-table-ddl-formatting | 32 | 31 | 1 | 0 | 0 | small |
| python-statemachine-state-data-scoping | 72 | 67 | 3 | 1 | 1 | small |
| helm-array-merge-strategies | 44 | 41 | 0 | 0 | 3 | small |
| prometheus-typed-label-sorting | 17 | 15 | 2 | 0 | 0 | small |
| task-task-graph-export | 20 | 17 | 1 | 1 | 1 | small |
| go-critic-doc-link-checker | 3 | 1 | 0 | 0 | 1 | small (1 private) |
| happy-dom-deterministic-intersectionobserver | 14 | 3 | 11 | 0 | 0 | small (literal substitutions) |
| helm-unified-manifest-stream | 4 | 0 | 4 | 0 | 0 | small–medium |
| skrub-duration-encoding | 130 | 44 | 0 | 0 | 86 | small–medium (one backend per case) |
| updo-policy-alerting | 17 | 12 | 1 | 0 | 4 | medium |
| termenv-preserve-ansi-resets | 35 | 24 | 0 | 5 | 6 | medium |
| ts-pattern-match-each | 85 | 66 | 7 | 0 | 12 | medium |
| dateutil-rfc5545-timezone-interop | 67 | 19 | 24 | 1 | 23 | medium–large |
| cattrs-partial-structuring-recovery | 69 | 17 | 9 | 0 | 43 | large |
| fd-deterministic-multi-key-sorting | 43 | 14 | 15 | 0 | 14 | large |
| returns-validated-error-accumulation | 159 | 91 | 18 | 0 | 50 | large |
| bandit-structured-nosec-directives | 69 | 36 | 3 | 0 | 30 | large |
| pest-character-class-coalescing | 104 | 2 | 38 | 0 | 64 | large |
| narwhals-rolling-window-suite | 103 | 3 | 18 | 0 | 82 | large |

Group B applied the strictest reading: a same-shape case with substituted
literals counts as Weaker. The other groups sometimes counted such cases as
Covered. Weaker-by-substituted-literal is a smaller risk than Missing.
