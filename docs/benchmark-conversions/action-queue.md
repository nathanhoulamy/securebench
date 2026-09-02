# Conversion action queue

This focused register contains all 32 rows that are excluded from conversion,
plus eight approved rows that still require a major redesign. Approved clean and
semantic-change designs remain in [`inventory.csv`](inventory.csv) without being
duplicated here.

## Priority interpretation

1. **Excluded:** do not convert. DeepSWE rows in this group still need a
   stronger decision or design; TerminalBench exclusions have no approved safe
   conversion under the current trust model.
2. **Approved major redesign:** direction is accepted, but common verifier
   infrastructure or a benchmark rewrite is still needed.

## Excluded — DeepSWE (16)

| Benchmark | Task | Pattern | Impact | Final verdict |
|---|---|---|---|---|
| DeepSWE | [`adaptix-name-mapping-aliases`](DeepSWE/adaptix-name-mapping-aliases.md) | Black-box challenge/response | Moderate | Excluded — Major redesign |
| DeepSWE | [`arktype-json-schema-refs-dependencies`](DeepSWE/arktype-json-schema-refs-dependencies.md) | Black-box challenge/response | Low | Excluded — Major redesign |
| DeepSWE | [`fastapi-implicit-head-options`](DeepSWE/fastapi-implicit-head-options.md) | Black-box challenge/response + passive artifact verification | Moderate | Excluded — Major redesign |
| DeepSWE | [`gql-incremental-graphql-delivery`](DeepSWE/gql-incremental-graphql-delivery.md) | Black-box challenge/response | Moderate | Excluded — Major redesign |
| DeepSWE | [`httpx-deterministic-cookie-store`](DeepSWE/httpx-deterministic-cookie-store.md) | Black-box challenge/response | Moderate | Excluded — Major redesign |
| DeepSWE | [`httpx-multipart-response-parsing`](DeepSWE/httpx-multipart-response-parsing.md) | Black-box challenge/response | Moderate | Excluded — Major redesign |
| DeepSWE | [`httpx-streaming-json-iteration`](DeepSWE/httpx-streaming-json-iteration.md) | Black-box challenge/response | Moderate | Excluded — Major redesign |
| DeepSWE | [`katex-multicolumn-array-spans`](DeepSWE/katex-multicolumn-array-spans.md) | Black-box challenge/response | Moderate | Excluded — Major redesign |
| DeepSWE | [`kombu-single-active-consumer-priority`](DeepSWE/kombu-single-active-consumer-priority.md) | Black-box challenge/response | Moderate | Excluded — Major redesign |
| DeepSWE | [`kombu-virtual-queue-dead-lettering`](DeepSWE/kombu-virtual-queue-dead-lettering.md) | Black-box challenge/response | Moderate | Excluded — Major redesign |
| DeepSWE | [`langchain-request-coalescing`](DeepSWE/langchain-request-coalescing.md) | Trusted external state | Moderate | Excluded — Major redesign |
| DeepSWE | [`mnamer-daemon-watch-lifecycle`](DeepSWE/mnamer-daemon-watch-lifecycle.md) | Trusted external state | Moderate | Excluded — Major redesign |
| DeepSWE | [`mobly-grouped-test-barriers`](DeepSWE/mobly-grouped-test-barriers.md) | Trusted external state | Moderate | Excluded — Major redesign |
| DeepSWE | [`numba-stencil-boundary-modes`](DeepSWE/numba-stencil-boundary-modes.md) | Black-box challenge/response | Moderate | Excluded — Conversion with semantic change |
| DeepSWE | [`pebble-durability-wait-apis`](DeepSWE/pebble-durability-wait-apis.md) | Trusted external state | Moderate | Excluded — Major redesign |
| DeepSWE | [`vulture-persistent-analysis-cache`](DeepSWE/vulture-persistent-analysis-cache.md) | Black-box challenge/response + passive artifact verification + trusted external state | Moderate | Excluded — Major redesign |


## Approved major redesign — 8

