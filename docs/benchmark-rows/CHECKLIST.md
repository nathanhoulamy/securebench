# Benchmark row review checklist

This checklist is intentionally empty at setup time. Check a row only after we have reviewed its goal and original tests together and recorded the conversion decision in that row's dossier.

## Review completion definition

A row is complete when we have:

- read the public task and original verifier;
- enumerated the scoring-relevant assertions;
- decided how, or whether, the row can use the new split-verification standard;
- recorded any change in benchmark meaning;
- assigned a final status such as convertible, redesign required, or excluded;
- defined how the converted verifier will be validated.

## Terminal-Bench 2.0 — 89/89 reviewed

Source snapshot: [`harbor-framework/terminal-bench-2@2fd12b88aafdd04a52c298e3940bcb189f9766d6`](https://github.com/harbor-framework/terminal-bench-2/tree/2fd12b88aafdd04a52c298e3940bcb189f9766d6)

Interactive overview: [`Terminal-Bench split-verification review dashboard`](terminalbench-review-dashboard.html)

Non-clean decisions: [`Terminal-Bench semantic-change, redesign, and exclusion register`](NON-CLEAN-QUEUE.md)

### Final decision summary

All 89 rows have a recorded full split-verification decision:

- 52 clean conversions;
- 15 conversions with a recorded semantic change;
- 6 major redesigns;
- 16 exclusions.

Among the 73 rows retaining a conversion design, the approved verification architecture is:

| Pattern | Clean | Semantic change | Major redesign | Total |
|---|---:|---:|---:|---:|
| Passive artifact verification | 28 | 1 | 0 | 29 |
| Black-box challenge/response | 17 | 10 | 3 | 30 |
| Passive artifact verification + black-box challenge/response | 5 | 4 | 2 | 11 |
| Black-box challenge/response + trusted external state | 1 | 0 | 1 | 2 |
| All three approved patterns | 1 | 0 | 0 | 1 |
| **Total convertible/redesignable** | **52** | **15** | **6** | **73** |

The remaining 16 rows are excluded because no currently approved executable pattern preserves their essential scored behavior at acceptable trust or implementation cost. No Terminal-Bench row requires a third core check type.

### Reviewed / approved — 89

| Row | Approved pattern | Final verdict |
|---|---|---|
| [`adaptive-rejection-sampler`](TerminalBench/adaptive-rejection-sampler.md) | Black-box challenge/response | Approved — Conversion with semantic change |
| [`bn-fit-modify`](TerminalBench/bn-fit-modify.md) | Passive artifact verification | Approved — Clean conversion |
| [`break-filter-js-from-html`](TerminalBench/break-filter-js-from-html.md) | Passive artifact verification + black-box challenge/response | Approved — Clean conversion |
| [`build-cython-ext`](TerminalBench/build-cython-ext.md) | Redesign or exclude | Approved — Exclude |
| [`build-pmars`](TerminalBench/build-pmars.md) | Black-box challenge/response | Approved — Clean conversion |
| [`build-pov-ray`](TerminalBench/build-pov-ray.md) | Passive artifact verification + black-box challenge/response | Approved — Conversion with semantic change |
| [`caffe-cifar-10`](TerminalBench/caffe-cifar-10.md) | Redesign or exclude | Approved — Exclude |
| [`cancel-async-tasks`](TerminalBench/cancel-async-tasks.md) | Black-box challenge/response + trusted external state | Approved — Clean conversion |
| [`chess-best-move`](TerminalBench/chess-best-move.md) | Passive artifact verification | Approved — Clean conversion |
| [`circuit-fibsqrt`](TerminalBench/circuit-fibsqrt.md) | Black-box challenge/response | Approved — Clean conversion |
| [`cobol-modernization`](TerminalBench/cobol-modernization.md) | Black-box challenge/response | Approved — Clean conversion |
| [`code-from-image`](TerminalBench/code-from-image.md) | Passive artifact verification | Approved — Clean conversion |
| [`compile-compcert`](TerminalBench/compile-compcert.md) | Passive artifact verification + black-box challenge/response | Approved — Conversion with semantic change |
| [`configure-git-webserver`](TerminalBench/configure-git-webserver.md) | Black-box challenge/response | Approved — Clean conversion |
| [`constraints-scheduling`](TerminalBench/constraints-scheduling.md) | Passive artifact verification | Approved — Clean conversion |
| [`count-dataset-tokens`](TerminalBench/count-dataset-tokens.md) | Passive artifact verification | Approved — Clean conversion |
| [`crack-7z-hash`](TerminalBench/crack-7z-hash.md) | Passive artifact verification | Approved — Clean conversion |
| [`custom-memory-heap-crash`](TerminalBench/custom-memory-heap-crash.md) | Redesign or exclude | Approved — Exclude |
| [`db-wal-recovery`](TerminalBench/db-wal-recovery.md) | Passive artifact verification | Approved — Clean conversion |
| [`distribution-search`](TerminalBench/distribution-search.md) | Passive artifact verification | Approved — Clean conversion |
| [`dna-assembly`](TerminalBench/dna-assembly.md) | Passive artifact verification | Approved — Clean conversion |
| [`dna-insert`](TerminalBench/dna-insert.md) | Passive artifact verification | Approved — Clean conversion |
| [`extract-elf`](TerminalBench/extract-elf.md) | Black-box challenge/response | Approved — Clean conversion |
| [`extract-moves-from-video`](TerminalBench/extract-moves-from-video.md) | Passive artifact verification | Approved — Clean conversion |
| [`feal-differential-cryptanalysis`](TerminalBench/feal-differential-cryptanalysis.md) | Redesign or exclude | Approved — Exclude |
| [`feal-linear-cryptanalysis`](TerminalBench/feal-linear-cryptanalysis.md) | Passive artifact verification | Approved — Clean conversion |
| [`filter-js-from-html`](TerminalBench/filter-js-from-html.md) | Redesign or exclude | Approved — Exclude |
| [`financial-document-processor`](TerminalBench/financial-document-processor.md) | Passive artifact verification | Approved — Clean conversion |
| [`fix-code-vulnerability`](TerminalBench/fix-code-vulnerability.md) | Black-box challenge/response | Approved — Clean conversion |
| [`fix-git`](TerminalBench/fix-git.md) | Passive artifact verification | Approved — Clean conversion |
| [`fix-ocaml-gc`](TerminalBench/fix-ocaml-gc.md) | Redesign or exclude | Approved — Exclude |
| [`gcode-to-text`](TerminalBench/gcode-to-text.md) | Passive artifact verification | Approved — Clean conversion |
| [`git-leak-recovery`](TerminalBench/git-leak-recovery.md) | Passive artifact verification | Approved — Clean conversion |
| [`git-multibranch`](TerminalBench/git-multibranch.md) | Multi-participant service redesign required | Excluded — current runtime unsupported |
| [`gpt2-codegolf`](TerminalBench/gpt2-codegolf.md) | Black-box challenge/response | Approved — Clean conversion |
| [`headless-terminal`](TerminalBench/headless-terminal.md) | Black-box challenge/response | Approved — Conversion with semantic change |
| [`hf-model-inference`](TerminalBench/hf-model-inference.md) | Black-box challenge/response | Approved — Conversion with semantic change |
| [`install-windows-3.11`](TerminalBench/install-windows-3.11.md) | Black-box challenge/response + trusted external state | Approved — Conversion with semantic change |
| [`kv-store-grpc`](TerminalBench/kv-store-grpc.md) | Black-box challenge/response | Approved — Conversion with semantic change |
| [`large-scale-text-editing`](TerminalBench/large-scale-text-editing.md) | Black-box challenge/response | Approved — Clean conversion |
| [`largest-eigenval`](TerminalBench/largest-eigenval.md) | Black-box challenge/response | Approved — Major redesign |
| [`llm-inference-batching-scheduler`](TerminalBench/llm-inference-batching-scheduler.md) | Passive artifact verification | Approved — Clean conversion |
| [`log-summary-date-ranges`](TerminalBench/log-summary-date-ranges.md) | Passive artifact verification | Approved — Clean conversion |
| [`mailman`](TerminalBench/mailman.md) | Black-box challenge/response + trusted external state | Approved — Major redesign |
| [`make-doom-for-mips`](TerminalBench/make-doom-for-mips.md) | Black-box challenge/response | Approved — Clean conversion |
| [`make-mips-interpreter`](TerminalBench/make-mips-interpreter.md) | Black-box challenge/response | Approved — Clean conversion |
| [`mcmc-sampling-stan`](TerminalBench/mcmc-sampling-stan.md) | Redesign or exclude | Approved — Exclude |
| [`merge-diff-arc-agi-task`](TerminalBench/merge-diff-arc-agi-task.md) | Passive artifact verification + black-box challenge/response | Approved — Clean conversion |
| [`model-extraction-relu-logits`](TerminalBench/model-extraction-relu-logits.md) | Redesign or exclude | Approved — Exclude |
| [`modernize-scientific-stack`](TerminalBench/modernize-scientific-stack.md) | Passive artifact verification + black-box challenge/response | Approved — Conversion with semantic change |
| [`mteb-leaderboard`](TerminalBench/mteb-leaderboard.md) | Passive artifact verification | Approved — Clean conversion |
| [`mteb-retrieve`](TerminalBench/mteb-retrieve.md) | Passive artifact verification | Approved — Clean conversion |
| [`multi-source-data-merger`](TerminalBench/multi-source-data-merger.md) | Passive artifact verification | Approved — Clean conversion |
| [`nginx-request-logging`](TerminalBench/nginx-request-logging.md) | Passive artifact verification + black-box challenge/response | Approved — Major redesign |
| [`openssl-selfsigned-cert`](TerminalBench/openssl-selfsigned-cert.md) | Passive artifact verification + black-box challenge/response | Approved — Conversion with semantic change |
| [`overfull-hbox`](TerminalBench/overfull-hbox.md) | Passive artifact verification + black-box challenge/response | Approved — Clean conversion |
| [`password-recovery`](TerminalBench/password-recovery.md) | Passive artifact verification | Approved — Clean conversion |
| [`path-tracing-reverse`](TerminalBench/path-tracing-reverse.md) | Black-box challenge/response | Approved — Conversion with semantic change |
| [`path-tracing`](TerminalBench/path-tracing.md) | Black-box challenge/response | Approved — Conversion with semantic change |
| [`polyglot-c-py`](TerminalBench/polyglot-c-py.md) | Black-box challenge/response | Approved — Clean conversion |
| [`polyglot-rust-c`](TerminalBench/polyglot-rust-c.md) | Black-box challenge/response | Approved — Clean conversion |
| [`portfolio-optimization`](TerminalBench/portfolio-optimization.md) | Redesign or exclude | Approved — Exclude |
| [`protein-assembly`](TerminalBench/protein-assembly.md) | Passive artifact verification | Approved — Clean conversion |
| [`prove-plus-comm`](TerminalBench/prove-plus-comm.md) | Black-box challenge/response | Approved — Conversion with semantic change |
| [`pypi-server`](TerminalBench/pypi-server.md) | Black-box challenge/response | Approved — Conversion with semantic change |
| [`pytorch-model-cli`](TerminalBench/pytorch-model-cli.md) | Passive artifact verification + black-box challenge/response | Approved — Clean conversion |
| [`pytorch-model-recovery`](TerminalBench/pytorch-model-recovery.md) | Redesign or exclude | Approved — Exclude |
| [`qemu-alpine-ssh`](TerminalBench/qemu-alpine-ssh.md) | Redesign or exclude | Approved — Exclude |
| [`qemu-startup`](TerminalBench/qemu-startup.md) | Redesign or exclude | Approved — Exclude |
| [`query-optimize`](TerminalBench/query-optimize.md) | Black-box challenge/response | Approved — Major redesign |
| [`raman-fitting`](TerminalBench/raman-fitting.md) | Passive artifact verification | Approved — Clean conversion |
| [`regex-chess`](TerminalBench/regex-chess.md) | Black-box challenge/response | Approved — Conversion with semantic change |
| [`regex-log`](TerminalBench/regex-log.md) | Black-box challenge/response | Approved — Clean conversion |
| [`reshard-c4-data`](TerminalBench/reshard-c4-data.md) | Redesign or exclude | Approved — Exclude |
| [`rstan-to-pystan`](TerminalBench/rstan-to-pystan.md) | Passive artifact verification | Approved — Conversion with semantic change |
| [`sam-cell-seg`](TerminalBench/sam-cell-seg.md) | Black-box challenge/response | Approved — Clean conversion |
| [`sanitize-git-repo`](TerminalBench/sanitize-git-repo.md) | Passive artifact verification | Approved — Clean conversion |
| [`schemelike-metacircular-eval`](TerminalBench/schemelike-metacircular-eval.md) | Black-box challenge/response | Approved — Conversion with semantic change |
| [`sparql-university`](TerminalBench/sparql-university.md) | Black-box challenge/response | Approved — Clean conversion |
| [`sqlite-db-truncate`](TerminalBench/sqlite-db-truncate.md) | Passive artifact verification | Approved — Clean conversion |
| [`sqlite-with-gcov`](TerminalBench/sqlite-with-gcov.md) | Passive artifact verification + black-box challenge/response | Approved — Clean conversion |
| [`torch-pipeline-parallelism`](TerminalBench/torch-pipeline-parallelism.md) | Redesign or exclude | Approved — Exclude |
| [`torch-tensor-parallelism`](TerminalBench/torch-tensor-parallelism.md) | Redesign or exclude | Approved — Exclude |
| [`train-fasttext`](TerminalBench/train-fasttext.md) | Passive artifact verification + black-box challenge/response | Approved — Major redesign |
| [`tune-mjcf`](TerminalBench/tune-mjcf.md) | Black-box challenge/response | Approved — Major redesign |
| [`video-processing`](TerminalBench/video-processing.md) | Black-box challenge/response | Approved — Clean conversion |
| [`vulnerable-secret`](TerminalBench/vulnerable-secret.md) | Passive artifact verification | Approved — Clean conversion |
| [`winning-avg-corewars`](TerminalBench/winning-avg-corewars.md) | Black-box challenge/response | Approved — Clean conversion |
| [`write-compressor`](TerminalBench/write-compressor.md) | Passive artifact verification | Approved — Clean conversion |

## DeepSWE — 97/113 reviewed

Source snapshot: [`datacurve-ai/deep-swe@e016041a6ccf8da29906afc9a3f5a8df940a1f78`](https://github.com/datacurve-ai/deep-swe/tree/e016041a6ccf8da29906afc9a3f5a8df940a1f78)

Interactive overview: [`DeepSWE split-verification review dashboard`](deepswe-review-dashboard.html)

Unified redesign draft: [`Proposed DeepSWE split-verification row shape`](../proposed-deepswe-split-row-shape.md)

- Pattern key: **Black-box challenge/response** runs secret per-case inputs against public behavior; **Passive artifact verification** parses bounded outputs/source without executing them on the Oracle; **Trusted external state** corroborates behavior with host-owned services, ledgers, clocks, or supervisors. Combined labels indicate hybrid designs.

### Checked / approved — 97

| Task | Proposed pattern | Intelligence impact | Final verdict |
|---|---|---|---|
| [`abs-module-cache-flags`](DeepSWE/abs-module-cache-flags.md) | Black-box challenge/response | Low | Approved — Conversion with semantic change |
| [`abs-stepped-slices`](DeepSWE/abs-stepped-slices.md) | Black-box challenge/response | Low | Approved — Conversion with semantic change |
| [`actionlint-action-pinning-lint`](DeepSWE/actionlint-action-pinning-lint.md) | Black-box challenge/response | Low | Approved — Conversion with semantic change |
| [`aiomonitor-task-snapshots-diff`](DeepSWE/aiomonitor-task-snapshots-diff.md) | Black-box challenge/response + trusted external state | Low | Approved — Conversion with semantic change |
| [`anko-default-function-arguments`](DeepSWE/anko-default-function-arguments.md) | Black-box challenge/response | Low | Approved — Conversion with semantic change |
| [`anko-typed-variable-bindings`](DeepSWE/anko-typed-variable-bindings.md) | Black-box challenge/response | Low | Approved — Conversion with semantic change |
| [`arcane-drift-detection-baselines`](DeepSWE/arcane-drift-detection-baselines.md) | Black-box challenge/response + passive artifact verification + trusted external state | Low | Approved — Conversion with semantic change |
| [`awilix-async-container-initialization`](DeepSWE/awilix-async-container-initialization.md) | Trusted external state | Low | Approved — Conversion with semantic change |
| [`bandit-incremental-cache-control`](DeepSWE/bandit-incremental-cache-control.md) | Trusted external state | Low | Approved — Conversion with semantic change |
| [`bandit-interprocedural-taint-checks`](DeepSWE/bandit-interprocedural-taint-checks.md) | Black-box challenge/response | Low | Approved — Conversion with semantic change |
| [`bandit-structured-nosec-directives`](DeepSWE/bandit-structured-nosec-directives.md) | Black-box challenge/response | Low | Approved — Conversion with semantic change |
| [`boa-hierarchical-evaluation-cancellation`](DeepSWE/boa-hierarchical-evaluation-cancellation.md) | Black-box challenge/response | None | Approved — Clean conversion |
| [`cattrs-partial-structuring-recovery`](DeepSWE/cattrs-partial-structuring-recovery.md) | Black-box challenge/response | None | Approved — Clean conversion |
| [`clack-async-autocomplete-options`](DeepSWE/clack-async-autocomplete-options.md) | Black-box challenge/response + trusted external state | Low | Approved — Conversion with semantic change |
| [`claude-code-by-agents-recursive-delegation`](DeepSWE/claude-code-by-agents-recursive-delegation.md) | Trusted external state | None | Approved — Clean conversion |
| [`cliffy-config-file-parsing`](DeepSWE/cliffy-config-file-parsing.md) | Black-box challenge/response | Low | Approved — Conversion with semantic change |
| [`csstree-shorthand-expansion-compression`](DeepSWE/csstree-shorthand-expansion-compression.md) | Black-box challenge/response | Low | Approved — Conversion with semantic change |
| [`dasel-html-document-format`](DeepSWE/dasel-html-document-format.md) | Black-box challenge/response | Low | Approved — Conversion with semantic change |
| [`dateutil-rfc5545-timezone-interop`](DeepSWE/dateutil-rfc5545-timezone-interop.md) | Black-box challenge/response | Low | Approved — Conversion with semantic change |
| [`drizzle-orm-window-function-builders`](DeepSWE/drizzle-orm-window-function-builders.md) | Black-box challenge/response + passive artifact verification | Low | Approved — Conversion with semantic change |
| [`dynamodb-toolbox-conditional-attribute-requirements`](DeepSWE/dynamodb-toolbox-conditional-attribute-requirements.md) | Black-box challenge/response | Low | Approved — Conversion with semantic change |
| [`dynamodb-toolbox-lazy-recursive-schemas`](DeepSWE/dynamodb-toolbox-lazy-recursive-schemas.md) | Black-box challenge/response | Low | Approved — Conversion with semantic change |
| [`effect-sse-httpapi-streaming`](DeepSWE/effect-sse-httpapi-streaming.md) | Black-box challenge/response | None | Approved — Clean conversion |
| [`eicrud-keyset-pagination-cursor`](DeepSWE/eicrud-keyset-pagination-cursor.md) | Black-box challenge/response + trusted external state | Low | Approved — Conversion with semantic change |
| [`etree-xml-diff-patch`](DeepSWE/etree-xml-diff-patch.md) | Black-box challenge/response | None | Approved — Clean conversion |
| [`expr-try-catch-errors`](DeepSWE/expr-try-catch-errors.md) | Black-box challenge/response | Low | Approved — Conversion with semantic change |
| [`fastapi-deprecation-response-headers`](DeepSWE/fastapi-deprecation-response-headers.md) | Black-box challenge/response | Low | Approved — Conversion with semantic change |
| [`fd-deterministic-multi-key-sorting`](DeepSWE/fd-deterministic-multi-key-sorting.md) | Black-box challenge/response | None | Approved — Clean conversion |
| [`geo-shapeindex-serialization`](DeepSWE/geo-shapeindex-serialization.md) | Black-box challenge/response | Low | Approved — Conversion with semantic change |
| [`go-critic-doc-link-checker`](DeepSWE/go-critic-doc-link-checker.md) | Black-box challenge/response | None | Approved — Clean conversion |
| [`go-genai-streamed-function-args`](DeepSWE/go-genai-streamed-function-args.md) | Black-box challenge/response | Low | Approved — Conversion with semantic change |
| [`go-git-worktree-merge-conflicts`](DeepSWE/go-git-worktree-merge-conflicts.md) | Black-box challenge/response | None | Approved — Clean conversion |
| [`goreleaser-retry-publish-auditing`](DeepSWE/goreleaser-retry-publish-auditing.md) | Trusted external state | Low | Approved — Conversion with semantic change |
| [`happy-dom-abort-pending-body-reads`](DeepSWE/happy-dom-abort-pending-body-reads.md) | Black-box challenge/response | Low | Approved — Conversion with semantic change |
| [`happy-dom-deterministic-intersectionobserver`](DeepSWE/happy-dom-deterministic-intersectionobserver.md) | Black-box challenge/response | None | Approved — Clean conversion |
| [`helm-array-merge-strategies`](DeepSWE/helm-array-merge-strategies.md) | Black-box challenge/response | None | Approved — Clean conversion |
| [`helm-unified-manifest-stream`](DeepSWE/helm-unified-manifest-stream.md) | Passive artifact verification | None | Approved — Clean conversion |
| [`igel-persist-feature-schema`](DeepSWE/igel-persist-feature-schema.md) | Trusted external state | None | Approved — Clean conversion |
| [`ink-grid-box-layout`](DeepSWE/ink-grid-box-layout.md) | Black-box challenge/response | None | Approved — Clean conversion |
| [`ipython-session-bundle-replay`](DeepSWE/ipython-session-bundle-replay.md) | Black-box challenge/response | Low | Approved — Conversion with semantic change |
| [`kcp-go-multiplexed-kcp-streams`](DeepSWE/kcp-go-multiplexed-kcp-streams.md) | Trusted external state | Low | Approved — Conversion with semantic change |
| [`kea-atomic-signal-selectors`](DeepSWE/kea-atomic-signal-selectors.md) | Black-box challenge/response | Low | Approved — Conversion with semantic change |
| [`kgateway-consistent-hash-policy`](DeepSWE/kgateway-consistent-hash-policy.md) | Passive artifact verification | None | Approved — Clean conversion |
| [`koota-composite-trait-aspects`](DeepSWE/koota-composite-trait-aspects.md) | Black-box challenge/response | Low | Approved — Conversion with semantic change |
| [`koota-deferred-mutation-buffer`](DeepSWE/koota-deferred-mutation-buffer.md) | Black-box challenge/response | Low | Approved — Conversion with semantic change |
| [`koota-entity-snapshot-rollback`](DeepSWE/koota-entity-snapshot-rollback.md) | Black-box challenge/response | Low | Approved — Conversion with semantic change |
| [`koota-pair-relation-tracking`](DeepSWE/koota-pair-relation-tracking.md) | Black-box challenge/response | Low | Approved — Conversion with semantic change |
| [`koota-query-predicates`](DeepSWE/koota-query-predicates.md) | Black-box challenge/response | Low | Approved — Conversion with semantic change |
| [`kysely-window-grouping-helpers`](DeepSWE/kysely-window-grouping-helpers.md) | Black-box challenge/response | Low | Approved — Conversion with semantic change |
| [`mashumaro-flattened-dataclass-fields`](DeepSWE/mashumaro-flattened-dataclass-fields.md) | Black-box challenge/response | Low | Approved — Conversion with semantic change |
| [`meriyah-explicit-resource-declarations`](DeepSWE/meriyah-explicit-resource-declarations.md) | Black-box challenge/response | None | Approved — Clean conversion |
| [`narwhals-rolling-window-suite`](DeepSWE/narwhals-rolling-window-suite.md) | Black-box challenge/response | None | Approved — Clean conversion |
| [`obsidian-linter-auto-table-of-contents`](DeepSWE/obsidian-linter-auto-table-of-contents.md) | Black-box challenge/response | Low | Approved — Conversion with semantic change |
| [`obsidian-linter-link-format-conversion`](DeepSWE/obsidian-linter-link-format-conversion.md) | Black-box challenge/response | Low | Approved — Conversion with semantic change |
| [`obsidian-linter-scoped-ignore-markers`](DeepSWE/obsidian-linter-scoped-ignore-markers.md) | Black-box challenge/response | Low | Approved — Conversion with semantic change |
| [`ofetch-per-origin-circuit-breaker`](DeepSWE/ofetch-per-origin-circuit-breaker.md) | Trusted external state | Low | Approved — Major redesign |
| [`onedump-dump-encryption-pipeline`](DeepSWE/onedump-dump-encryption-pipeline.md) | Black-box challenge/response + passive artifact verification | None | Approved — Clean conversion |
| [`opa-rego-rule-profiling`](DeepSWE/opa-rego-rule-profiling.md) | Black-box challenge/response | None | Approved — Clean conversion |
| [`opa-template-string-reconstruction`](DeepSWE/opa-template-string-reconstruction.md) | Black-box challenge/response + passive artifact verification | None | Approved — Clean conversion |
| [`optique-conditional-option-dependencies`](DeepSWE/optique-conditional-option-dependencies.md) | Black-box challenge/response | Low | Approved — Conversion with semantic change |
| [`oxvg-structural-selector-preservation`](DeepSWE/oxvg-structural-selector-preservation.md) | Passive artifact verification | None | Approved — Clean conversion |
| [`participle-grammar-conflict-analysis`](DeepSWE/participle-grammar-conflict-analysis.md) | Black-box challenge/response | None | Approved — Clean conversion |
| [`pest-character-class-coalescing`](DeepSWE/pest-character-class-coalescing.md) | Black-box challenge/response | None | Approved — Clean conversion |
| [`prometheus-transactional-reload-status`](DeepSWE/prometheus-transactional-reload-status.md) | Black-box challenge/response + passive artifact verification | None | Approved — Clean conversion |
| [`prometheus-typed-label-sorting`](DeepSWE/prometheus-typed-label-sorting.md) | Black-box challenge/response | None | Approved — Clean conversion |
| [`psd-tools-blend-range-api`](DeepSWE/psd-tools-blend-range-api.md) | Black-box challenge/response + passive artifact verification | Low | Approved — Conversion with semantic change |
| [`pwntools-tube-multiplexing`](DeepSWE/pwntools-tube-multiplexing.md) | Black-box challenge/response | Low | Approved — Conversion with semantic change |
| [`python-statemachine-state-data-scoping`](DeepSWE/python-statemachine-state-data-scoping.md) | Black-box challenge/response | Low | Approved — Conversion with semantic change |
| [`query-persist-restored-query-state`](DeepSWE/query-persist-restored-query-state.md) | Trusted external state | Low | Approved — Major redesign |
| [`quill-shared-toolbar-focus`](DeepSWE/quill-shared-toolbar-focus.md) | Black-box challenge/response | None | Approved — Clean conversion |
| [`returns-validated-error-accumulation`](DeepSWE/returns-validated-error-accumulation.md) | Black-box challenge/response | Low | Approved — Conversion with semantic change |
| [`scc-bounded-memory-spilling`](DeepSWE/scc-bounded-memory-spilling.md) | Black-box challenge/response + passive artifact verification | Low | Approved — Conversion with semantic change |
| [`scriggo-method-declarations`](DeepSWE/scriggo-method-declarations.md) | Black-box challenge/response | Low | Approved — Conversion with semantic change |
| [`skrub-duration-encoding`](DeepSWE/skrub-duration-encoding.md) | Black-box challenge/response | Low | Approved — Conversion with semantic change |
| [`sql-formatter-bigquery-pipe-formatting`](DeepSWE/sql-formatter-bigquery-pipe-formatting.md) | Black-box challenge/response | Low | Approved — Conversion with semantic change |
| [`sqlfmt-create-table-ddl-formatting`](DeepSWE/sqlfmt-create-table-ddl-formatting.md) | Black-box challenge/response | Low | Approved — Conversion with semantic change |
| [`sqlite-utils-safe-import-checkpoints`](DeepSWE/sqlite-utils-safe-import-checkpoints.md) | Black-box challenge/response + passive artifact verification | Low | Approved — Conversion with semantic change |
| [`superjson-error-stack-serialization`](DeepSWE/superjson-error-stack-serialization.md) | Black-box challenge/response + passive artifact verification | Low | Approved — Conversion with semantic change |
| [`task-task-graph-export`](DeepSWE/task-task-graph-export.md) | Black-box challenge/response + passive artifact verification | None | Approved — Clean conversion |
| [`tengo-callable-instance-isolation`](DeepSWE/tengo-callable-instance-isolation.md) | Black-box challenge/response | Low | Approved — Conversion with semantic change |
| [`tengo-destructuring-bindings`](DeepSWE/tengo-destructuring-bindings.md) | Black-box challenge/response | Low | Approved — Conversion with semantic change |
| [`termenv-preserve-ansi-resets`](DeepSWE/termenv-preserve-ansi-resets.md) | Black-box challenge/response | None | Approved — Clean conversion |
| [`testem-bail-on-test-failure`](DeepSWE/testem-bail-on-test-failure.md) | Black-box challenge/response + passive artifact verification | Low | Approved — Conversion with semantic change |
| [`testem-per-launcher-reports`](DeepSWE/testem-per-launcher-reports.md) | Black-box challenge/response + passive artifact verification | None | Approved — Clean conversion |
| [`textual-kitty-key-phases`](DeepSWE/textual-kitty-key-phases.md) | Black-box challenge/response + passive artifact verification | None | Approved — Clean conversion |
| [`textual-richlog-follow-state`](DeepSWE/textual-richlog-follow-state.md) | Black-box challenge/response + passive artifact verification | Low | Approved — Conversion with semantic change |
| [`tomlkit-toml-table-converters`](DeepSWE/tomlkit-toml-table-converters.md) | Black-box challenge/response + passive artifact verification | Low | Approved — Conversion with semantic change |
| [`true-myth-iterable-collection-combinators`](DeepSWE/true-myth-iterable-collection-combinators.md) | Black-box challenge/response | Low | Approved — Conversion with semantic change |
| [`ts-pattern-match-each`](DeepSWE/ts-pattern-match-each.md) | Black-box challenge/response | Low | Approved — Conversion with semantic change |
| [`updo-policy-alerting`](DeepSWE/updo-policy-alerting.md) | Black-box challenge/response + trusted external state | None | Approved — Clean conversion |
| [`valibot-recursive-schema-composition`](DeepSWE/valibot-recursive-schema-composition.md) | Black-box challenge/response | Low | Approved — Conversion with semantic change |
| [`vitest-duration-sharding`](DeepSWE/vitest-duration-sharding.md) | Black-box challenge/response + passive artifact verification | Low | Approved — Conversion with semantic change |
| [`wasmi-trap-coredumps`](DeepSWE/wasmi-trap-coredumps.md) | Black-box challenge/response + passive artifact verification | Low | Approved — Conversion with semantic change |
| [`wazero-multi-module-snapshots`](DeepSWE/wazero-multi-module-snapshots.md) | Black-box challenge/response + passive artifact verification | Low | Approved — Conversion with semantic change |
| [`yaegi-go-embed-directives`](DeepSWE/yaegi-go-embed-directives.md) | Black-box challenge/response | None | Approved — Clean conversion |
| [`yjs-map-conflict-detection`](DeepSWE/yjs-map-conflict-detection.md) | Black-box challenge/response + passive artifact verification | Low | Approved — Conversion with semantic change |
| [`ytt-jsonpath-query-api`](DeepSWE/ytt-jsonpath-query-api.md) | Black-box challenge/response | None | Approved — Clean conversion |

### Unchecked / deferred — 16

| Task | Proposed pattern | Intelligence impact | Final verdict |
|---|---|---|---|
| [`adaptix-name-mapping-aliases`](DeepSWE/adaptix-name-mapping-aliases.md) | Black-box challenge/response | Moderate | Deferred — Major redesign |
| [`arktype-json-schema-refs-dependencies`](DeepSWE/arktype-json-schema-refs-dependencies.md) | Black-box challenge/response | Low | Deferred — Major redesign |
| [`fastapi-implicit-head-options`](DeepSWE/fastapi-implicit-head-options.md) | Black-box challenge/response + passive artifact verification | Moderate | Deferred — Major redesign |
| [`gql-incremental-graphql-delivery`](DeepSWE/gql-incremental-graphql-delivery.md) | Black-box challenge/response | Moderate | Deferred — Major redesign |
| [`httpx-deterministic-cookie-store`](DeepSWE/httpx-deterministic-cookie-store.md) | Black-box challenge/response | Moderate | Deferred — Major redesign |
| [`httpx-multipart-response-parsing`](DeepSWE/httpx-multipart-response-parsing.md) | Black-box challenge/response | Moderate | Deferred — Major redesign |
| [`httpx-streaming-json-iteration`](DeepSWE/httpx-streaming-json-iteration.md) | Black-box challenge/response | Moderate | Deferred — Major redesign |
| [`katex-multicolumn-array-spans`](DeepSWE/katex-multicolumn-array-spans.md) | Black-box challenge/response | Moderate | Deferred — Major redesign |
| [`kombu-single-active-consumer-priority`](DeepSWE/kombu-single-active-consumer-priority.md) | Black-box challenge/response | Moderate | Deferred — Major redesign |
| [`kombu-virtual-queue-dead-lettering`](DeepSWE/kombu-virtual-queue-dead-lettering.md) | Black-box challenge/response | Moderate | Deferred — Major redesign |
| [`langchain-request-coalescing`](DeepSWE/langchain-request-coalescing.md) | Trusted external state | Moderate | Deferred — Major redesign |
| [`mnamer-daemon-watch-lifecycle`](DeepSWE/mnamer-daemon-watch-lifecycle.md) | Trusted external state | Moderate | Deferred — Major redesign |
| [`mobly-grouped-test-barriers`](DeepSWE/mobly-grouped-test-barriers.md) | Trusted external state | Moderate | Deferred — Major redesign |
| [`numba-stencil-boundary-modes`](DeepSWE/numba-stencil-boundary-modes.md) | Black-box challenge/response | Moderate | Deferred — Conversion with semantic change |
| [`pebble-durability-wait-apis`](DeepSWE/pebble-durability-wait-apis.md) | Trusted external state | Moderate | Deferred — Major redesign |
| [`vulture-persistent-analysis-cache`](DeepSWE/vulture-persistent-analysis-cache.md) | Black-box challenge/response + passive artifact verification + trusted external state | Moderate | Deferred — Major redesign |