| Benchmark | Task | Pattern | Impact | Final verdict |
|---|---|---|---|---|
| DeepSWE | [`ofetch-per-origin-circuit-breaker`](DeepSWE/ofetch-per-origin-circuit-breaker.md) | Trusted external state | Low | Approved — Major redesign |
| DeepSWE | [`query-persist-restored-query-state`](DeepSWE/query-persist-restored-query-state.md) | Trusted external state | Low | Approved — Major redesign |
| Terminal-Bench 2.0 | [`largest-eigenval`](TerminalBench/largest-eigenval.md) | Black-box challenge/response | Not separately rated | Approved — Major redesign |
| Terminal-Bench 2.0 | [`mailman`](TerminalBench/mailman.md) | Black-box challenge/response + trusted external state | Not separately rated | Approved — Major redesign |
| Terminal-Bench 2.0 | [`nginx-request-logging`](TerminalBench/nginx-request-logging.md) | Black-box challenge/response + passive artifact verification | Not separately rated | Approved — Major redesign |
| Terminal-Bench 2.0 | [`query-optimize`](TerminalBench/query-optimize.md) | Black-box challenge/response | Not separately rated | Approved — Major redesign |
| Terminal-Bench 2.0 | [`train-fasttext`](TerminalBench/train-fasttext.md) | Black-box challenge/response + passive artifact verification | Not separately rated | Approved — Major redesign |
| Terminal-Bench 2.0 | [`tune-mjcf`](TerminalBench/tune-mjcf.md) | Black-box challenge/response | Not separately rated | Approved — Major redesign |


## Excluded — TerminalBench (16)

| Benchmark | Task | Pattern | Impact | Final verdict |
|---|---|---|---|---|
| Terminal-Bench 2.0 | [`build-cython-ext`](TerminalBench/build-cython-ext.md) | No approved pattern (excluded) | Not separately rated | Excluded — No conversion |
| Terminal-Bench 2.0 | [`caffe-cifar-10`](TerminalBench/caffe-cifar-10.md) | No approved pattern (excluded) | Not separately rated | Excluded — No conversion |
| Terminal-Bench 2.0 | [`custom-memory-heap-crash`](TerminalBench/custom-memory-heap-crash.md) | No approved pattern (excluded) | Not separately rated | Excluded — No conversion |
| Terminal-Bench 2.0 | [`feal-differential-cryptanalysis`](TerminalBench/feal-differential-cryptanalysis.md) | No approved pattern (excluded) | Not separately rated | Excluded — No conversion |
| Terminal-Bench 2.0 | [`filter-js-from-html`](TerminalBench/filter-js-from-html.md) | No approved pattern (excluded) | Not separately rated | Excluded — No conversion |
| Terminal-Bench 2.0 | [`fix-ocaml-gc`](TerminalBench/fix-ocaml-gc.md) | No approved pattern (excluded) | Not separately rated | Excluded — No conversion |
| Terminal-Bench 2.0 | [`git-multibranch`](TerminalBench/git-multibranch.md) | Multi-participant service redesign required | Not separately rated | Excluded — Current runtime unsupported |
| Terminal-Bench 2.0 | [`mcmc-sampling-stan`](TerminalBench/mcmc-sampling-stan.md) | No approved pattern (excluded) | Not separately rated | Excluded — No conversion |
| Terminal-Bench 2.0 | [`model-extraction-relu-logits`](TerminalBench/model-extraction-relu-logits.md) | No approved pattern (excluded) | Not separately rated | Excluded — No conversion |
| Terminal-Bench 2.0 | [`portfolio-optimization`](TerminalBench/portfolio-optimization.md) | No approved pattern (excluded) | Not separately rated | Excluded — No conversion |
| Terminal-Bench 2.0 | [`pytorch-model-recovery`](TerminalBench/pytorch-model-recovery.md) | No approved pattern (excluded) | Not separately rated | Excluded — No conversion |
| Terminal-Bench 2.0 | [`qemu-alpine-ssh`](TerminalBench/qemu-alpine-ssh.md) | No approved pattern (excluded) | Not separately rated | Excluded — No conversion |
| Terminal-Bench 2.0 | [`qemu-startup`](TerminalBench/qemu-startup.md) | No approved pattern (excluded) | Not separately rated | Excluded — No conversion |
| Terminal-Bench 2.0 | [`reshard-c4-data`](TerminalBench/reshard-c4-data.md) | No approved pattern (excluded) | Not separately rated | Excluded — No conversion |
| Terminal-Bench 2.0 | [`torch-pipeline-parallelism`](TerminalBench/torch-pipeline-parallelism.md) | No approved pattern (excluded) | Not separately rated | Excluded — No conversion |
| Terminal-Bench 2.0 | [`torch-tensor-parallelism`](TerminalBench/torch-tensor-parallelism.md) | No approved pattern (excluded) | Not separately rated | Excluded — No conversion |
