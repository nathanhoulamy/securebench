# Campaign freeze

Written 2026-09-24T23:13:25+00:00.

## Code

- SecureBench git SHA: `50bffce861a0e6fd4ae49cbcf899d2f65170b799` (branch `split-verification-v2`)
- Working tree at freeze (uncommitted paths; the campaign uses only committed rows,
  see ISSUES.md I-01, plus the campaign tooling under `tools/native_baseline/`):

```
M benchmarks/deep-swe/tasks-v2.jsonl
 M benchmarks/terminal-bench/tasks-v2.jsonl
 M benchmarks/terminal-bench/v2/hidden/kv-store-grpc/oracle/oracle.py
 M docs/benchmark-conversions/DeepSWE/expr-try-catch-errors.md
 M docs/benchmark-conversions/DeepSWE/obsidian-linter-auto-table-of-contents.md
 M docs/benchmark-conversions/TerminalBench/kv-store-grpc.md
 M docs/benchmark-conversions/inventory.csv
 M securebench/harnesses/codex.py
 M securebench/harnesses/shared.py
 M tests/test_harness_shared.py
 M tests/test_kv_store_grpc_v2.py
 M tests/test_log_summary_date_ranges_v2.py
 M tests/test_mteb_exact_answer_v2.py
 M tests/test_protein_assembly_v2.py
 M tests/test_raman_fitting_v2.py
 M tests/test_rstan_to_pystan_v2.py
 M tests/test_write_compressor_v2.py
?? benchmarks/deep-swe/v2/evaluation_inputs/expr-try-catch-errors/
?? benchmarks/deep-swe/v2/evaluation_inputs/kysely-window-grouping-helpers/
?? benchmarks/deep-swe/v2/evaluation_inputs/obsidian-linter-auto-table-of-contents/
?? benchmarks/deep-swe/v2/evaluation_inputs/sqlite-utils-safe-import-checkpoints/
?? benchmarks/deep-swe/v2/evaluation_inputs/valibot-recursive-schema-composition/
?? benchmarks/deep-swe/v2/hidden/expr-try-catch-errors/
?? benchmarks/deep-swe/v2/hidden/kysely-window-grouping-helpers/
?? benchmarks/deep-swe/v2/hidden/obsidian-linter-auto-table-of-contents/
?? benchmarks/deep-swe/v2/hidden/sqlite-utils-safe-import-checkpoints/
?? benchmarks/deep-swe/v2/hidden/valibot-recursive-schema-composition/
?? benchmarks/deep-swe/v2/staging/
?? benchmarks/terminal-bench/v2/evaluation_inputs/regex-log/
?? benchmarks/terminal-bench/v2/hidden/regex-log/
?? tests/test_deepswe_expr_try_catch_errors_v2.py
?? tests/test_deepswe_kysely_window_grouping_helpers_v2.py
?? tests/test_deepswe_obsidian_linter_auto_table_of_contents_v2.py
?? tests/test_deepswe_sqlite_utils_safe_import_checkpoints_v2.py
?? tests/test_deepswe_valibot_recursive_schema_composition_v2.py
?? tools/native_baseline/
```

## Agent

- Codex CLI `@openai/codex@0.156.1` (both conditions; pinned, not `latest`)
- Model `gpt-6-luna`, reasoning effort `max` (both conditions)
- Model id accepted by the API: `GET /v1/models/gpt-6-luna` returned 200 on 2026-09-24.
- Cost is computed from Codex-reported token usage with litellm's `gpt-6-luna` prices (USD/token): input 1e-07, cached input 1e-08, output 5e-07 (litellm `1.102.1`).

## Native harnesses (condition A)

- Harbor `0.23.0` (Terminal-Bench 2.0), Pier `0.3.1` (DeepSWE)
- Terminal-Bench 2.0: `harbor-framework/terminal-bench-2` at `2fd12b88aafdd04a52c298e3940bcb189f9766d6`
- DeepSWE: `datacurve-ai/deep-swe` at `e016041a6ccf8da29906afc9a3f5a8df940a1f78`

## Host

- Docker: `client 29.7.2 / server 29.7.2`
- CPU: Intel(R) Core(TM) i7-8700 CPU @ 3.20GHz, 12 logical CPUs
- RAM: 30.7 GiB
- OS: Ubuntu 26.04 LTS, kernel 7.0.0-31-generic
- Python (SecureBench venv): Python 3.14.4

## Images

`securebench_image` is the digest SecureBench pins. `upstream_tag_digest_at_freeze` is what
the upstream tag resolved to at freeze. They differ only for the 7 locally rebuilt TB images
(ISSUES.md I-06).

| pack | task | securebench_image | upstream_image | upstream tag digest at freeze |
|---|---|---|---|---|
| deep-swe | cattrs-partial-structuring-recovery | `public.ecr.aws/d3j8x8q7/swe-bench-202605@sha256:443a3534dab64283e5a9dedf3b7ac8867ed7d5dabcde39bc39c77ab5a909176a` | `public.ecr.aws/d3j8x8q7/swe-bench-202605:kh7f7cahc5ddm1qzpxz13kpmrh8235pc-v1.1` | `sha256:443a3534dab64283e5a9dedf3b7ac8867ed7d5dabcde39bc39c77ab5a909176a` |
| deep-swe | fd-deterministic-multi-key-sorting | `public.ecr.aws/d3j8x8q7/swe-bench-202605@sha256:31c4201bbe4b79457ab34494b84767d417926e1cf9e8e24ac7d44d9a8e4bc538` | `public.ecr.aws/d3j8x8q7/swe-bench-202605:kh79s1ny2ab454f8caet44rv5n82za06-v1.1` | `sha256:31c4201bbe4b79457ab34494b84767d417926e1cf9e8e24ac7d44d9a8e4bc538` |
| deep-swe | updo-policy-alerting | `public.ecr.aws/d3j8x8q7/swe-bench-202605@sha256:91b20a45b0445cf1bb97a96b9749c2caad0c4747de538c6df700c48e1a88cf54` | `public.ecr.aws/d3j8x8q7/swe-bench-202605:kh7dk7mmh6ewnyc9h46wyag19d831gmy-v1.1` | `sha256:91b20a45b0445cf1bb97a96b9749c2caad0c4747de538c6df700c48e1a88cf54` |
| deep-swe | go-critic-doc-link-checker | `public.ecr.aws/d3j8x8q7/swe-bench-202605@sha256:f4388c446f0c29f48f5d43cebefff6e72af1121d3ce4d1e12404e77a2a455437` | `public.ecr.aws/d3j8x8q7/swe-bench-202605:kh727w7pxd9cv476t3cxptxcg182e1e5-v1.1` | `sha256:f4388c446f0c29f48f5d43cebefff6e72af1121d3ce4d1e12404e77a2a455437` |
| deep-swe | bandit-structured-nosec-directives | `public.ecr.aws/d3j8x8q7/swe-bench-202605@sha256:2f6978cf88228baa0d3323e4f139ee222f5886218d86ca1d327bcae3711f4b6a` | `public.ecr.aws/d3j8x8q7/swe-bench-202605:kh757d8ggvnfaszv8zcav3msy982ma7f-v1.1` | `sha256:2f6978cf88228baa0d3323e4f139ee222f5886218d86ca1d327bcae3711f4b6a` |
| deep-swe | dateutil-rfc5545-timezone-interop | `public.ecr.aws/d3j8x8q7/swe-bench-202605@sha256:ac1167c4badd5db3e8058572e4ae9f09c391a7a6c6801b46ce7f7b12d8c6b77f` | `public.ecr.aws/d3j8x8q7/swe-bench-202605:kh7czqrrmrm1vnwfx1nhtjh9as833esn-v1.1` | `sha256:ac1167c4badd5db3e8058572e4ae9f09c391a7a6c6801b46ce7f7b12d8c6b77f` |
| deep-swe | ink-grid-box-layout | `public.ecr.aws/d3j8x8q7/swe-bench-202605@sha256:c50fcbacd80c6e4b42e18fedf0f8f4bcb2c591ef9a04e4dba39e588e095d4b8e` | `public.ecr.aws/d3j8x8q7/swe-bench-202605:kh75wxkjyha9441e7m9tpetb2582mn63-v1.1` | `sha256:c50fcbacd80c6e4b42e18fedf0f8f4bcb2c591ef9a04e4dba39e588e095d4b8e` |
| deep-swe | narwhals-rolling-window-suite | `public.ecr.aws/d3j8x8q7/swe-bench-202605@sha256:a94da0d6a13d23612acec72b399ae93baf72b875a354f05d3613ed6b552be2c1` | `public.ecr.aws/d3j8x8q7/swe-bench-202605:kh7987m8hz4g19ngkk2zfe3v4n82y0e2-v1.1` | `sha256:a94da0d6a13d23612acec72b399ae93baf72b875a354f05d3613ed6b552be2c1` |
| deep-swe | task-task-graph-export | `public.ecr.aws/d3j8x8q7/swe-bench-202605@sha256:9fc864fa050dc1140c0064096f8df4e06d24c544aa5c056e3adf084fbcfe8287` | `public.ecr.aws/d3j8x8q7/swe-bench-202605:kh7ejvdhks3x059j6jwfncaj4982yxrv-v1.1` | `sha256:9fc864fa050dc1140c0064096f8df4e06d24c544aa5c056e3adf084fbcfe8287` |
| deep-swe | prometheus-typed-label-sorting | `public.ecr.aws/d3j8x8q7/swe-bench-202605@sha256:3139157bed16d3b4e0ecc15f9e0bead0b4f95d3beb7ffae37eeb3cb05c50cd95` | `public.ecr.aws/d3j8x8q7/swe-bench-202605:kh76dadw64v8013j689380xsg182yhfc-v1.1` | `sha256:3139157bed16d3b4e0ecc15f9e0bead0b4f95d3beb7ffae37eeb3cb05c50cd95` |
| deep-swe | termenv-preserve-ansi-resets | `public.ecr.aws/d3j8x8q7/swe-bench-202605@sha256:555ed2efa5299b9e67a3d2ab0e443f6569dde695bffaac8a7f514b7de471e3b2` | `public.ecr.aws/d3j8x8q7/swe-bench-202605:kh731cskx45z0t0961464d9ezx8220nt-v1.1` | `sha256:555ed2efa5299b9e67a3d2ab0e443f6569dde695bffaac8a7f514b7de471e3b2` |
| deep-swe | pest-character-class-coalescing | `public.ecr.aws/d3j8x8q7/swe-bench-202605@sha256:3147fd9b5a532ba679ac2c933ddf16e7ade6f32ddcf3b2d93576f243be3bd6af` | `public.ecr.aws/d3j8x8q7/swe-bench-202605:kh7bmp04pqht2pcvp8qce1afm582ph2j-v1.1` | `sha256:3147fd9b5a532ba679ac2c933ddf16e7ade6f32ddcf3b2d93576f243be3bd6af` |
| deep-swe | etree-xml-diff-patch | `public.ecr.aws/d3j8x8q7/swe-bench-202605@sha256:e057fb0080708ee7a527b9c2d1d55351f602126d35eecb595d506b1aa52581d3` | `public.ecr.aws/d3j8x8q7/swe-bench-202605:kh7e0e2z02keqh6j7db6bcg1c9822140-v1.1` | `sha256:e057fb0080708ee7a527b9c2d1d55351f602126d35eecb595d506b1aa52581d3` |
| deep-swe | meriyah-explicit-resource-declarations | `public.ecr.aws/d3j8x8q7/swe-bench-202605@sha256:43ce618452b29610b682ea77e384dcb8c57308957a7eb65734a47d76a7ff47dc` | `public.ecr.aws/d3j8x8q7/swe-bench-202605:kh7398skqnxqwg9hbmdj7ncmk1822aa0-v1.1` | `sha256:43ce618452b29610b682ea77e384dcb8c57308957a7eb65734a47d76a7ff47dc` |
| deep-swe | happy-dom-deterministic-intersectionobserver | `public.ecr.aws/d3j8x8q7/swe-bench-202605@sha256:7133a09f0c5b4e9325b433e0fac31edc4946deff425dad755569dc21f41394f0` | `public.ecr.aws/d3j8x8q7/swe-bench-202605:kh75ggdejhnymjbhkbtkxvhz758352br-v1.1` | `sha256:7133a09f0c5b4e9325b433e0fac31edc4946deff425dad755569dc21f41394f0` |
| deep-swe | tengo-destructuring-bindings | `public.ecr.aws/d3j8x8q7/swe-bench-202605@sha256:4ef42ab32e07164ff16f4af59da104016a605cf436c6fde1be8c68745740582f` | `public.ecr.aws/d3j8x8q7/swe-bench-202605:kh7ajwvesks1d5kkpeqx7y79sd8238zn-v1.1` | `sha256:4ef42ab32e07164ff16f4af59da104016a605cf436c6fde1be8c68745740582f` |
| deep-swe | returns-validated-error-accumulation | `public.ecr.aws/d3j8x8q7/swe-bench-202605@sha256:f1a88a58920be20192034003a6711a2dfd952bad72207b98e16f5f47f2377287` | `public.ecr.aws/d3j8x8q7/swe-bench-202605:kh754n098chwgtm24jakheqsw5833ec6-v1.1` | `sha256:f1a88a58920be20192034003a6711a2dfd952bad72207b98e16f5f47f2377287` |
| deep-swe | mashumaro-flattened-dataclass-fields | `public.ecr.aws/d3j8x8q7/swe-bench-202605@sha256:507c94460ec7003fe7c54f5ed9bae4a0e6b20f0b4ba925926a81a010e62b76fd` | `public.ecr.aws/d3j8x8q7/swe-bench-202605:kh70k6aj3y457hgtraar0rmgdn822qx8-v1.1` | `sha256:507c94460ec7003fe7c54f5ed9bae4a0e6b20f0b4ba925926a81a010e62b76fd` |
| deep-swe | ts-pattern-match-each | `public.ecr.aws/d3j8x8q7/swe-bench-202605@sha256:4c4584bdfdbd898b90f3c1c011236056bc9ed82319680cca865fd9f2ca1a5126` | `public.ecr.aws/d3j8x8q7/swe-bench-202605:kh724kgmvy32trvakc1q6a6sa583fdx7-v1.1` | `sha256:4c4584bdfdbd898b90f3c1c011236056bc9ed82319680cca865fd9f2ca1a5126` |
| deep-swe | python-statemachine-state-data-scoping | `public.ecr.aws/d3j8x8q7/swe-bench-202605@sha256:06309d9ef75ee48bc5aa98258af57a6d102057983871513b5de91d6a9ead0f9a` | `public.ecr.aws/d3j8x8q7/swe-bench-202605:kh719np6e210pf8skawv132rw183pfyy-v1.1` | `sha256:06309d9ef75ee48bc5aa98258af57a6d102057983871513b5de91d6a9ead0f9a` |
| deep-swe | true-myth-iterable-collection-combinators | `public.ecr.aws/d3j8x8q7/swe-bench-202605@sha256:7bdf0b71ad1b632b8be3f8befe0a5a584d2f185c154ba4fe7d3bbf2a6871d72b` | `public.ecr.aws/d3j8x8q7/swe-bench-202605:kh74r2t7kdnt7h2efdk0hf5asx82zr0s-v1.1` | `sha256:7bdf0b71ad1b632b8be3f8befe0a5a584d2f185c154ba4fe7d3bbf2a6871d72b` |
| deep-swe | helm-unified-manifest-stream | `public.ecr.aws/d3j8x8q7/swe-bench-202605@sha256:b6915c6766cbfd2a26301adcb79bcb49a0c84bbff4039920378c9ff854c48d2c` | `public.ecr.aws/d3j8x8q7/swe-bench-202605:kh7dvkse99x41x83c5z6f2eq7n82w8fm-v1.1` | `sha256:b6915c6766cbfd2a26301adcb79bcb49a0c84bbff4039920378c9ff854c48d2c` |
| deep-swe | skrub-duration-encoding | `public.ecr.aws/d3j8x8q7/swe-bench-202605@sha256:53c898620ea0fb580b17c4552f57f2eddf11e4fac7ca90189b75695cee3064a5` | `public.ecr.aws/d3j8x8q7/swe-bench-202605:kh77y2107s6xkqyf61mj1dsm0983kmp1-v1.1` | `sha256:53c898620ea0fb580b17c4552f57f2eddf11e4fac7ca90189b75695cee3064a5` |
| deep-swe | sqlfmt-create-table-ddl-formatting | `public.ecr.aws/d3j8x8q7/swe-bench-202605@sha256:f09016a93979391f413ea87a6dff4dc90b813c455282fd9d60d994eaa093e0a8` | `public.ecr.aws/d3j8x8q7/swe-bench-202605:kh71t2fb7qvx4y0svvv77e5p3182hnvq-v1.1` | `sha256:f09016a93979391f413ea87a6dff4dc90b813c455282fd9d60d994eaa093e0a8` |
| deep-swe | anko-default-function-arguments | `public.ecr.aws/d3j8x8q7/swe-bench-202605@sha256:31c8dce39317314800d1200610475ba27b98c71350d524d25e7df71d80c5752a` | `public.ecr.aws/d3j8x8q7/swe-bench-202605:kh7fj3hc92zehtc8azrm32xzb182w9dr-v1.1` | `sha256:31c8dce39317314800d1200610475ba27b98c71350d524d25e7df71d80c5752a` |
| deep-swe | csstree-shorthand-expansion-compression | `public.ecr.aws/d3j8x8q7/swe-bench-202605@sha256:df2cc59d679c908f8f13f68fc59231a5d6f0c2bcec4b7b26fdf9489eb824a8b2` | `public.ecr.aws/d3j8x8q7/swe-bench-202605:kh72qraccnjwdet6ynagsccr4x82y65c-v1.1` | `sha256:df2cc59d679c908f8f13f68fc59231a5d6f0c2bcec4b7b26fdf9489eb824a8b2` |
| deep-swe | tengo-callable-instance-isolation | `public.ecr.aws/d3j8x8q7/swe-bench-202605@sha256:4ef42ab32e07164ff16f4af59da104016a605cf436c6fde1be8c68745740582f` | `public.ecr.aws/d3j8x8q7/swe-bench-202605:kh77n9t7ybdq9387d08jzdp1y183ffe6-v1.1` | `sha256:4ef42ab32e07164ff16f4af59da104016a605cf436c6fde1be8c68745740582f` |
| deep-swe | tomlkit-toml-table-converters | `public.ecr.aws/d3j8x8q7/swe-bench-202605@sha256:0785d2c9caa62130352713828a2a98f85b991f87fa853bad7252546df9ff0eec` | `public.ecr.aws/d3j8x8q7/swe-bench-202605:kh7ezsk4ze1jyjta967ypwnxhh83etpm-v1.1` | `sha256:0785d2c9caa62130352713828a2a98f85b991f87fa853bad7252546df9ff0eec` |
| deep-swe | obsidian-linter-scoped-ignore-markers | `public.ecr.aws/d3j8x8q7/swe-bench-202605@sha256:5522ad4d38ef3cd0163dfd1f584dcafd197b914ddf56816d0a88941067657d67` | `public.ecr.aws/d3j8x8q7/swe-bench-202605:kh7fmf1y6r9ajpg3htmaj237h182vztd-v1.1` | `sha256:5522ad4d38ef3cd0163dfd1f584dcafd197b914ddf56816d0a88941067657d67` |
| deep-swe | helm-array-merge-strategies | `public.ecr.aws/d3j8x8q7/swe-bench-202605@sha256:d8b573f9e37303fb1aeb03efbfbecb84be8ea2dabaefb34f09b66bb6f6c13721` | `public.ecr.aws/d3j8x8q7/swe-bench-202605:kh72a3qcr0kjpdr153havavn8s83bx8t-v1.1` | `sha256:d8b573f9e37303fb1aeb03efbfbecb84be8ea2dabaefb34f09b66bb6f6c13721` |
| terminal-bench | constraints-scheduling | `alexgshaw/constraints-scheduling@sha256:567ce5a189f8d11ac461790876e934cc7af38391baf89a78f95f4dafc1fec3b0` | `alexgshaw/constraints-scheduling:20251031` | `sha256:567ce5a189f8d11ac461790876e934cc7af38391baf89a78f95f4dafc1fec3b0` |
| terminal-bench | sqlite-db-truncate | `alexgshaw/sqlite-db-truncate@sha256:aabac93c93bd1f310e6a6fb893911d7735026ed18491c72133c9196a09092ca4` | `alexgshaw/sqlite-db-truncate:20251031` | `sha256:aabac93c93bd1f310e6a6fb893911d7735026ed18491c72133c9196a09092ca4` |
| terminal-bench | vulnerable-secret | `alexgshaw/vulnerable-secret@sha256:61ebb40454dd103aa2f7e71ad6dafd91cf2b301e6bb07e69d5b472412d1ee15b` | `alexgshaw/vulnerable-secret:20251031` | `sha256:61ebb40454dd103aa2f7e71ad6dafd91cf2b301e6bb07e69d5b472412d1ee15b` |
| terminal-bench | bn-fit-modify | `alexgshaw/bn-fit-modify@sha256:5aeb11ca6e802b83816c9a31f055ac9d028309a853509400c2e3139ac2d8380d` | `alexgshaw/bn-fit-modify:20251031` | `sha256:5aeb11ca6e802b83816c9a31f055ac9d028309a853509400c2e3139ac2d8380d` |
| terminal-bench | cancel-async-tasks | `alexgshaw/cancel-async-tasks@sha256:84c7fae6b256dcc56a350790e2a9715eefc7dad662a9d8e8a472363aa71ef18d` | `alexgshaw/cancel-async-tasks:20251031` | `sha256:84c7fae6b256dcc56a350790e2a9715eefc7dad662a9d8e8a472363aa71ef18d` |
| terminal-bench | chess-best-move | `alexgshaw/chess-best-move@sha256:bb447f94d9e2a8ed879f85c85a514b213b7418f9fe11fd7b2428a0b0e436e647` | `alexgshaw/chess-best-move:20251031` | `sha256:bb447f94d9e2a8ed879f85c85a514b213b7418f9fe11fd7b2428a0b0e436e647` |
| terminal-bench | code-from-image | `alexgshaw/code-from-image@sha256:2be9cdb746ed18c1b2b1404032efae0b2235a1b8fc479ef17730c95409d89f76` | `alexgshaw/code-from-image:20251031` | `sha256:2be9cdb746ed18c1b2b1404032efae0b2235a1b8fc479ef17730c95409d89f76` |
| terminal-bench | count-dataset-tokens | `alexgshaw/count-dataset-tokens@sha256:9c513c4ba342bd95be501f6f5eadd4806a2b18749c87c251615825100130232d` | `alexgshaw/count-dataset-tokens:20251031` | `sha256:9c513c4ba342bd95be501f6f5eadd4806a2b18749c87c251615825100130232d` |
| terminal-bench | crack-7z-hash | `alexgshaw/crack-7z-hash@sha256:0f4453abd774c5a3d3d7e66ba28fae88ec2e49ada3a993b324ebc16c348666d3` | `alexgshaw/crack-7z-hash:20251031` | `sha256:0f4453abd774c5a3d3d7e66ba28fae88ec2e49ada3a993b324ebc16c348666d3` |
| terminal-bench | db-wal-recovery | `alexgshaw/db-wal-recovery@sha256:0e33ea5ec823975d1bd6c3778395c9f94251dd88f571146057bff6adb7e4594e` | `alexgshaw/db-wal-recovery:20251031` | `sha256:0e33ea5ec823975d1bd6c3778395c9f94251dd88f571146057bff6adb7e4594e` |
| terminal-bench | distribution-search | `alexgshaw/distribution-search@sha256:1448f7aa1c6080488251d00350e8e90477858989b1bec0accc866d7b3220738a` | `alexgshaw/distribution-search:20251031` | `sha256:1448f7aa1c6080488251d00350e8e90477858989b1bec0accc866d7b3220738a` |
| terminal-bench | dna-assembly | `alexgshaw/dna-assembly@sha256:d1adf6835f1dd91205ba70e452c699d0aea601010038e5617f370716efb50569` | `alexgshaw/dna-assembly:20251031` | `sha256:d1adf6835f1dd91205ba70e452c699d0aea601010038e5617f370716efb50569` |
| terminal-bench | dna-insert | `alexgshaw/dna-insert@sha256:4dd8760694e355de85ecf03605cb487ccdb33322f6afad513d2920829baa33b2` | `alexgshaw/dna-insert:20251031` | `sha256:4dd8760694e355de85ecf03605cb487ccdb33322f6afad513d2920829baa33b2` |
| terminal-bench | extract-moves-from-video | `alexgshaw/extract-moves-from-video@sha256:14a9dcca7d08ce53c5a0ed9fbd663a996ef28f207c199ed69d9ccf6064f8b184` | `alexgshaw/extract-moves-from-video:20251031` | `sha256:14a9dcca7d08ce53c5a0ed9fbd663a996ef28f207c199ed69d9ccf6064f8b184` |
| terminal-bench | feal-linear-cryptanalysis | `alexgshaw/feal-linear-cryptanalysis@sha256:ea78749a8422c6228d26c8753f45906a6a2df089906764b7e3c3e27e8f718ee7` | `alexgshaw/feal-linear-cryptanalysis:20251031` | `sha256:ea78749a8422c6228d26c8753f45906a6a2df089906764b7e3c3e27e8f718ee7` |
| terminal-bench | financial-document-processor | `alexgshaw/financial-document-processor@sha256:ef6c9cfaaf14cdd200163008a188d5baa9f626f3bfb8d3e7d6f30c08518e6251` | `alexgshaw/financial-document-processor:20251031` | `sha256:ef6c9cfaaf14cdd200163008a188d5baa9f626f3bfb8d3e7d6f30c08518e6251` |
| terminal-bench | fix-git | `alexgshaw/fix-git@sha256:61e431c00c58df652287aadce5457634d9f9330cfdd153ebdf2802df0d540119` | `alexgshaw/fix-git:20251031` | `sha256:61e431c00c58df652287aadce5457634d9f9330cfdd153ebdf2802df0d540119` |
| terminal-bench | gcode-to-text | `alexgshaw/gcode-to-text@sha256:0979ef40c6a3e8c4e7ab5b6c2524c74625a84799e15cd45dd98dcf83b11efd4d` | `alexgshaw/gcode-to-text:20251031` | `sha256:0979ef40c6a3e8c4e7ab5b6c2524c74625a84799e15cd45dd98dcf83b11efd4d` |
| terminal-bench | git-leak-recovery | `alexgshaw/git-leak-recovery@sha256:62160e522a4238b8bcd522411ea97b5b200f811e5899d34947e66809bef7e586` | `alexgshaw/git-leak-recovery:20251031` | `sha256:62160e522a4238b8bcd522411ea97b5b200f811e5899d34947e66809bef7e586` |
| terminal-bench | gpt2-codegolf | `alexgshaw/gpt2-codegolf@sha256:537e7bd26b02db5c761230515fa09dc05f89403c6737fbdae4b5793ebc2c7066` | `alexgshaw/gpt2-codegolf:20251031` | `sha256:537e7bd26b02db5c761230515fa09dc05f89403c6737fbdae4b5793ebc2c7066` |
| terminal-bench | headless-terminal | `alexgshaw/headless-terminal@sha256:eb7e209672bf6cef2785fafd9e13509b10626c327bcc2b37f5bf40ca83eaf3aa` | `alexgshaw/headless-terminal:20251031` | `sha256:eb7e209672bf6cef2785fafd9e13509b10626c327bcc2b37f5bf40ca83eaf3aa` |
| terminal-bench | hf-model-inference | `alexgshaw/hf-model-inference@sha256:f96dd7d3c85c7257b404fd63ba8d24ced2478cd90232c20e297c372f953fa607` | `alexgshaw/hf-model-inference:20251031` | `sha256:f96dd7d3c85c7257b404fd63ba8d24ced2478cd90232c20e297c372f953fa607` |
| terminal-bench | kv-store-grpc | `alexgshaw/kv-store-grpc@sha256:3399400800dcb207634daa42bc1b052e831e285cc9d221eea66c47bc0fc79791` | `alexgshaw/kv-store-grpc:20251031` | `sha256:3399400800dcb207634daa42bc1b052e831e285cc9d221eea66c47bc0fc79791` |
| terminal-bench | log-summary-date-ranges | `alexgshaw/log-summary-date-ranges@sha256:cbeb6ba905c2fec294f16cd5e16e3ea7f2e04d38ac2484d51a11de262aa7dc51` | `alexgshaw/log-summary-date-ranges:20251031` | `sha256:cbeb6ba905c2fec294f16cd5e16e3ea7f2e04d38ac2484d51a11de262aa7dc51` |
| terminal-bench | raman-fitting | `alexgshaw/raman-fitting@sha256:401fa95d5d491f44a473eda9d2c52930f9565cc889c796eabcb6e20fec26852e` | `alexgshaw/raman-fitting:20251031` | `sha256:401fa95d5d491f44a473eda9d2c52930f9565cc889c796eabcb6e20fec26852e` |
| terminal-bench | protein-assembly | `alexgshaw/protein-assembly@sha256:94de701b57e7ecfdbada6044f8534876e4b58874f8f313184dadc4d7533e0818` | `alexgshaw/protein-assembly:20251031` | `sha256:94de701b57e7ecfdbada6044f8534876e4b58874f8f313184dadc4d7533e0818` |
| terminal-bench | write-compressor | `alexgshaw/write-compressor@sha256:3618e1f8a997b437c09cd3dbaac736705809c05f6f12f584b65722175970ebe1` | `alexgshaw/write-compressor:20251031` | `sha256:3618e1f8a997b437c09cd3dbaac736705809c05f6f12f584b65722175970ebe1` |
| terminal-bench | mteb-leaderboard | `alexgshaw/mteb-leaderboard@sha256:968de9456bfc53728f7df0cb6c9ce33e17bd0e5563ddfe031e6ed2964965aecf` | `alexgshaw/mteb-leaderboard:20251031` | `sha256:968de9456bfc53728f7df0cb6c9ce33e17bd0e5563ddfe031e6ed2964965aecf` |
| terminal-bench | mteb-retrieve | `alexgshaw/mteb-retrieve@sha256:99dd676a21fd3124b7b8164cd93e8f0c51f1fdab2f84a831c61049eff78d063d` | `alexgshaw/mteb-retrieve:20251031` | `sha256:99dd676a21fd3124b7b8164cd93e8f0c51f1fdab2f84a831c61049eff78d063d` |
| terminal-bench | rstan-to-pystan | `alexgshaw/rstan-to-pystan@sha256:b23d48839408524326095c15ada4145c772b87646cf299022ff1f58c97baba91` | `alexgshaw/rstan-to-pystan:20251031` | `sha256:b23d48839408524326095c15ada4145c772b87646cf299022ff1f58c97baba91` |

## Per-task limits

From `configs/resources.csv` (upstream task.toml vs the SecureBench config):

```csv
pack,task,upstream_agent_timeout_s,securebench_row_timeout_s,effective_securebench_timeout_s,upstream_verifier_timeout_s,upstream_cpus,securebench_cpus,upstream_memory_mb,securebench_memory,upstream_verifier_cpus,upstream_verifier_memory_mb,upstream_agent_network,securebench_agent_network,upstream_storage_mb,securebench_capture_cap_bytes,upstream_image,securebench_image
deep-swe,cattrs-partial-structuring-recovery,5400.0,5400.0,5400.0,1800.0,2,unlimited,8192,8192m,2,8192,no-network,"""none""",20480,,public.ecr.aws/d3j8x8q7/swe-bench-202605:kh7f7cahc5ddm1qzpxz13kpmrh8235pc-v1.1,public.ecr.aws/d3j8x8q7/swe-bench-202605@sha256:443a3534dab64283e5a9dedf3b7ac8867ed7d5dabcde39bc39c77ab5a909176a
deep-swe,fd-deterministic-multi-key-sorting,5400.0,5400.0,5400.0,1800.0,2,unlimited,8192,8192m,2,8192,no-network,"""none""",20480,,public.ecr.aws/d3j8x8q7/swe-bench-202605:kh79s1ny2ab454f8caet44rv5n82za06-v1.1,public.ecr.aws/d3j8x8q7/swe-bench-202605@sha256:31c4201bbe4b79457ab34494b84767d417926e1cf9e8e24ac7d44d9a8e4bc538
deep-swe,updo-policy-alerting,5400.0,5400.0,5400.0,1800.0,2,unlimited,8192,8192m,2,8192,no-network,"""none""",20480,,public.ecr.aws/d3j8x8q7/swe-bench-202605:kh7dk7mmh6ewnyc9h46wyag19d831gmy-v1.1,public.ecr.aws/d3j8x8q7/swe-bench-202605@sha256:91b20a45b0445cf1bb97a96b9749c2caad0c4747de538c6df700c48e1a88cf54
deep-swe,go-critic-doc-link-checker,5400.0,5400.0,5400.0,1800.0,2,unlimited,8192,8192m,2,8192,no-network,"""none""",20480,,public.ecr.aws/d3j8x8q7/swe-bench-202605:kh727w7pxd9cv476t3cxptxcg182e1e5-v1.1,public.ecr.aws/d3j8x8q7/swe-bench-202605@sha256:f4388c446f0c29f48f5d43cebefff6e72af1121d3ce4d1e12404e77a2a455437
deep-swe,bandit-structured-nosec-directives,5400.0,5400.0,5400.0,1800.0,2,unlimited,8192,8192m,2,8192,no-network,"""none""",20480,,public.ecr.aws/d3j8x8q7/swe-bench-202605:kh757d8ggvnfaszv8zcav3msy982ma7f-v1.1,public.ecr.aws/d3j8x8q7/swe-bench-202605@sha256:2f6978cf88228baa0d3323e4f139ee222f5886218d86ca1d327bcae3711f4b6a
deep-swe,dateutil-rfc5545-timezone-interop,5400.0,5400.0,5400.0,1800.0,2,unlimited,8192,8192m,2,8192,no-network,"""none""",20480,,public.ecr.aws/d3j8x8q7/swe-bench-202605:kh7czqrrmrm1vnwfx1nhtjh9as833esn-v1.1,public.ecr.aws/d3j8x8q7/swe-bench-202605@sha256:ac1167c4badd5db3e8058572e4ae9f09c391a7a6c6801b46ce7f7b12d8c6b77f
deep-swe,ink-grid-box-layout,5400.0,5400.0,5400.0,1800.0,2,unlimited,8192,8192m,2,8192,no-network,"""none""",20480,,public.ecr.aws/d3j8x8q7/swe-bench-202605:kh75wxkjyha9441e7m9tpetb2582mn63-v1.1,public.ecr.aws/d3j8x8q7/swe-bench-202605@sha256:c50fcbacd80c6e4b42e18fedf0f8f4bcb2c591ef9a04e4dba39e588e095d4b8e
deep-swe,narwhals-rolling-window-suite,5400.0,5400.0,5400.0,1800.0,2,unlimited,8192,8192m,2,8192,no-network,"""none""",20480,,public.ecr.aws/d3j8x8q7/swe-bench-202605:kh7987m8hz4g19ngkk2zfe3v4n82y0e2-v1.1,public.ecr.aws/d3j8x8q7/swe-bench-202605@sha256:a94da0d6a13d23612acec72b399ae93baf72b875a354f05d3613ed6b552be2c1
deep-swe,task-task-graph-export,5400.0,5400.0,5400.0,1800.0,2,unlimited,8192,8192m,2,8192,no-network,"""none""",20480,,public.ecr.aws/d3j8x8q7/swe-bench-202605:kh7ejvdhks3x059j6jwfncaj4982yxrv-v1.1,public.ecr.aws/d3j8x8q7/swe-bench-202605@sha256:9fc864fa050dc1140c0064096f8df4e06d24c544aa5c056e3adf084fbcfe8287
deep-swe,prometheus-typed-label-sorting,5400.0,5400.0,5400.0,1800.0,2,unlimited,8192,8192m,2,8192,no-network,"{""allowed_domains"": [], ""mode"": ""none""}",20480,,public.ecr.aws/d3j8x8q7/swe-bench-202605:kh76dadw64v8013j689380xsg182yhfc-v1.1,public.ecr.aws/d3j8x8q7/swe-bench-202605@sha256:3139157bed16d3b4e0ecc15f9e0bead0b4f95d3beb7ffae37eeb3cb05c50cd95
deep-swe,termenv-preserve-ansi-resets,5400.0,5400.0,5400.0,1800.0,2,unlimited,8192,8192m,2,8192,no-network,"""none""",20480,,public.ecr.aws/d3j8x8q7/swe-bench-202605:kh731cskx45z0t0961464d9ezx8220nt-v1.1,public.ecr.aws/d3j8x8q7/swe-bench-202605@sha256:555ed2efa5299b9e67a3d2ab0e443f6569dde695bffaac8a7f514b7de471e3b2
deep-swe,pest-character-class-coalescing,5400.0,5400.0,5400.0,1800.0,2,unlimited,8192,8192m,2,8192,no-network,"""none""",20480,,public.ecr.aws/d3j8x8q7/swe-bench-202605:kh7bmp04pqht2pcvp8qce1afm582ph2j-v1.1,public.ecr.aws/d3j8x8q7/swe-bench-202605@sha256:3147fd9b5a532ba679ac2c933ddf16e7ade6f32ddcf3b2d93576f243be3bd6af
deep-swe,etree-xml-diff-patch,5400.0,5400.0,5400.0,1800.0,2,unlimited,8192,8192m,2,8192,no-network,"""none""",20480,,public.ecr.aws/d3j8x8q7/swe-bench-202605:kh7e0e2z02keqh6j7db6bcg1c9822140-v1.1,public.ecr.aws/d3j8x8q7/swe-bench-202605@sha256:e057fb0080708ee7a527b9c2d1d55351f602126d35eecb595d506b1aa52581d3
deep-swe,meriyah-explicit-resource-declarations,5400.0,5400.0,5400.0,1800.0,2,unlimited,8192,8192m,2,8192,no-network,"""none""",20480,,public.ecr.aws/d3j8x8q7/swe-bench-202605:kh7398skqnxqwg9hbmdj7ncmk1822aa0-v1.1,public.ecr.aws/d3j8x8q7/swe-bench-202605@sha256:43ce618452b29610b682ea77e384dcb8c57308957a7eb65734a47d76a7ff47dc
deep-swe,happy-dom-deterministic-intersectionobserver,5400.0,5400.0,5400.0,1800.0,2,unlimited,8192,8192m,2,8192,no-network,"""none""",20480,,public.ecr.aws/d3j8x8q7/swe-bench-202605:kh75ggdejhnymjbhkbtkxvhz758352br-v1.1,public.ecr.aws/d3j8x8q7/swe-bench-202605@sha256:7133a09f0c5b4e9325b433e0fac31edc4946deff425dad755569dc21f41394f0
deep-swe,tengo-destructuring-bindings,5400.0,5400.0,5400.0,1800.0,2,unlimited,8192,8192m,2,8192,no-network,"""none""",20480,,public.ecr.aws/d3j8x8q7/swe-bench-202605:kh7ajwvesks1d5kkpeqx7y79sd8238zn-v1.1,public.ecr.aws/d3j8x8q7/swe-bench-202605@sha256:4ef42ab32e07164ff16f4af59da104016a605cf436c6fde1be8c68745740582f
deep-swe,returns-validated-error-accumulation,5400.0,5400.0,5400.0,1800.0,2,unlimited,8192,8192m,2,8192,no-network,"""none""",20480,,public.ecr.aws/d3j8x8q7/swe-bench-202605:kh754n098chwgtm24jakheqsw5833ec6-v1.1,public.ecr.aws/d3j8x8q7/swe-bench-202605@sha256:f1a88a58920be20192034003a6711a2dfd952bad72207b98e16f5f47f2377287
deep-swe,mashumaro-flattened-dataclass-fields,5400.0,5400.0,5400.0,1800.0,2,unlimited,8192,8192m,2,8192,no-network,"{""allowed_domains"": [], ""mode"": ""none""}",20480,,public.ecr.aws/d3j8x8q7/swe-bench-202605:kh70k6aj3y457hgtraar0rmgdn822qx8-v1.1,public.ecr.aws/d3j8x8q7/swe-bench-202605@sha256:507c94460ec7003fe7c54f5ed9bae4a0e6b20f0b4ba925926a81a010e62b76fd
deep-swe,ts-pattern-match-each,5400.0,5400.0,5400.0,1800.0,2,unlimited,8192,8192m,2,8192,no-network,"""none""",20480,,public.ecr.aws/d3j8x8q7/swe-bench-202605:kh724kgmvy32trvakc1q6a6sa583fdx7-v1.1,public.ecr.aws/d3j8x8q7/swe-bench-202605@sha256:4c4584bdfdbd898b90f3c1c011236056bc9ed82319680cca865fd9f2ca1a5126
deep-swe,python-statemachine-state-data-scoping,5400.0,5400.0,5400.0,1800.0,2,unlimited,8192,8192m,2,8192,no-network,"{""allowed_domains"": [], ""mode"": ""none""}",20480,,public.ecr.aws/d3j8x8q7/swe-bench-202605:kh719np6e210pf8skawv132rw183pfyy-v1.1,public.ecr.aws/d3j8x8q7/swe-bench-202605@sha256:06309d9ef75ee48bc5aa98258af57a6d102057983871513b5de91d6a9ead0f9a
deep-swe,true-myth-iterable-collection-combinators,5400.0,5400.0,5400.0,1800.0,2,unlimited,8192,8192m,2,8192,no-network,"""none""",20480,,public.ecr.aws/d3j8x8q7/swe-bench-202605:kh74r2t7kdnt7h2efdk0hf5asx82zr0s-v1.1,public.ecr.aws/d3j8x8q7/swe-bench-202605@sha256:7bdf0b71ad1b632b8be3f8befe0a5a584d2f185c154ba4fe7d3bbf2a6871d72b
deep-swe,helm-unified-manifest-stream,5400.0,5400.0,5400.0,1800.0,2,unlimited,8192,8192m,2,8192,no-network,"""none""",20480,,public.ecr.aws/d3j8x8q7/swe-bench-202605:kh7dvkse99x41x83c5z6f2eq7n82w8fm-v1.1,public.ecr.aws/d3j8x8q7/swe-bench-202605@sha256:b6915c6766cbfd2a26301adcb79bcb49a0c84bbff4039920378c9ff854c48d2c
deep-swe,skrub-duration-encoding,5400.0,5400.0,5400.0,1800.0,2,unlimited,8192,8192m,2,8192,no-network,"""none""",20480,,public.ecr.aws/d3j8x8q7/swe-bench-202605:kh77y2107s6xkqyf61mj1dsm0983kmp1-v1.1,public.ecr.aws/d3j8x8q7/swe-bench-202605@sha256:53c898620ea0fb580b17c4552f57f2eddf11e4fac7ca90189b75695cee3064a5
deep-swe,sqlfmt-create-table-ddl-formatting,5400.0,5400.0,5400.0,1800.0,2,unlimited,8192,8192m,2,8192,no-network,"{""allowed_domains"": [], ""mode"": ""none""}",20480,,public.ecr.aws/d3j8x8q7/swe-bench-202605:kh71t2fb7qvx4y0svvv77e5p3182hnvq-v1.1,public.ecr.aws/d3j8x8q7/swe-bench-202605@sha256:f09016a93979391f413ea87a6dff4dc90b813c455282fd9d60d994eaa093e0a8
deep-swe,anko-default-function-arguments,5400.0,5400.0,5400.0,1800.0,2,unlimited,8192,8192m,2,8192,no-network,"{""allowed_domains"": [], ""mode"": ""none""}",20480,,public.ecr.aws/d3j8x8q7/swe-bench-202605:kh7fj3hc92zehtc8azrm32xzb182w9dr-v1.1,public.ecr.aws/d3j8x8q7/swe-bench-202605@sha256:31c8dce39317314800d1200610475ba27b98c71350d524d25e7df71d80c5752a
deep-swe,csstree-shorthand-expansion-compression,5400.0,5400.0,5400.0,1800.0,2,unlimited,8192,8192m,2,8192,no-network,"""none""",20480,,public.ecr.aws/d3j8x8q7/swe-bench-202605:kh72qraccnjwdet6ynagsccr4x82y65c-v1.1,public.ecr.aws/d3j8x8q7/swe-bench-202605@sha256:df2cc59d679c908f8f13f68fc59231a5d6f0c2bcec4b7b26fdf9489eb824a8b2
deep-swe,tengo-callable-instance-isolation,5400.0,5400.0,5400.0,1800.0,2,unlimited,8192,8192m,2,8192,no-network,"""none""",20480,,public.ecr.aws/d3j8x8q7/swe-bench-202605:kh77n9t7ybdq9387d08jzdp1y183ffe6-v1.1,public.ecr.aws/d3j8x8q7/swe-bench-202605@sha256:4ef42ab32e07164ff16f4af59da104016a605cf436c6fde1be8c68745740582f
deep-swe,tomlkit-toml-table-converters,5400.0,5400.0,5400.0,1800.0,2,unlimited,8192,8192m,2,8192,no-network,"{""allowed_domains"": [], ""mode"": ""none""}",20480,,public.ecr.aws/d3j8x8q7/swe-bench-202605:kh7ezsk4ze1jyjta967ypwnxhh83etpm-v1.1,public.ecr.aws/d3j8x8q7/swe-bench-202605@sha256:0785d2c9caa62130352713828a2a98f85b991f87fa853bad7252546df9ff0eec
deep-swe,obsidian-linter-scoped-ignore-markers,5400.0,5400.0,5400.0,1800.0,2,unlimited,8192,8192m,2,8192,no-network,"""none""",20480,,public.ecr.aws/d3j8x8q7/swe-bench-202605:kh7fmf1y6r9ajpg3htmaj237h182vztd-v1.1,public.ecr.aws/d3j8x8q7/swe-bench-202605@sha256:5522ad4d38ef3cd0163dfd1f584dcafd197b914ddf56816d0a88941067657d67
deep-swe,helm-array-merge-strategies,5400.0,5400.0,5400.0,1800.0,2,unlimited,8192,8192m,2,8192,no-network,"""none""",20480,,public.ecr.aws/d3j8x8q7/swe-bench-202605:kh72a3qcr0kjpdr153havavn8s83bx8t-v1.1,public.ecr.aws/d3j8x8q7/swe-bench-202605@sha256:d8b573f9e37303fb1aeb03efbfbecb84be8ea2dabaefb34f09b66bb6f6c13721
terminal-bench,constraints-scheduling,1200.0,1200.0,1200.0,1200.0,1,unlimited,2048,2048m,1,2048,internet,"{""allowed_domains"": [], ""mode"": ""internet""}",10240,10737418240,alexgshaw/constraints-scheduling:20251031,alexgshaw/constraints-scheduling@sha256:567ce5a189f8d11ac461790876e934cc7af38391baf89a78f95f4dafc1fec3b0
terminal-bench,sqlite-db-truncate,900.0,900.0,900.0,900.0,1,unlimited,2048,2048m,1,2048,internet,"{""allowed_domains"": [], ""mode"": ""internet""}",10240,10737418240,alexgshaw/sqlite-db-truncate:20251031,alexgshaw/sqlite-db-truncate@sha256:aabac93c93bd1f310e6a6fb893911d7735026ed18491c72133c9196a09092ca4
terminal-bench,vulnerable-secret,900.0,1200.0,900.0,900.0,1,unlimited,2048,2048m,1,2048,internet,"{""allowed_domains"": [], ""mode"": ""internet""}",10240,10737418240,alexgshaw/vulnerable-secret:20251031,alexgshaw/vulnerable-secret@sha256:61ebb40454dd103aa2f7e71ad6dafd91cf2b301e6bb07e69d5b472412d1ee15b
terminal-bench,bn-fit-modify,3600.0,3600.0,3600.0,3600.0,1,unlimited,2048,2048m,1,2048,internet,"{""allowed_domains"": [], ""mode"": ""internet""}",10240,10737418240,alexgshaw/bn-fit-modify:20251031,alexgshaw/bn-fit-modify@sha256:5aeb11ca6e802b83816c9a31f055ac9d028309a853509400c2e3139ac2d8380d
terminal-bench,cancel-async-tasks,900.0,900.0,900.0,900.0,1,unlimited,2048,2048m,1,2048,internet,"{""allowed_domains"": [""pypi.org"", ""pythonhosted.org""], ""mode"": ""internet""}",10240,10737418240,alexgshaw/cancel-async-tasks:20251031,alexgshaw/cancel-async-tasks@sha256:84c7fae6b256dcc56a350790e2a9715eefc7dad662a9d8e8a472363aa71ef18d
terminal-bench,chess-best-move,900.0,900.0,900.0,900.0,1,unlimited,2048,2048m,1,2048,internet,"{""allowed_domains"": [], ""mode"": ""internet""}",10240,10737418240,alexgshaw/chess-best-move:20251031,alexgshaw/chess-best-move@sha256:bb447f94d9e2a8ed879f85c85a514b213b7418f9fe11fd7b2428a0b0e436e647
terminal-bench,code-from-image,1200.0,1200.0,1200.0,1200.0,1,unlimited,2048,2048m,1,2048,internet,"{""allowed_domains"": [], ""mode"": ""internet""}",10240,10737418240,alexgshaw/code-from-image:20251031,alexgshaw/code-from-image@sha256:2be9cdb746ed18c1b2b1404032efae0b2235a1b8fc479ef17730c95409d89f76
terminal-bench,count-dataset-tokens,900.0,900.0,900.0,900.0,1,unlimited,2048,2048m,1,2048,internet,"{""allowed_domains"": [""huggingface.co"", ""hf.co"", ""xethub.hf.co"", ""pypi.org"", ""pythonhosted.org""], ""mode"": ""internet""}",10240,10737418240,alexgshaw/count-dataset-tokens:20251031,alexgshaw/count-dataset-tokens@sha256:9c513c4ba342bd95be501f6f5eadd4806a2b18749c87c251615825100130232d
terminal-bench,crack-7z-hash,1800.0,1800.0,1800.0,900.0,1,unlimited,4096,4096m,1,4096,internet,"{""allowed_domains"": [], ""mode"": ""internet""}",10240,10737418240,alexgshaw/crack-7z-hash:20251031,alexgshaw/crack-7z-hash@sha256:0f4453abd774c5a3d3d7e66ba28fae88ec2e49ada3a993b324ebc16c348666d3
terminal-bench,db-wal-recovery,900.0,900.0,900.0,900.0,1,unlimited,2048,2048m,1,2048,internet,"{""allowed_domains"": [], ""mode"": ""internet""}",10240,10737418240,alexgshaw/db-wal-recovery:20251031,alexgshaw/db-wal-recovery@sha256:0e33ea5ec823975d1bd6c3778395c9f94251dd88f571146057bff6adb7e4594e
terminal-bench,distribution-search,3600.0,3600.0,3600.0,3600.0,1,unlimited,2048,2048m,1,2048,internet,"{""allowed_domains"": [], ""mode"": ""internet""}",10240,10737418240,alexgshaw/distribution-search:20251031,alexgshaw/distribution-search@sha256:1448f7aa1c6080488251d00350e8e90477858989b1bec0accc866d7b3220738a
terminal-bench,dna-assembly,1800.0,1800.0,1800.0,1800.0,1,unlimited,2048,2048m,1,2048,internet,"{""allowed_domains"": [], ""mode"": ""internet""}",10240,10737418240,alexgshaw/dna-assembly:20251031,alexgshaw/dna-assembly@sha256:d1adf6835f1dd91205ba70e452c699d0aea601010038e5617f370716efb50569
terminal-bench,dna-insert,1800.0,1800.0,1800.0,1800.0,1,unlimited,4096,4096m,1,4096,internet,"{""allowed_domains"": [], ""mode"": ""internet""}",10240,10737418240,alexgshaw/dna-insert:20251031,alexgshaw/dna-insert@sha256:4dd8760694e355de85ecf03605cb487ccdb33322f6afad513d2920829baa33b2
terminal-bench,extract-moves-from-video,1800.0,1800.0,1800.0,1800.0,1,unlimited,2048,2048m,1,2048,internet,"{""allowed_domains"": [""youtube.com"", ""googlevideo.com"", ""ytimg.com"", ""pypi.org"", ""pythonhosted.org""], ""mode"": ""internet""}",10240,10737418240,alexgshaw/extract-moves-from-video:20251031,alexgshaw/extract-moves-from-video@sha256:14a9dcca7d08ce53c5a0ed9fbd663a996ef28f207c199ed69d9ccf6064f8b184
terminal-bench,feal-linear-cryptanalysis,1800.0,1800.0,1800.0,1800.0,1,unlimited,2048,2048m,1,2048,internet,"{""allowed_domains"": [], ""mode"": ""internet""}",10240,10737418240,alexgshaw/feal-linear-cryptanalysis:20251031,alexgshaw/feal-linear-cryptanalysis@sha256:ea78749a8422c6228d26c8753f45906a6a2df089906764b7e3c3e27e8f718ee7
terminal-bench,financial-document-processor,1200.0,1200.0,1200.0,1200.0,1,unlimited,4096,4096m,1,4096,internet,"{""allowed_domains"": [], ""mode"": ""internet""}",10240,10737418240,alexgshaw/financial-document-processor:20251031,alexgshaw/financial-document-processor@sha256:ef6c9cfaaf14cdd200163008a188d5baa9f626f3bfb8d3e7d6f30c08518e6251
terminal-bench,fix-git,900.0,900.0,900.0,900.0,1,unlimited,2048,2048m,1,2048,internet,"{""allowed_domains"": [], ""mode"": ""internet""}",10240,10737418240,alexgshaw/fix-git:20251031,alexgshaw/fix-git@sha256:61e431c00c58df652287aadce5457634d9f9330cfdd153ebdf2802df0d540119
terminal-bench,gcode-to-text,900.0,900.0,900.0,900.0,1,unlimited,2048,2048m,1,2048,internet,"{""allowed_domains"": [], ""mode"": ""internet""}",10240,10737418240,alexgshaw/gcode-to-text:20251031,alexgshaw/gcode-to-text@sha256:0979ef40c6a3e8c4e7ab5b6c2524c74625a84799e15cd45dd98dcf83b11efd4d
terminal-bench,git-leak-recovery,900.0,900.0,900.0,900.0,1,unlimited,2048,2048m,1,2048,internet,"{""allowed_domains"": [], ""mode"": ""internet""}",10240,10737418240,alexgshaw/git-leak-recovery:20251031,alexgshaw/git-leak-recovery@sha256:62160e522a4238b8bcd522411ea97b5b200f811e5899d34947e66809bef7e586
terminal-bench,gpt2-codegolf,900.0,900.0,900.0,900.0,1,unlimited,8192,8192m,1,8192,internet,"{""allowed_domains"": [], ""mode"": ""internet""}",10240,10737418240,alexgshaw/gpt2-codegolf:20251031,alexgshaw/gpt2-codegolf@sha256:537e7bd26b02db5c761230515fa09dc05f89403c6737fbdae4b5793ebc2c7066
terminal-bench,headless-terminal,900.0,900.0,900.0,900.0,1,unlimited,2048,2048m,1,2048,internet,"{""allowed_domains"": [""pypi.org"", ""pythonhosted.org""], ""mode"": ""internet""}",10240,10737418240,alexgshaw/headless-terminal:20251031,alexgshaw/headless-terminal@sha256:eb7e209672bf6cef2785fafd9e13509b10626c327bcc2b37f5bf40ca83eaf3aa
terminal-bench,hf-model-inference,900.0,900.0,900.0,900.0,1,unlimited,2048,2048m,1,2048,internet,"{""allowed_domains"": [""huggingface.co"", ""hf.co"", ""xethub.hf.co"", ""pypi.org"", ""pythonhosted.org""], ""mode"": ""internet""}",10240,10737418240,alexgshaw/hf-model-inference:20251031,alexgshaw/hf-model-inference@sha256:f96dd7d3c85c7257b404fd63ba8d24ced2478cd90232c20e297c372f953fa607
terminal-bench,kv-store-grpc,900.0,900.0,900.0,900.0,1,unlimited,2048,2048m,1,2048,internet,"{""allowed_domains"": [""pypi.org"", ""pythonhosted.org""], ""mode"": ""internet""}",10240,10737418240,alexgshaw/kv-store-grpc:20251031,alexgshaw/kv-store-grpc@sha256:3399400800dcb207634daa42bc1b052e831e285cc9d221eea66c47bc0fc79791
terminal-bench,log-summary-date-ranges,900.0,900.0,900.0,900.0,1,unlimited,2048,2048m,1,2048,internet,"{""allowed_domains"": [], ""mode"": ""none""}",10240,10737418240,alexgshaw/log-summary-date-ranges:20251031,alexgshaw/log-summary-date-ranges@sha256:cbeb6ba905c2fec294f16cd5e16e3ea7f2e04d38ac2484d51a11de262aa7dc51
terminal-bench,raman-fitting,900.0,900.0,900.0,900.0,1,unlimited,2048,2048m,1,2048,internet,"{""allowed_domains"": [""pypi.org"", ""pythonhosted.org""], ""mode"": ""restricted""}",10240,10737418240,alexgshaw/raman-fitting:20251031,alexgshaw/raman-fitting@sha256:401fa95d5d491f44a473eda9d2c52930f9565cc889c796eabcb6e20fec26852e
terminal-bench,protein-assembly,1800.0,1800.0,1800.0,1800.0,1,unlimited,4096,4096m,1,4096,internet,"{""allowed_domains"": [""rcsb.org"", ""fpbase.org"", ""pypi.org"", ""pythonhosted.org""], ""mode"": ""restricted""}",10240,10737418240,alexgshaw/protein-assembly:20251031,alexgshaw/protein-assembly@sha256:94de701b57e7ecfdbada6044f8534876e4b58874f8f313184dadc4d7533e0818
terminal-bench,write-compressor,900.0,900.0,900.0,900.0,1,unlimited,2048,2048m,1,2048,internet,"{""allowed_domains"": [], ""mode"": ""none""}",10240,10737418240,alexgshaw/write-compressor:20251031,alexgshaw/write-compressor@sha256:3618e1f8a997b437c09cd3dbaac736705809c05f6f12f584b65722175970ebe1
terminal-bench,mteb-leaderboard,3600.0,3600.0,3600.0,3600.0,1,unlimited,4096,4096m,1,4096,internet,"{""allowed_domains"": [""huggingface.co"", ""hf.co"", ""pypi.org"", ""pythonhosted.org""], ""mode"": ""restricted""}",10240,10737418240,alexgshaw/mteb-leaderboard:20251031,alexgshaw/mteb-leaderboard@sha256:968de9456bfc53728f7df0cb6c9ce33e17bd0e5563ddfe031e6ed2964965aecf
terminal-bench,mteb-retrieve,1800.0,1800.0,1800.0,1800.0,1,unlimited,2048,2048m,1,2048,internet,"{""allowed_domains"": [""huggingface.co"", ""hf.co"", ""xethub.hf.co"", ""pypi.org"", ""pythonhosted.org""], ""mode"": ""restricted""}",10240,10737418240,alexgshaw/mteb-retrieve:20251031,alexgshaw/mteb-retrieve@sha256:99dd676a21fd3124b7b8164cd93e8f0c51f1fdab2f84a831c61049eff78d063d
terminal-bench,rstan-to-pystan,1800.0,1800.0,1800.0,1800.0,4,unlimited,8192,8192m,4,8192,internet,"{""allowed_domains"": [""pypi.org"", ""pythonhosted.org""], ""mode"": ""restricted""}",10240,10737418240,alexgshaw/rstan-to-pystan:20251031,alexgshaw/rstan-to-pystan@sha256:b23d48839408524326095c15ada4145c772b87646cf299022ff1f58c97baba91
```

## Campaign configs (SecureBench, condition B)

Generated by `python -m tools.native_baseline.campaign_configs`; one config and one-row
task file per task. Full text follows.

### configs/securebench/deep-swe/anko-default-function-arguments/config.yaml (sha256 `1dba5da70c59552d`)

```yaml
schema_version: '1.0'
run:
  id: campaign-securebench-deep-swe-anko-default-function-arguments
  output_dir: /home/mfavrett/project/securebench/runs/campaign/securebench/deep-swe/unassigned/anko-default-function-arguments
  max_workers: 1
benchmark:
  manifest: /home/mfavrett/project/securebench/benchmarks/deep-swe/manifest-v2.yaml
  tasks: /home/mfavrett/project/securebench/runs/campaign/configs/securebench/deep-swe/anko-default-function-arguments/task.jsonl
docker:
  memory_limit: 8192m
harness:
  type: codex
  config:
    auth: api_key
    model: gpt-6-luna
    reasoning_effort: max
    version: 0.156.1
    task_file: task.json
    prompt: instructions
    timeout_seconds: 5400
    allow_external_tools: false
```

### configs/securebench/deep-swe/bandit-structured-nosec-directives/config.yaml (sha256 `27fdcd60ef404c30`)

```yaml
schema_version: '1.0'
run:
  id: campaign-securebench-deep-swe-bandit-structured-nosec-directives
  output_dir: /home/mfavrett/project/securebench/runs/campaign/securebench/deep-swe/unassigned/bandit-structured-nosec-directives
  max_workers: 1
benchmark:
  manifest: /home/mfavrett/project/securebench/benchmarks/deep-swe/manifest-v2.yaml
  tasks: /home/mfavrett/project/securebench/runs/campaign/configs/securebench/deep-swe/bandit-structured-nosec-directives/task.jsonl
docker:
  memory_limit: 8192m
harness:
  type: codex
  config:
    auth: api_key
    model: gpt-6-luna
    reasoning_effort: max
    version: 0.156.1
    task_file: task.json
    prompt: instructions
    timeout_seconds: 5400
    allow_external_tools: false
```

### configs/securebench/deep-swe/cattrs-partial-structuring-recovery/config.yaml (sha256 `17decbbc7f74cbe1`)

```yaml
schema_version: '1.0'
run:
  id: campaign-securebench-deep-swe-cattrs-partial-structuring-recovery
  output_dir: /home/mfavrett/project/securebench/runs/campaign/securebench/deep-swe/unassigned/cattrs-partial-structuring-recovery
  max_workers: 1
benchmark:
  manifest: /home/mfavrett/project/securebench/benchmarks/deep-swe/manifest-v2.yaml
  tasks: /home/mfavrett/project/securebench/runs/campaign/configs/securebench/deep-swe/cattrs-partial-structuring-recovery/task.jsonl
docker:
  memory_limit: 8192m
harness:
  type: codex
  config:
    auth: api_key
    model: gpt-6-luna
    reasoning_effort: max
    version: 0.156.1
    task_file: task.json
    prompt: instructions
    timeout_seconds: 5400
    allow_external_tools: false
```

### configs/securebench/deep-swe/csstree-shorthand-expansion-compression/config.yaml (sha256 `eca07d40906c2920`)

```yaml
schema_version: '1.0'
run:
  id: campaign-securebench-deep-swe-csstree-shorthand-expansion-compression
  output_dir: /home/mfavrett/project/securebench/runs/campaign/securebench/deep-swe/unassigned/csstree-shorthand-expansion-compression
  max_workers: 1
benchmark:
  manifest: /home/mfavrett/project/securebench/benchmarks/deep-swe/manifest-v2.yaml
  tasks: /home/mfavrett/project/securebench/runs/campaign/configs/securebench/deep-swe/csstree-shorthand-expansion-compression/task.jsonl
docker:
  memory_limit: 8192m
harness:
  type: codex
  config:
    auth: api_key
    model: gpt-6-luna
    reasoning_effort: max
    version: 0.156.1
    task_file: task.json
    prompt: instructions
    timeout_seconds: 5400
    allow_external_tools: false
```

### configs/securebench/deep-swe/dateutil-rfc5545-timezone-interop/config.yaml (sha256 `70d96f432f634641`)

```yaml
schema_version: '1.0'
run:
  id: campaign-securebench-deep-swe-dateutil-rfc5545-timezone-interop
  output_dir: /home/mfavrett/project/securebench/runs/campaign/securebench/deep-swe/unassigned/dateutil-rfc5545-timezone-interop
  max_workers: 1
benchmark:
  manifest: /home/mfavrett/project/securebench/benchmarks/deep-swe/manifest-v2.yaml
  tasks: /home/mfavrett/project/securebench/runs/campaign/configs/securebench/deep-swe/dateutil-rfc5545-timezone-interop/task.jsonl
docker:
  memory_limit: 8192m
harness:
  type: codex
  config:
    auth: api_key
    model: gpt-6-luna
    reasoning_effort: max
    version: 0.156.1
    task_file: task.json
    prompt: instructions
    timeout_seconds: 5400
    allow_external_tools: false
```

### configs/securebench/deep-swe/etree-xml-diff-patch/config.yaml (sha256 `4ac5c1a02b010c9b`)

```yaml
schema_version: '1.0'
run:
  id: campaign-securebench-deep-swe-etree-xml-diff-patch
  output_dir: /home/mfavrett/project/securebench/runs/campaign/securebench/deep-swe/unassigned/etree-xml-diff-patch
  max_workers: 1
benchmark:
  manifest: /home/mfavrett/project/securebench/benchmarks/deep-swe/manifest-v2.yaml
  tasks: /home/mfavrett/project/securebench/runs/campaign/configs/securebench/deep-swe/etree-xml-diff-patch/task.jsonl
docker:
  memory_limit: 8192m
harness:
  type: codex
  config:
    auth: api_key
    model: gpt-6-luna
    reasoning_effort: max
    version: 0.156.1
    task_file: task.json
    prompt: instructions
    timeout_seconds: 5400
    allow_external_tools: false
```

### configs/securebench/deep-swe/fd-deterministic-multi-key-sorting/config.yaml (sha256 `3166feabfc0908e3`)

```yaml
schema_version: '1.0'
run:
  id: campaign-securebench-deep-swe-fd-deterministic-multi-key-sorting
  output_dir: /home/mfavrett/project/securebench/runs/campaign/securebench/deep-swe/unassigned/fd-deterministic-multi-key-sorting
  max_workers: 1
benchmark:
  manifest: /home/mfavrett/project/securebench/benchmarks/deep-swe/manifest-v2.yaml
  tasks: /home/mfavrett/project/securebench/runs/campaign/configs/securebench/deep-swe/fd-deterministic-multi-key-sorting/task.jsonl
docker:
  memory_limit: 8192m
harness:
  type: codex
  config:
    auth: api_key
    model: gpt-6-luna
    reasoning_effort: max
    version: 0.156.1
    task_file: task.json
    prompt: instructions
    timeout_seconds: 5400
    allow_external_tools: false
```

### configs/securebench/deep-swe/go-critic-doc-link-checker/config.yaml (sha256 `debcd14b17ea765a`)

```yaml
schema_version: '1.0'
run:
  id: campaign-securebench-deep-swe-go-critic-doc-link-checker
  output_dir: /home/mfavrett/project/securebench/runs/campaign/securebench/deep-swe/unassigned/go-critic-doc-link-checker
  max_workers: 1
benchmark:
  manifest: /home/mfavrett/project/securebench/benchmarks/deep-swe/manifest-v2.yaml
  tasks: /home/mfavrett/project/securebench/runs/campaign/configs/securebench/deep-swe/go-critic-doc-link-checker/task.jsonl
docker:
  memory_limit: 8192m
harness:
  type: codex
  config:
    auth: api_key
    model: gpt-6-luna
    reasoning_effort: max
    version: 0.156.1
    task_file: task.json
    prompt: instructions
    timeout_seconds: 5400
    allow_external_tools: false
```

### configs/securebench/deep-swe/happy-dom-deterministic-intersectionobserver/config.yaml (sha256 `ce5dd642700a60ac`)

```yaml
schema_version: '1.0'
run:
  id: campaign-securebench-deep-swe-happy-dom-deterministic-intersectionobserver
  output_dir: /home/mfavrett/project/securebench/runs/campaign/securebench/deep-swe/unassigned/happy-dom-deterministic-intersectionobserver
  max_workers: 1
benchmark:
  manifest: /home/mfavrett/project/securebench/benchmarks/deep-swe/manifest-v2.yaml
  tasks: /home/mfavrett/project/securebench/runs/campaign/configs/securebench/deep-swe/happy-dom-deterministic-intersectionobserver/task.jsonl
docker:
  memory_limit: 8192m
harness:
  type: codex
  config:
    auth: api_key
    model: gpt-6-luna
    reasoning_effort: max
    version: 0.156.1
    task_file: task.json
    prompt: instructions
    timeout_seconds: 5400
    allow_external_tools: false
```

### configs/securebench/deep-swe/helm-array-merge-strategies/config.yaml (sha256 `f099d128cb268389`)

```yaml
schema_version: '1.0'
run:
  id: campaign-securebench-deep-swe-helm-array-merge-strategies
  output_dir: /home/mfavrett/project/securebench/runs/campaign/securebench/deep-swe/unassigned/helm-array-merge-strategies
  max_workers: 1
benchmark:
  manifest: /home/mfavrett/project/securebench/benchmarks/deep-swe/manifest-v2.yaml
  tasks: /home/mfavrett/project/securebench/runs/campaign/configs/securebench/deep-swe/helm-array-merge-strategies/task.jsonl
docker:
  memory_limit: 8192m
harness:
  type: codex
  config:
    auth: api_key
    model: gpt-6-luna
    reasoning_effort: max
    version: 0.156.1
    task_file: task.json
    prompt: instructions
    timeout_seconds: 5400
    allow_external_tools: false
```

### configs/securebench/deep-swe/helm-unified-manifest-stream/config.yaml (sha256 `bacc2d17474e5078`)

```yaml
schema_version: '1.0'
run:
  id: campaign-securebench-deep-swe-helm-unified-manifest-stream
  output_dir: /home/mfavrett/project/securebench/runs/campaign/securebench/deep-swe/unassigned/helm-unified-manifest-stream
  max_workers: 1
benchmark:
  manifest: /home/mfavrett/project/securebench/benchmarks/deep-swe/manifest-v2.yaml
  tasks: /home/mfavrett/project/securebench/runs/campaign/configs/securebench/deep-swe/helm-unified-manifest-stream/task.jsonl
docker:
  memory_limit: 8192m
harness:
  type: codex
  config:
    auth: api_key
    model: gpt-6-luna
    reasoning_effort: max
    version: 0.156.1
    task_file: task.json
    prompt: instructions
    timeout_seconds: 5400
    allow_external_tools: false
```

### configs/securebench/deep-swe/ink-grid-box-layout/config.yaml (sha256 `d472de80d67c3932`)

```yaml
schema_version: '1.0'
run:
  id: campaign-securebench-deep-swe-ink-grid-box-layout
  output_dir: /home/mfavrett/project/securebench/runs/campaign/securebench/deep-swe/unassigned/ink-grid-box-layout
  max_workers: 1
benchmark:
  manifest: /home/mfavrett/project/securebench/benchmarks/deep-swe/manifest-v2.yaml
  tasks: /home/mfavrett/project/securebench/runs/campaign/configs/securebench/deep-swe/ink-grid-box-layout/task.jsonl
docker:
  memory_limit: 8192m
harness:
  type: codex
  config:
    auth: api_key
    model: gpt-6-luna
    reasoning_effort: max
    version: 0.156.1
    task_file: task.json
    prompt: instructions
    timeout_seconds: 5400
    allow_external_tools: false
```

### configs/securebench/deep-swe/mashumaro-flattened-dataclass-fields/config.yaml (sha256 `c699d54120849489`)

```yaml
schema_version: '1.0'
run:
  id: campaign-securebench-deep-swe-mashumaro-flattened-dataclass-fields
  output_dir: /home/mfavrett/project/securebench/runs/campaign/securebench/deep-swe/unassigned/mashumaro-flattened-dataclass-fields
  max_workers: 1
benchmark:
  manifest: /home/mfavrett/project/securebench/benchmarks/deep-swe/manifest-v2.yaml
  tasks: /home/mfavrett/project/securebench/runs/campaign/configs/securebench/deep-swe/mashumaro-flattened-dataclass-fields/task.jsonl
docker:
  memory_limit: 8192m
harness:
  type: codex
  config:
    auth: api_key
    model: gpt-6-luna
    reasoning_effort: max
    version: 0.156.1
    task_file: task.json
    prompt: instructions
    timeout_seconds: 5400
    allow_external_tools: false
```

### configs/securebench/deep-swe/meriyah-explicit-resource-declarations/config.yaml (sha256 `15adcc54ab6f6e09`)

```yaml
schema_version: '1.0'
run:
  id: campaign-securebench-deep-swe-meriyah-explicit-resource-declarations
  output_dir: /home/mfavrett/project/securebench/runs/campaign/securebench/deep-swe/unassigned/meriyah-explicit-resource-declarations
  max_workers: 1
benchmark:
  manifest: /home/mfavrett/project/securebench/benchmarks/deep-swe/manifest-v2.yaml
  tasks: /home/mfavrett/project/securebench/runs/campaign/configs/securebench/deep-swe/meriyah-explicit-resource-declarations/task.jsonl
docker:
  memory_limit: 8192m
harness:
  type: codex
  config:
    auth: api_key
    model: gpt-6-luna
    reasoning_effort: max
    version: 0.156.1
    task_file: task.json
    prompt: instructions
    timeout_seconds: 5400
    allow_external_tools: false
```

### configs/securebench/deep-swe/narwhals-rolling-window-suite/config.yaml (sha256 `7dbf3820e472fbda`)

```yaml
schema_version: '1.0'
run:
  id: campaign-securebench-deep-swe-narwhals-rolling-window-suite
  output_dir: /home/mfavrett/project/securebench/runs/campaign/securebench/deep-swe/unassigned/narwhals-rolling-window-suite
  max_workers: 1
benchmark:
  manifest: /home/mfavrett/project/securebench/benchmarks/deep-swe/manifest-v2.yaml
  tasks: /home/mfavrett/project/securebench/runs/campaign/configs/securebench/deep-swe/narwhals-rolling-window-suite/task.jsonl
docker:
  memory_limit: 8192m
harness:
  type: codex
  config:
    auth: api_key
    model: gpt-6-luna
    reasoning_effort: max
    version: 0.156.1
    task_file: task.json
    prompt: instructions
    timeout_seconds: 5400
    allow_external_tools: false
```

### configs/securebench/deep-swe/obsidian-linter-scoped-ignore-markers/config.yaml (sha256 `0047fb00f09f4c3e`)

```yaml
schema_version: '1.0'
run:
  id: campaign-securebench-deep-swe-obsidian-linter-scoped-ignore-markers
  output_dir: /home/mfavrett/project/securebench/runs/campaign/securebench/deep-swe/unassigned/obsidian-linter-scoped-ignore-markers
  max_workers: 1
benchmark:
  manifest: /home/mfavrett/project/securebench/benchmarks/deep-swe/manifest-v2.yaml
  tasks: /home/mfavrett/project/securebench/runs/campaign/configs/securebench/deep-swe/obsidian-linter-scoped-ignore-markers/task.jsonl
docker:
  memory_limit: 8192m
harness:
  type: codex
  config:
    auth: api_key
    model: gpt-6-luna
    reasoning_effort: max
    version: 0.156.1
    task_file: task.json
    prompt: instructions
    timeout_seconds: 5400
    allow_external_tools: false
```

### configs/securebench/deep-swe/pest-character-class-coalescing/config.yaml (sha256 `1a74ba2a19eb1a1b`)

```yaml
schema_version: '1.0'
run:
  id: campaign-securebench-deep-swe-pest-character-class-coalescing
  output_dir: /home/mfavrett/project/securebench/runs/campaign/securebench/deep-swe/unassigned/pest-character-class-coalescing
  max_workers: 1
benchmark:
  manifest: /home/mfavrett/project/securebench/benchmarks/deep-swe/manifest-v2.yaml
  tasks: /home/mfavrett/project/securebench/runs/campaign/configs/securebench/deep-swe/pest-character-class-coalescing/task.jsonl
docker:
  memory_limit: 8192m
harness:
  type: codex
  config:
    auth: api_key
    model: gpt-6-luna
    reasoning_effort: max
    version: 0.156.1
    task_file: task.json
    prompt: instructions
    timeout_seconds: 5400
    allow_external_tools: false
```

### configs/securebench/deep-swe/prometheus-typed-label-sorting/config.yaml (sha256 `ea49a55e59bac41a`)

```yaml
schema_version: '1.0'
run:
  id: campaign-securebench-deep-swe-prometheus-typed-label-sorting
  output_dir: /home/mfavrett/project/securebench/runs/campaign/securebench/deep-swe/unassigned/prometheus-typed-label-sorting
  max_workers: 1
benchmark:
  manifest: /home/mfavrett/project/securebench/benchmarks/deep-swe/manifest-v2.yaml
  tasks: /home/mfavrett/project/securebench/runs/campaign/configs/securebench/deep-swe/prometheus-typed-label-sorting/task.jsonl
docker:
  memory_limit: 8192m
harness:
  type: codex
  config:
    auth: api_key
    model: gpt-6-luna
    reasoning_effort: max
    version: 0.156.1
    task_file: task.json
    prompt: instructions
    timeout_seconds: 5400
    allow_external_tools: false
```

### configs/securebench/deep-swe/python-statemachine-state-data-scoping/config.yaml (sha256 `2ed0065539b516f1`)

```yaml
schema_version: '1.0'
run:
  id: campaign-securebench-deep-swe-python-statemachine-state-data-scoping
  output_dir: /home/mfavrett/project/securebench/runs/campaign/securebench/deep-swe/unassigned/python-statemachine-state-data-scoping
  max_workers: 1
benchmark:
  manifest: /home/mfavrett/project/securebench/benchmarks/deep-swe/manifest-v2.yaml
  tasks: /home/mfavrett/project/securebench/runs/campaign/configs/securebench/deep-swe/python-statemachine-state-data-scoping/task.jsonl
docker:
  memory_limit: 8192m
harness:
  type: codex
  config:
    auth: api_key
    model: gpt-6-luna
    reasoning_effort: max
    version: 0.156.1
    task_file: task.json
    prompt: instructions
    timeout_seconds: 5400
    allow_external_tools: false
```

### configs/securebench/deep-swe/returns-validated-error-accumulation/config.yaml (sha256 `d735d3b1f15f3d72`)

```yaml
schema_version: '1.0'
run:
  id: campaign-securebench-deep-swe-returns-validated-error-accumulation
  output_dir: /home/mfavrett/project/securebench/runs/campaign/securebench/deep-swe/unassigned/returns-validated-error-accumulation
  max_workers: 1
benchmark:
  manifest: /home/mfavrett/project/securebench/benchmarks/deep-swe/manifest-v2.yaml
  tasks: /home/mfavrett/project/securebench/runs/campaign/configs/securebench/deep-swe/returns-validated-error-accumulation/task.jsonl
docker:
  memory_limit: 8192m
harness:
  type: codex
  config:
    auth: api_key
    model: gpt-6-luna
    reasoning_effort: max
    version: 0.156.1
    task_file: task.json
    prompt: instructions
    timeout_seconds: 5400
    allow_external_tools: false
```

### configs/securebench/deep-swe/skrub-duration-encoding/config.yaml (sha256 `89b68899b2b513b4`)

```yaml
schema_version: '1.0'
run:
  id: campaign-securebench-deep-swe-skrub-duration-encoding
  output_dir: /home/mfavrett/project/securebench/runs/campaign/securebench/deep-swe/unassigned/skrub-duration-encoding
  max_workers: 1
benchmark:
  manifest: /home/mfavrett/project/securebench/benchmarks/deep-swe/manifest-v2.yaml
  tasks: /home/mfavrett/project/securebench/runs/campaign/configs/securebench/deep-swe/skrub-duration-encoding/task.jsonl
docker:
  memory_limit: 8192m
harness:
  type: codex
  config:
    auth: api_key
    model: gpt-6-luna
    reasoning_effort: max
    version: 0.156.1
    task_file: task.json
    prompt: instructions
    timeout_seconds: 5400
    allow_external_tools: false
```

### configs/securebench/deep-swe/sqlfmt-create-table-ddl-formatting/config.yaml (sha256 `9ce3158124e58cc7`)

```yaml
schema_version: '1.0'
run:
  id: campaign-securebench-deep-swe-sqlfmt-create-table-ddl-formatting
  output_dir: /home/mfavrett/project/securebench/runs/campaign/securebench/deep-swe/unassigned/sqlfmt-create-table-ddl-formatting
  max_workers: 1
benchmark:
  manifest: /home/mfavrett/project/securebench/benchmarks/deep-swe/manifest-v2.yaml
  tasks: /home/mfavrett/project/securebench/runs/campaign/configs/securebench/deep-swe/sqlfmt-create-table-ddl-formatting/task.jsonl
docker:
  memory_limit: 8192m
harness:
  type: codex
  config:
    auth: api_key
    model: gpt-6-luna
    reasoning_effort: max
    version: 0.156.1
    task_file: task.json
    prompt: instructions
    timeout_seconds: 5400
    allow_external_tools: false
```

### configs/securebench/deep-swe/task-task-graph-export/config.yaml (sha256 `86de056068157172`)

```yaml
schema_version: '1.0'
run:
  id: campaign-securebench-deep-swe-task-task-graph-export
  output_dir: /home/mfavrett/project/securebench/runs/campaign/securebench/deep-swe/unassigned/task-task-graph-export
  max_workers: 1
benchmark:
  manifest: /home/mfavrett/project/securebench/benchmarks/deep-swe/manifest-v2.yaml
  tasks: /home/mfavrett/project/securebench/runs/campaign/configs/securebench/deep-swe/task-task-graph-export/task.jsonl
docker:
  memory_limit: 8192m
harness:
  type: codex
  config:
    auth: api_key
    model: gpt-6-luna
    reasoning_effort: max
    version: 0.156.1
    task_file: task.json
    prompt: instructions
    timeout_seconds: 5400
    allow_external_tools: false
```

### configs/securebench/deep-swe/tengo-callable-instance-isolation/config.yaml (sha256 `dd4cd58bfc3ebd22`)

```yaml
schema_version: '1.0'
run:
  id: campaign-securebench-deep-swe-tengo-callable-instance-isolation
  output_dir: /home/mfavrett/project/securebench/runs/campaign/securebench/deep-swe/unassigned/tengo-callable-instance-isolation
  max_workers: 1
benchmark:
  manifest: /home/mfavrett/project/securebench/benchmarks/deep-swe/manifest-v2.yaml
  tasks: /home/mfavrett/project/securebench/runs/campaign/configs/securebench/deep-swe/tengo-callable-instance-isolation/task.jsonl
docker:
  memory_limit: 8192m
harness:
  type: codex
  config:
    auth: api_key
    model: gpt-6-luna
    reasoning_effort: max
    version: 0.156.1
    task_file: task.json
    prompt: instructions
    timeout_seconds: 5400
    allow_external_tools: false
```

### configs/securebench/deep-swe/tengo-destructuring-bindings/config.yaml (sha256 `c61f921deb5bb683`)

```yaml
schema_version: '1.0'
run:
  id: campaign-securebench-deep-swe-tengo-destructuring-bindings
  output_dir: /home/mfavrett/project/securebench/runs/campaign/securebench/deep-swe/unassigned/tengo-destructuring-bindings
  max_workers: 1
benchmark:
  manifest: /home/mfavrett/project/securebench/benchmarks/deep-swe/manifest-v2.yaml
  tasks: /home/mfavrett/project/securebench/runs/campaign/configs/securebench/deep-swe/tengo-destructuring-bindings/task.jsonl
docker:
  memory_limit: 8192m
harness:
  type: codex
  config:
    auth: api_key
    model: gpt-6-luna
    reasoning_effort: max
    version: 0.156.1
    task_file: task.json
    prompt: instructions
    timeout_seconds: 5400
    allow_external_tools: false
```

### configs/securebench/deep-swe/termenv-preserve-ansi-resets/config.yaml (sha256 `afef83afe3d67dde`)

```yaml
schema_version: '1.0'
run:
  id: campaign-securebench-deep-swe-termenv-preserve-ansi-resets
  output_dir: /home/mfavrett/project/securebench/runs/campaign/securebench/deep-swe/unassigned/termenv-preserve-ansi-resets
  max_workers: 1
benchmark:
  manifest: /home/mfavrett/project/securebench/benchmarks/deep-swe/manifest-v2.yaml
  tasks: /home/mfavrett/project/securebench/runs/campaign/configs/securebench/deep-swe/termenv-preserve-ansi-resets/task.jsonl
docker:
  memory_limit: 8192m
harness:
  type: codex
  config:
    auth: api_key
    model: gpt-6-luna
    reasoning_effort: max
    version: 0.156.1
    task_file: task.json
    prompt: instructions
    timeout_seconds: 5400
    allow_external_tools: false
```

### configs/securebench/deep-swe/tomlkit-toml-table-converters/config.yaml (sha256 `3fd14d02508cead0`)

```yaml
schema_version: '1.0'
run:
  id: campaign-securebench-deep-swe-tomlkit-toml-table-converters
  output_dir: /home/mfavrett/project/securebench/runs/campaign/securebench/deep-swe/unassigned/tomlkit-toml-table-converters
  max_workers: 1
benchmark:
  manifest: /home/mfavrett/project/securebench/benchmarks/deep-swe/manifest-v2.yaml
  tasks: /home/mfavrett/project/securebench/runs/campaign/configs/securebench/deep-swe/tomlkit-toml-table-converters/task.jsonl
docker:
  memory_limit: 8192m
harness:
  type: codex
  config:
    auth: api_key
    model: gpt-6-luna
    reasoning_effort: max
    version: 0.156.1
    task_file: task.json
    prompt: instructions
    timeout_seconds: 5400
    allow_external_tools: false
```

### configs/securebench/deep-swe/true-myth-iterable-collection-combinators/config.yaml (sha256 `9aa3aac3d02e8523`)

```yaml
schema_version: '1.0'
run:
  id: campaign-securebench-deep-swe-true-myth-iterable-collection-combinators
  output_dir: /home/mfavrett/project/securebench/runs/campaign/securebench/deep-swe/unassigned/true-myth-iterable-collection-combinators
  max_workers: 1
benchmark:
  manifest: /home/mfavrett/project/securebench/benchmarks/deep-swe/manifest-v2.yaml
  tasks: /home/mfavrett/project/securebench/runs/campaign/configs/securebench/deep-swe/true-myth-iterable-collection-combinators/task.jsonl
docker:
  memory_limit: 8192m
harness:
  type: codex
  config:
    auth: api_key
    model: gpt-6-luna
    reasoning_effort: max
    version: 0.156.1
    task_file: task.json
    prompt: instructions
    timeout_seconds: 5400
    allow_external_tools: false
```

### configs/securebench/deep-swe/ts-pattern-match-each/config.yaml (sha256 `d3d8fac0cc1ea9ac`)

```yaml
schema_version: '1.0'
run:
  id: campaign-securebench-deep-swe-ts-pattern-match-each
  output_dir: /home/mfavrett/project/securebench/runs/campaign/securebench/deep-swe/unassigned/ts-pattern-match-each
  max_workers: 1
benchmark:
  manifest: /home/mfavrett/project/securebench/benchmarks/deep-swe/manifest-v2.yaml
  tasks: /home/mfavrett/project/securebench/runs/campaign/configs/securebench/deep-swe/ts-pattern-match-each/task.jsonl
docker:
  memory_limit: 8192m
harness:
  type: codex
  config:
    auth: api_key
    model: gpt-6-luna
    reasoning_effort: max
    version: 0.156.1
    task_file: task.json
    prompt: instructions
    timeout_seconds: 5400
    allow_external_tools: false
```

### configs/securebench/deep-swe/updo-policy-alerting/config.yaml (sha256 `b4e0d18f0c6ce160`)

```yaml
schema_version: '1.0'
run:
  id: campaign-securebench-deep-swe-updo-policy-alerting
  output_dir: /home/mfavrett/project/securebench/runs/campaign/securebench/deep-swe/unassigned/updo-policy-alerting
  max_workers: 1
benchmark:
  manifest: /home/mfavrett/project/securebench/benchmarks/deep-swe/manifest-v2.yaml
  tasks: /home/mfavrett/project/securebench/runs/campaign/configs/securebench/deep-swe/updo-policy-alerting/task.jsonl
docker:
  memory_limit: 8192m
harness:
  type: codex
  config:
    auth: api_key
    model: gpt-6-luna
    reasoning_effort: max
    version: 0.156.1
    task_file: task.json
    prompt: instructions
    timeout_seconds: 5400
    allow_external_tools: false
```

### configs/securebench/terminal-bench/bn-fit-modify/config.yaml (sha256 `1feb9a1eabee40bc`)

```yaml
schema_version: '1.0'
run:
  id: campaign-securebench-terminal-bench-bn-fit-modify
  output_dir: /home/mfavrett/project/securebench/runs/campaign/securebench/terminal-bench/unassigned/bn-fit-modify
  max_workers: 1
benchmark:
  manifest: /home/mfavrett/project/securebench/benchmarks/terminal-bench/manifest-v2.yaml
  tasks: /home/mfavrett/project/securebench/runs/campaign/configs/securebench/terminal-bench/bn-fit-modify/task.jsonl
docker:
  memory_limit: 2048m
network_policy:
  mode: extend
  allowed_domains:
  - github.com
  - githubusercontent.com
  - pypi.org
  - pythonhosted.org
  - huggingface.co
  - hf.co
  - xethub.hf.co
  - pytorch.org
  - debian.org
  - ubuntu.com
  - r-project.org
  - youtube.com
  - googlevideo.com
  - ytimg.com
  - povray.org
  - neocities.org
  - qemu.org
  - inria.fr
  - ocaml.org
  - readthedocs.io
  - rcsb.org
  - ncbi.nlm.nih.gov
  - fpbase.org
  - corewar.co.uk
harness:
  type: codex
  config:
    auth: api_key
    model: gpt-6-luna
    reasoning_effort: max
    version: 0.156.1
    task_file: task.json
    prompt: instructions
    timeout_seconds: 3600
    allow_external_tools: false
capture:
  max_candidate_bytes: 10737418240
```

### configs/securebench/terminal-bench/cancel-async-tasks/config.yaml (sha256 `375875df40758c6f`)

```yaml
schema_version: '1.0'
run:
  id: campaign-securebench-terminal-bench-cancel-async-tasks
  output_dir: /home/mfavrett/project/securebench/runs/campaign/securebench/terminal-bench/unassigned/cancel-async-tasks
  max_workers: 1
benchmark:
  manifest: /home/mfavrett/project/securebench/benchmarks/terminal-bench/manifest-v2.yaml
  tasks: /home/mfavrett/project/securebench/runs/campaign/configs/securebench/terminal-bench/cancel-async-tasks/task.jsonl
docker:
  memory_limit: 2048m
network_policy:
  mode: extend
  allowed_domains:
  - github.com
  - githubusercontent.com
  - pypi.org
  - pythonhosted.org
  - huggingface.co
  - hf.co
  - xethub.hf.co
  - pytorch.org
  - debian.org
  - ubuntu.com
  - r-project.org
  - youtube.com
  - googlevideo.com
  - ytimg.com
  - povray.org
  - neocities.org
  - qemu.org
  - inria.fr
  - ocaml.org
  - readthedocs.io
  - rcsb.org
  - ncbi.nlm.nih.gov
  - fpbase.org
  - corewar.co.uk
harness:
  type: codex
  config:
    auth: api_key
    model: gpt-6-luna
    reasoning_effort: max
    version: 0.156.1
    task_file: task.json
    prompt: instructions
    timeout_seconds: 900
    allow_external_tools: false
capture:
  max_candidate_bytes: 10737418240
```

### configs/securebench/terminal-bench/chess-best-move/config.yaml (sha256 `c1f350db35016194`)

```yaml
schema_version: '1.0'
run:
  id: campaign-securebench-terminal-bench-chess-best-move
  output_dir: /home/mfavrett/project/securebench/runs/campaign/securebench/terminal-bench/unassigned/chess-best-move
  max_workers: 1
benchmark:
  manifest: /home/mfavrett/project/securebench/benchmarks/terminal-bench/manifest-v2.yaml
  tasks: /home/mfavrett/project/securebench/runs/campaign/configs/securebench/terminal-bench/chess-best-move/task.jsonl
docker:
  memory_limit: 2048m
network_policy:
  mode: extend
  allowed_domains:
  - github.com
  - githubusercontent.com
  - pypi.org
  - pythonhosted.org
  - huggingface.co
  - hf.co
  - xethub.hf.co
  - pytorch.org
  - debian.org
  - ubuntu.com
  - r-project.org
  - youtube.com
  - googlevideo.com
  - ytimg.com
  - povray.org
  - neocities.org
  - qemu.org
  - inria.fr
  - ocaml.org
  - readthedocs.io
  - rcsb.org
  - ncbi.nlm.nih.gov
  - fpbase.org
  - corewar.co.uk
harness:
  type: codex
  config:
    auth: api_key
    model: gpt-6-luna
    reasoning_effort: max
    version: 0.156.1
    task_file: task.json
    prompt: instructions
    timeout_seconds: 900
    allow_external_tools: false
capture:
  max_candidate_bytes: 10737418240
```

### configs/securebench/terminal-bench/code-from-image/config.yaml (sha256 `dc67020bbbc92287`)

```yaml
schema_version: '1.0'
run:
  id: campaign-securebench-terminal-bench-code-from-image
  output_dir: /home/mfavrett/project/securebench/runs/campaign/securebench/terminal-bench/unassigned/code-from-image
  max_workers: 1
benchmark:
  manifest: /home/mfavrett/project/securebench/benchmarks/terminal-bench/manifest-v2.yaml
  tasks: /home/mfavrett/project/securebench/runs/campaign/configs/securebench/terminal-bench/code-from-image/task.jsonl
docker:
  memory_limit: 2048m
network_policy:
  mode: extend
  allowed_domains:
  - github.com
  - githubusercontent.com
  - pypi.org
  - pythonhosted.org
  - huggingface.co
  - hf.co
  - xethub.hf.co
  - pytorch.org
  - debian.org
  - ubuntu.com
  - r-project.org
  - youtube.com
  - googlevideo.com
  - ytimg.com
  - povray.org
  - neocities.org
  - qemu.org
  - inria.fr
  - ocaml.org
  - readthedocs.io
  - rcsb.org
  - ncbi.nlm.nih.gov
  - fpbase.org
  - corewar.co.uk
harness:
  type: codex
  config:
    auth: api_key
    model: gpt-6-luna
    reasoning_effort: max
    version: 0.156.1
    task_file: task.json
    prompt: instructions
    timeout_seconds: 1200
    allow_external_tools: false
capture:
  max_candidate_bytes: 10737418240
```

### configs/securebench/terminal-bench/constraints-scheduling/config.yaml (sha256 `8af8ce431c58c237`)

```yaml
schema_version: '1.0'
run:
  id: campaign-securebench-terminal-bench-constraints-scheduling
  output_dir: /home/mfavrett/project/securebench/runs/campaign/securebench/terminal-bench/unassigned/constraints-scheduling
  max_workers: 1
benchmark:
  manifest: /home/mfavrett/project/securebench/benchmarks/terminal-bench/manifest-v2.yaml
  tasks: /home/mfavrett/project/securebench/runs/campaign/configs/securebench/terminal-bench/constraints-scheduling/task.jsonl
docker:
  memory_limit: 2048m
network_policy:
  mode: extend
  allowed_domains:
  - github.com
  - githubusercontent.com
  - pypi.org
  - pythonhosted.org
  - huggingface.co
  - hf.co
  - xethub.hf.co
  - pytorch.org
  - debian.org
  - ubuntu.com
  - r-project.org
  - youtube.com
  - googlevideo.com
  - ytimg.com
  - povray.org
  - neocities.org
  - qemu.org
  - inria.fr
  - ocaml.org
  - readthedocs.io
  - rcsb.org
  - ncbi.nlm.nih.gov
  - fpbase.org
  - corewar.co.uk
harness:
  type: codex
  config:
    auth: api_key
    model: gpt-6-luna
    reasoning_effort: max
    version: 0.156.1
    task_file: task.json
    prompt: instructions
    timeout_seconds: 1200
    allow_external_tools: false
capture:
  max_candidate_bytes: 10737418240
```

### configs/securebench/terminal-bench/count-dataset-tokens/config.yaml (sha256 `ae2413ad611af78e`)

```yaml
schema_version: '1.0'
run:
  id: campaign-securebench-terminal-bench-count-dataset-tokens
  output_dir: /home/mfavrett/project/securebench/runs/campaign/securebench/terminal-bench/unassigned/count-dataset-tokens
  max_workers: 1
benchmark:
  manifest: /home/mfavrett/project/securebench/benchmarks/terminal-bench/manifest-v2.yaml
  tasks: /home/mfavrett/project/securebench/runs/campaign/configs/securebench/terminal-bench/count-dataset-tokens/task.jsonl
docker:
  memory_limit: 2048m
network_policy:
  mode: extend
  allowed_domains:
  - github.com
  - githubusercontent.com
  - pypi.org
  - pythonhosted.org
  - huggingface.co
  - hf.co
  - xethub.hf.co
  - pytorch.org
  - debian.org
  - ubuntu.com
  - r-project.org
  - youtube.com
  - googlevideo.com
  - ytimg.com
  - povray.org
  - neocities.org
  - qemu.org
  - inria.fr
  - ocaml.org
  - readthedocs.io
  - rcsb.org
  - ncbi.nlm.nih.gov
  - fpbase.org
  - corewar.co.uk
harness:
  type: codex
  config:
    auth: api_key
    model: gpt-6-luna
    reasoning_effort: max
    version: 0.156.1
    task_file: task.json
    prompt: instructions
    timeout_seconds: 900
    allow_external_tools: false
capture:
  max_candidate_bytes: 10737418240
```

### configs/securebench/terminal-bench/crack-7z-hash/config.yaml (sha256 `d0d997abfd2ecf1f`)

```yaml
schema_version: '1.0'
run:
  id: campaign-securebench-terminal-bench-crack-7z-hash
  output_dir: /home/mfavrett/project/securebench/runs/campaign/securebench/terminal-bench/unassigned/crack-7z-hash
  max_workers: 1
benchmark:
  manifest: /home/mfavrett/project/securebench/benchmarks/terminal-bench/manifest-v2.yaml
  tasks: /home/mfavrett/project/securebench/runs/campaign/configs/securebench/terminal-bench/crack-7z-hash/task.jsonl
docker:
  memory_limit: 4096m
network_policy:
  mode: extend
  allowed_domains:
  - github.com
  - githubusercontent.com
  - pypi.org
  - pythonhosted.org
  - huggingface.co
  - hf.co
  - xethub.hf.co
  - pytorch.org
  - debian.org
  - ubuntu.com
  - r-project.org
  - youtube.com
  - googlevideo.com
  - ytimg.com
  - povray.org
  - neocities.org
  - qemu.org
  - inria.fr
  - ocaml.org
  - readthedocs.io
  - rcsb.org
  - ncbi.nlm.nih.gov
  - fpbase.org
  - corewar.co.uk
harness:
  type: codex
  config:
    auth: api_key
    model: gpt-6-luna
    reasoning_effort: max
    version: 0.156.1
    task_file: task.json
    prompt: instructions
    timeout_seconds: 1800
    allow_external_tools: false
capture:
  max_candidate_bytes: 10737418240
```

### configs/securebench/terminal-bench/db-wal-recovery/config.yaml (sha256 `9fc142ae37420c6b`)

```yaml
schema_version: '1.0'
run:
  id: campaign-securebench-terminal-bench-db-wal-recovery
  output_dir: /home/mfavrett/project/securebench/runs/campaign/securebench/terminal-bench/unassigned/db-wal-recovery
  max_workers: 1
benchmark:
  manifest: /home/mfavrett/project/securebench/benchmarks/terminal-bench/manifest-v2.yaml
  tasks: /home/mfavrett/project/securebench/runs/campaign/configs/securebench/terminal-bench/db-wal-recovery/task.jsonl
docker:
  memory_limit: 2048m
network_policy:
  mode: extend
  allowed_domains:
  - github.com
  - githubusercontent.com
  - pypi.org
  - pythonhosted.org
  - huggingface.co
  - hf.co
  - xethub.hf.co
  - pytorch.org
  - debian.org
  - ubuntu.com
  - r-project.org
  - youtube.com
  - googlevideo.com
  - ytimg.com
  - povray.org
  - neocities.org
  - qemu.org
  - inria.fr
  - ocaml.org
  - readthedocs.io
  - rcsb.org
  - ncbi.nlm.nih.gov
  - fpbase.org
  - corewar.co.uk
harness:
  type: codex
  config:
    auth: api_key
    model: gpt-6-luna
    reasoning_effort: max
    version: 0.156.1
    task_file: task.json
    prompt: instructions
    timeout_seconds: 900
    allow_external_tools: false
capture:
  max_candidate_bytes: 10737418240
```

### configs/securebench/terminal-bench/distribution-search/config.yaml (sha256 `2d4b5a2c340d93d1`)

```yaml
schema_version: '1.0'
run:
  id: campaign-securebench-terminal-bench-distribution-search
  output_dir: /home/mfavrett/project/securebench/runs/campaign/securebench/terminal-bench/unassigned/distribution-search
  max_workers: 1
benchmark:
  manifest: /home/mfavrett/project/securebench/benchmarks/terminal-bench/manifest-v2.yaml
  tasks: /home/mfavrett/project/securebench/runs/campaign/configs/securebench/terminal-bench/distribution-search/task.jsonl
docker:
  memory_limit: 2048m
network_policy:
  mode: extend
  allowed_domains:
  - github.com
  - githubusercontent.com
  - pypi.org
  - pythonhosted.org
  - huggingface.co
  - hf.co
  - xethub.hf.co
  - pytorch.org
  - debian.org
  - ubuntu.com
  - r-project.org
  - youtube.com
  - googlevideo.com
  - ytimg.com
  - povray.org
  - neocities.org
  - qemu.org
  - inria.fr
  - ocaml.org
  - readthedocs.io
  - rcsb.org
  - ncbi.nlm.nih.gov
  - fpbase.org
  - corewar.co.uk
harness:
  type: codex
  config:
    auth: api_key
    model: gpt-6-luna
    reasoning_effort: max
    version: 0.156.1
    task_file: task.json
    prompt: instructions
    timeout_seconds: 3600
    allow_external_tools: false
capture:
  max_candidate_bytes: 10737418240
```

### configs/securebench/terminal-bench/dna-assembly/config.yaml (sha256 `7830f15cb58c9e52`)

```yaml
schema_version: '1.0'
run:
  id: campaign-securebench-terminal-bench-dna-assembly
  output_dir: /home/mfavrett/project/securebench/runs/campaign/securebench/terminal-bench/unassigned/dna-assembly
  max_workers: 1
benchmark:
  manifest: /home/mfavrett/project/securebench/benchmarks/terminal-bench/manifest-v2.yaml
  tasks: /home/mfavrett/project/securebench/runs/campaign/configs/securebench/terminal-bench/dna-assembly/task.jsonl
docker:
  memory_limit: 2048m
network_policy:
  mode: extend
  allowed_domains:
  - github.com
  - githubusercontent.com
  - pypi.org
  - pythonhosted.org
  - huggingface.co
  - hf.co
  - xethub.hf.co
  - pytorch.org
  - debian.org
  - ubuntu.com
  - r-project.org
  - youtube.com
  - googlevideo.com
  - ytimg.com
  - povray.org
  - neocities.org
  - qemu.org
  - inria.fr
  - ocaml.org
  - readthedocs.io
  - rcsb.org
  - ncbi.nlm.nih.gov
  - fpbase.org
  - corewar.co.uk
harness:
  type: codex
  config:
    auth: api_key
    model: gpt-6-luna
    reasoning_effort: max
    version: 0.156.1
    task_file: task.json
    prompt: instructions
    timeout_seconds: 1800
    allow_external_tools: false
capture:
  max_candidate_bytes: 10737418240
```

### configs/securebench/terminal-bench/dna-insert/config.yaml (sha256 `2d1796a8d91d7a40`)

```yaml
schema_version: '1.0'
run:
  id: campaign-securebench-terminal-bench-dna-insert
  output_dir: /home/mfavrett/project/securebench/runs/campaign/securebench/terminal-bench/unassigned/dna-insert
  max_workers: 1
benchmark:
  manifest: /home/mfavrett/project/securebench/benchmarks/terminal-bench/manifest-v2.yaml
  tasks: /home/mfavrett/project/securebench/runs/campaign/configs/securebench/terminal-bench/dna-insert/task.jsonl
docker:
  memory_limit: 4096m
network_policy:
  mode: extend
  allowed_domains:
  - github.com
  - githubusercontent.com
  - pypi.org
  - pythonhosted.org
  - huggingface.co
  - hf.co
  - xethub.hf.co
  - pytorch.org
  - debian.org
  - ubuntu.com
  - r-project.org
  - youtube.com
  - googlevideo.com
  - ytimg.com
  - povray.org
  - neocities.org
  - qemu.org
  - inria.fr
  - ocaml.org
  - readthedocs.io
  - rcsb.org
  - ncbi.nlm.nih.gov
  - fpbase.org
  - corewar.co.uk
harness:
  type: codex
  config:
    auth: api_key
    model: gpt-6-luna
    reasoning_effort: max
    version: 0.156.1
    task_file: task.json
    prompt: instructions
    timeout_seconds: 1800
    allow_external_tools: false
capture:
  max_candidate_bytes: 10737418240
```

### configs/securebench/terminal-bench/extract-moves-from-video/config.yaml (sha256 `c41db7684ae400b3`)

```yaml
schema_version: '1.0'
run:
  id: campaign-securebench-terminal-bench-extract-moves-from-video
  output_dir: /home/mfavrett/project/securebench/runs/campaign/securebench/terminal-bench/unassigned/extract-moves-from-video
  max_workers: 1
benchmark:
  manifest: /home/mfavrett/project/securebench/benchmarks/terminal-bench/manifest-v2.yaml
  tasks: /home/mfavrett/project/securebench/runs/campaign/configs/securebench/terminal-bench/extract-moves-from-video/task.jsonl
docker:
  memory_limit: 2048m
network_policy:
  mode: extend
  allowed_domains:
  - github.com
  - githubusercontent.com
  - pypi.org
  - pythonhosted.org
  - huggingface.co
  - hf.co
  - xethub.hf.co
  - pytorch.org
  - debian.org
  - ubuntu.com
  - r-project.org
  - youtube.com
  - googlevideo.com
  - ytimg.com
  - povray.org
  - neocities.org
  - qemu.org
  - inria.fr
  - ocaml.org
  - readthedocs.io
  - rcsb.org
  - ncbi.nlm.nih.gov
  - fpbase.org
  - corewar.co.uk
harness:
  type: codex
  config:
    auth: api_key
    model: gpt-6-luna
    reasoning_effort: max
    version: 0.156.1
    task_file: task.json
    prompt: instructions
    timeout_seconds: 1800
    allow_external_tools: false
capture:
  max_candidate_bytes: 10737418240
```

### configs/securebench/terminal-bench/feal-linear-cryptanalysis/config.yaml (sha256 `96bc3a9fbd113bfa`)

```yaml
schema_version: '1.0'
run:
  id: campaign-securebench-terminal-bench-feal-linear-cryptanalysis
  output_dir: /home/mfavrett/project/securebench/runs/campaign/securebench/terminal-bench/unassigned/feal-linear-cryptanalysis
  max_workers: 1
benchmark:
  manifest: /home/mfavrett/project/securebench/benchmarks/terminal-bench/manifest-v2.yaml
  tasks: /home/mfavrett/project/securebench/runs/campaign/configs/securebench/terminal-bench/feal-linear-cryptanalysis/task.jsonl
docker:
  memory_limit: 2048m
network_policy:
  mode: extend
  allowed_domains:
  - github.com
  - githubusercontent.com
  - pypi.org
  - pythonhosted.org
  - huggingface.co
  - hf.co
  - xethub.hf.co
  - pytorch.org
  - debian.org
  - ubuntu.com
  - r-project.org
  - youtube.com
  - googlevideo.com
  - ytimg.com
  - povray.org
  - neocities.org
  - qemu.org
  - inria.fr
  - ocaml.org
  - readthedocs.io
  - rcsb.org
  - ncbi.nlm.nih.gov
  - fpbase.org
  - corewar.co.uk
harness:
  type: codex
  config:
    auth: api_key
    model: gpt-6-luna
    reasoning_effort: max
    version: 0.156.1
    task_file: task.json
    prompt: instructions
    timeout_seconds: 1800
    allow_external_tools: false
capture:
  max_candidate_bytes: 10737418240
```

### configs/securebench/terminal-bench/financial-document-processor/config.yaml (sha256 `5c017299b1a283da`)

```yaml
schema_version: '1.0'
run:
  id: campaign-securebench-terminal-bench-financial-document-processor
  output_dir: /home/mfavrett/project/securebench/runs/campaign/securebench/terminal-bench/unassigned/financial-document-processor
  max_workers: 1
benchmark:
  manifest: /home/mfavrett/project/securebench/benchmarks/terminal-bench/manifest-v2.yaml
  tasks: /home/mfavrett/project/securebench/runs/campaign/configs/securebench/terminal-bench/financial-document-processor/task.jsonl
docker:
  memory_limit: 4096m
network_policy:
  mode: extend
  allowed_domains:
  - github.com
  - githubusercontent.com
  - pypi.org
  - pythonhosted.org
  - huggingface.co
  - hf.co
  - xethub.hf.co
  - pytorch.org
  - debian.org
  - ubuntu.com
  - r-project.org
  - youtube.com
  - googlevideo.com
  - ytimg.com
  - povray.org
  - neocities.org
  - qemu.org
  - inria.fr
  - ocaml.org
  - readthedocs.io
  - rcsb.org
  - ncbi.nlm.nih.gov
  - fpbase.org
  - corewar.co.uk
harness:
  type: codex
  config:
    auth: api_key
    model: gpt-6-luna
    reasoning_effort: max
    version: 0.156.1
    task_file: task.json
    prompt: instructions
    timeout_seconds: 1200
    allow_external_tools: false
capture:
  max_candidate_bytes: 10737418240
```

### configs/securebench/terminal-bench/fix-git/config.yaml (sha256 `81e5468d43119dd3`)

```yaml
schema_version: '1.0'
run:
  id: campaign-securebench-terminal-bench-fix-git
  output_dir: /home/mfavrett/project/securebench/runs/campaign/securebench/terminal-bench/unassigned/fix-git
  max_workers: 1
benchmark:
  manifest: /home/mfavrett/project/securebench/benchmarks/terminal-bench/manifest-v2.yaml
  tasks: /home/mfavrett/project/securebench/runs/campaign/configs/securebench/terminal-bench/fix-git/task.jsonl
docker:
  memory_limit: 2048m
network_policy:
  mode: extend
  allowed_domains:
  - github.com
  - githubusercontent.com
  - pypi.org
  - pythonhosted.org
  - huggingface.co
  - hf.co
  - xethub.hf.co
  - pytorch.org
  - debian.org
  - ubuntu.com
  - r-project.org
  - youtube.com
  - googlevideo.com
  - ytimg.com
  - povray.org
  - neocities.org
  - qemu.org
  - inria.fr
  - ocaml.org
  - readthedocs.io
  - rcsb.org
  - ncbi.nlm.nih.gov
  - fpbase.org
  - corewar.co.uk
harness:
  type: codex
  config:
    auth: api_key
    model: gpt-6-luna
    reasoning_effort: max
    version: 0.156.1
    task_file: task.json
    prompt: instructions
    timeout_seconds: 900
    allow_external_tools: false
capture:
  max_candidate_bytes: 10737418240
```

### configs/securebench/terminal-bench/gcode-to-text/config.yaml (sha256 `8a257cb85d2570e9`)

```yaml
schema_version: '1.0'
run:
  id: campaign-securebench-terminal-bench-gcode-to-text
  output_dir: /home/mfavrett/project/securebench/runs/campaign/securebench/terminal-bench/unassigned/gcode-to-text
  max_workers: 1
benchmark:
  manifest: /home/mfavrett/project/securebench/benchmarks/terminal-bench/manifest-v2.yaml
  tasks: /home/mfavrett/project/securebench/runs/campaign/configs/securebench/terminal-bench/gcode-to-text/task.jsonl
docker:
  memory_limit: 2048m
network_policy:
  mode: extend
  allowed_domains:
  - github.com
  - githubusercontent.com
  - pypi.org
  - pythonhosted.org
  - huggingface.co
  - hf.co
  - xethub.hf.co
  - pytorch.org
  - debian.org
  - ubuntu.com
  - r-project.org
  - youtube.com
  - googlevideo.com
  - ytimg.com
  - povray.org
  - neocities.org
  - qemu.org
  - inria.fr
  - ocaml.org
  - readthedocs.io
  - rcsb.org
  - ncbi.nlm.nih.gov
  - fpbase.org
  - corewar.co.uk
harness:
  type: codex
  config:
    auth: api_key
    model: gpt-6-luna
    reasoning_effort: max
    version: 0.156.1
    task_file: task.json
    prompt: instructions
    timeout_seconds: 900
    allow_external_tools: false
capture:
  max_candidate_bytes: 10737418240
```

### configs/securebench/terminal-bench/git-leak-recovery/config.yaml (sha256 `beadec838d87c4ec`)

```yaml
schema_version: '1.0'
run:
  id: campaign-securebench-terminal-bench-git-leak-recovery
  output_dir: /home/mfavrett/project/securebench/runs/campaign/securebench/terminal-bench/unassigned/git-leak-recovery
  max_workers: 1
benchmark:
  manifest: /home/mfavrett/project/securebench/benchmarks/terminal-bench/manifest-v2.yaml
  tasks: /home/mfavrett/project/securebench/runs/campaign/configs/securebench/terminal-bench/git-leak-recovery/task.jsonl
docker:
  memory_limit: 2048m
network_policy:
  mode: extend
  allowed_domains:
  - github.com
  - githubusercontent.com
  - pypi.org
  - pythonhosted.org
  - huggingface.co
  - hf.co
  - xethub.hf.co
  - pytorch.org
  - debian.org
  - ubuntu.com
  - r-project.org
  - youtube.com
  - googlevideo.com
  - ytimg.com
  - povray.org
  - neocities.org
  - qemu.org
  - inria.fr
  - ocaml.org
  - readthedocs.io
  - rcsb.org
  - ncbi.nlm.nih.gov
  - fpbase.org
  - corewar.co.uk
harness:
  type: codex
  config:
    auth: api_key
    model: gpt-6-luna
    reasoning_effort: max
    version: 0.156.1
    task_file: task.json
    prompt: instructions
    timeout_seconds: 900
    allow_external_tools: false
capture:
  max_candidate_bytes: 10737418240
```

### configs/securebench/terminal-bench/gpt2-codegolf/config.yaml (sha256 `bde3b46285766cff`)

```yaml
schema_version: '1.0'
run:
  id: campaign-securebench-terminal-bench-gpt2-codegolf
  output_dir: /home/mfavrett/project/securebench/runs/campaign/securebench/terminal-bench/unassigned/gpt2-codegolf
  max_workers: 1
benchmark:
  manifest: /home/mfavrett/project/securebench/benchmarks/terminal-bench/manifest-v2.yaml
  tasks: /home/mfavrett/project/securebench/runs/campaign/configs/securebench/terminal-bench/gpt2-codegolf/task.jsonl
docker:
  memory_limit: 8192m
network_policy:
  mode: extend
  allowed_domains:
  - github.com
  - githubusercontent.com
  - pypi.org
  - pythonhosted.org
  - huggingface.co
  - hf.co
  - xethub.hf.co
  - pytorch.org
  - debian.org
  - ubuntu.com
  - r-project.org
  - youtube.com
  - googlevideo.com
  - ytimg.com
  - povray.org
  - neocities.org
  - qemu.org
  - inria.fr
  - ocaml.org
  - readthedocs.io
  - rcsb.org
  - ncbi.nlm.nih.gov
  - fpbase.org
  - corewar.co.uk
harness:
  type: codex
  config:
    auth: api_key
    model: gpt-6-luna
    reasoning_effort: max
    version: 0.156.1
    task_file: task.json
    prompt: instructions
    timeout_seconds: 900
    allow_external_tools: false
capture:
  max_candidate_bytes: 10737418240
```

### configs/securebench/terminal-bench/headless-terminal/config.yaml (sha256 `9e669a4fd68e5478`)

```yaml
schema_version: '1.0'
run:
  id: campaign-securebench-terminal-bench-headless-terminal
  output_dir: /home/mfavrett/project/securebench/runs/campaign/securebench/terminal-bench/unassigned/headless-terminal
  max_workers: 1
benchmark:
  manifest: /home/mfavrett/project/securebench/benchmarks/terminal-bench/manifest-v2.yaml
  tasks: /home/mfavrett/project/securebench/runs/campaign/configs/securebench/terminal-bench/headless-terminal/task.jsonl
docker:
  memory_limit: 2048m
network_policy:
  mode: extend
  allowed_domains:
  - github.com
  - githubusercontent.com
  - pypi.org
  - pythonhosted.org
  - huggingface.co
  - hf.co
  - xethub.hf.co
  - pytorch.org
  - debian.org
  - ubuntu.com
  - r-project.org
  - youtube.com
  - googlevideo.com
  - ytimg.com
  - povray.org
  - neocities.org
  - qemu.org
  - inria.fr
  - ocaml.org
  - readthedocs.io
  - rcsb.org
  - ncbi.nlm.nih.gov
  - fpbase.org
  - corewar.co.uk
harness:
  type: codex
  config:
    auth: api_key
    model: gpt-6-luna
    reasoning_effort: max
    version: 0.156.1
    task_file: task.json
    prompt: instructions
    timeout_seconds: 900
    allow_external_tools: false
capture:
  max_candidate_bytes: 10737418240
```

### configs/securebench/terminal-bench/hf-model-inference/config.yaml (sha256 `cdc5a9f8247c5dd9`)

```yaml
schema_version: '1.0'
run:
  id: campaign-securebench-terminal-bench-hf-model-inference
  output_dir: /home/mfavrett/project/securebench/runs/campaign/securebench/terminal-bench/unassigned/hf-model-inference
  max_workers: 1
benchmark:
  manifest: /home/mfavrett/project/securebench/benchmarks/terminal-bench/manifest-v2.yaml
  tasks: /home/mfavrett/project/securebench/runs/campaign/configs/securebench/terminal-bench/hf-model-inference/task.jsonl
docker:
  memory_limit: 2048m
network_policy:
  mode: extend
  allowed_domains:
  - github.com
  - githubusercontent.com
  - pypi.org
  - pythonhosted.org
  - huggingface.co
  - hf.co
  - xethub.hf.co
  - pytorch.org
  - debian.org
  - ubuntu.com
  - r-project.org
  - youtube.com
  - googlevideo.com
  - ytimg.com
  - povray.org
  - neocities.org
  - qemu.org
  - inria.fr
  - ocaml.org
  - readthedocs.io
  - rcsb.org
  - ncbi.nlm.nih.gov
  - fpbase.org
  - corewar.co.uk
harness:
  type: codex
  config:
    auth: api_key
    model: gpt-6-luna
    reasoning_effort: max
    version: 0.156.1
    task_file: task.json
    prompt: instructions
    timeout_seconds: 900
    allow_external_tools: false
capture:
  max_candidate_bytes: 10737418240
```

### configs/securebench/terminal-bench/kv-store-grpc/config.yaml (sha256 `99dd55d4949bbe0f`)

```yaml
schema_version: '1.0'
run:
  id: campaign-securebench-terminal-bench-kv-store-grpc
  output_dir: /home/mfavrett/project/securebench/runs/campaign/securebench/terminal-bench/unassigned/kv-store-grpc
  max_workers: 1
benchmark:
  manifest: /home/mfavrett/project/securebench/benchmarks/terminal-bench/manifest-v2.yaml
  tasks: /home/mfavrett/project/securebench/runs/campaign/configs/securebench/terminal-bench/kv-store-grpc/task.jsonl
docker:
  memory_limit: 2048m
network_policy:
  mode: extend
  allowed_domains:
  - github.com
  - githubusercontent.com
  - pypi.org
  - pythonhosted.org
  - huggingface.co
  - hf.co
  - xethub.hf.co
  - pytorch.org
  - debian.org
  - ubuntu.com
  - r-project.org
  - youtube.com
  - googlevideo.com
  - ytimg.com
  - povray.org
  - neocities.org
  - qemu.org
  - inria.fr
  - ocaml.org
  - readthedocs.io
  - rcsb.org
  - ncbi.nlm.nih.gov
  - fpbase.org
  - corewar.co.uk
harness:
  type: codex
  config:
    auth: api_key
    model: gpt-6-luna
    reasoning_effort: max
    version: 0.156.1
    task_file: task.json
    prompt: instructions
    timeout_seconds: 900
    allow_external_tools: false
capture:
  max_candidate_bytes: 10737418240
```

### configs/securebench/terminal-bench/log-summary-date-ranges/config.yaml (sha256 `7f7bd7022d90768a`)

```yaml
schema_version: '1.0'
run:
  id: campaign-securebench-terminal-bench-log-summary-date-ranges
  output_dir: /home/mfavrett/project/securebench/runs/campaign/securebench/terminal-bench/unassigned/log-summary-date-ranges
  max_workers: 1
benchmark:
  manifest: /home/mfavrett/project/securebench/benchmarks/terminal-bench/manifest-v2.yaml
  tasks: /home/mfavrett/project/securebench/runs/campaign/configs/securebench/terminal-bench/log-summary-date-ranges/task.jsonl
docker:
  memory_limit: 2048m
network_policy:
  mode: extend
  allowed_domains:
  - github.com
  - githubusercontent.com
  - pypi.org
  - pythonhosted.org
  - huggingface.co
  - hf.co
  - xethub.hf.co
  - pytorch.org
  - debian.org
  - ubuntu.com
  - r-project.org
  - youtube.com
  - googlevideo.com
  - ytimg.com
  - povray.org
  - neocities.org
  - qemu.org
  - inria.fr
  - ocaml.org
  - readthedocs.io
  - rcsb.org
  - ncbi.nlm.nih.gov
  - fpbase.org
  - corewar.co.uk
harness:
  type: codex
  config:
    auth: api_key
    model: gpt-6-luna
    reasoning_effort: max
    version: 0.156.1
    task_file: task.json
    prompt: instructions
    timeout_seconds: 900
    allow_external_tools: false
capture:
  max_candidate_bytes: 10737418240
```

### configs/securebench/terminal-bench/mteb-leaderboard/config.yaml (sha256 `0db1a5d5cb23eb04`)

```yaml
schema_version: '1.0'
run:
  id: campaign-securebench-terminal-bench-mteb-leaderboard
  output_dir: /home/mfavrett/project/securebench/runs/campaign/securebench/terminal-bench/unassigned/mteb-leaderboard
  max_workers: 1
benchmark:
  manifest: /home/mfavrett/project/securebench/benchmarks/terminal-bench/manifest-v2.yaml
  tasks: /home/mfavrett/project/securebench/runs/campaign/configs/securebench/terminal-bench/mteb-leaderboard/task.jsonl
docker:
  memory_limit: 4096m
network_policy:
  mode: extend
  allowed_domains:
  - github.com
  - githubusercontent.com
  - pypi.org
  - pythonhosted.org
  - huggingface.co
  - hf.co
  - xethub.hf.co
  - pytorch.org
  - debian.org
  - ubuntu.com
  - r-project.org
  - youtube.com
  - googlevideo.com
  - ytimg.com
  - povray.org
  - neocities.org
  - qemu.org
  - inria.fr
  - ocaml.org
  - readthedocs.io
  - rcsb.org
  - ncbi.nlm.nih.gov
  - fpbase.org
  - corewar.co.uk
harness:
  type: codex
  config:
    auth: api_key
    model: gpt-6-luna
    reasoning_effort: max
    version: 0.156.1
    task_file: task.json
    prompt: instructions
    timeout_seconds: 3600
    allow_external_tools: false
capture:
  max_candidate_bytes: 10737418240
```

### configs/securebench/terminal-bench/mteb-retrieve/config.yaml (sha256 `a4ce4780d5f21022`)

```yaml
schema_version: '1.0'
run:
  id: campaign-securebench-terminal-bench-mteb-retrieve
  output_dir: /home/mfavrett/project/securebench/runs/campaign/securebench/terminal-bench/unassigned/mteb-retrieve
  max_workers: 1
benchmark:
  manifest: /home/mfavrett/project/securebench/benchmarks/terminal-bench/manifest-v2.yaml
  tasks: /home/mfavrett/project/securebench/runs/campaign/configs/securebench/terminal-bench/mteb-retrieve/task.jsonl
docker:
  memory_limit: 2048m
network_policy:
  mode: extend
  allowed_domains:
  - github.com
  - githubusercontent.com
  - pypi.org
  - pythonhosted.org
  - huggingface.co
  - hf.co
  - xethub.hf.co
  - pytorch.org
  - debian.org
  - ubuntu.com
  - r-project.org
  - youtube.com
  - googlevideo.com
  - ytimg.com
  - povray.org
  - neocities.org
  - qemu.org
  - inria.fr
  - ocaml.org
  - readthedocs.io
  - rcsb.org
  - ncbi.nlm.nih.gov
  - fpbase.org
  - corewar.co.uk
harness:
  type: codex
  config:
    auth: api_key
    model: gpt-6-luna
    reasoning_effort: max
    version: 0.156.1
    task_file: task.json
    prompt: instructions
    timeout_seconds: 1800
    allow_external_tools: false
capture:
  max_candidate_bytes: 10737418240
```

### configs/securebench/terminal-bench/protein-assembly/config.yaml (sha256 `4ba6d328e3101833`)

```yaml
schema_version: '1.0'
run:
  id: campaign-securebench-terminal-bench-protein-assembly
  output_dir: /home/mfavrett/project/securebench/runs/campaign/securebench/terminal-bench/unassigned/protein-assembly
  max_workers: 1
benchmark:
  manifest: /home/mfavrett/project/securebench/benchmarks/terminal-bench/manifest-v2.yaml
  tasks: /home/mfavrett/project/securebench/runs/campaign/configs/securebench/terminal-bench/protein-assembly/task.jsonl
docker:
  memory_limit: 4096m
network_policy:
  mode: extend
  allowed_domains:
  - github.com
  - githubusercontent.com
  - pypi.org
  - pythonhosted.org
  - huggingface.co
  - hf.co
  - xethub.hf.co
  - pytorch.org
  - debian.org
  - ubuntu.com
  - r-project.org
  - youtube.com
  - googlevideo.com
  - ytimg.com
  - povray.org
  - neocities.org
  - qemu.org
  - inria.fr
  - ocaml.org
  - readthedocs.io
  - rcsb.org
  - ncbi.nlm.nih.gov
  - fpbase.org
  - corewar.co.uk
harness:
  type: codex
  config:
    auth: api_key
    model: gpt-6-luna
    reasoning_effort: max
    version: 0.156.1
    task_file: task.json
    prompt: instructions
    timeout_seconds: 1800
    allow_external_tools: false
capture:
  max_candidate_bytes: 10737418240
```

### configs/securebench/terminal-bench/raman-fitting/config.yaml (sha256 `22a827829252926c`)

```yaml
schema_version: '1.0'
run:
  id: campaign-securebench-terminal-bench-raman-fitting
  output_dir: /home/mfavrett/project/securebench/runs/campaign/securebench/terminal-bench/unassigned/raman-fitting
  max_workers: 1
benchmark:
  manifest: /home/mfavrett/project/securebench/benchmarks/terminal-bench/manifest-v2.yaml
  tasks: /home/mfavrett/project/securebench/runs/campaign/configs/securebench/terminal-bench/raman-fitting/task.jsonl
docker:
  memory_limit: 2048m
network_policy:
  mode: extend
  allowed_domains:
  - github.com
  - githubusercontent.com
  - pypi.org
  - pythonhosted.org
  - huggingface.co
  - hf.co
  - xethub.hf.co
  - pytorch.org
  - debian.org
  - ubuntu.com
  - r-project.org
  - youtube.com
  - googlevideo.com
  - ytimg.com
  - povray.org
  - neocities.org
  - qemu.org
  - inria.fr
  - ocaml.org
  - readthedocs.io
  - rcsb.org
  - ncbi.nlm.nih.gov
  - fpbase.org
  - corewar.co.uk
harness:
  type: codex
  config:
    auth: api_key
    model: gpt-6-luna
    reasoning_effort: max
    version: 0.156.1
    task_file: task.json
    prompt: instructions
    timeout_seconds: 900
    allow_external_tools: false
capture:
  max_candidate_bytes: 10737418240
```

### configs/securebench/terminal-bench/rstan-to-pystan/config.yaml (sha256 `8f9bd140502a5c26`)

```yaml
schema_version: '1.0'
run:
  id: campaign-securebench-terminal-bench-rstan-to-pystan
  output_dir: /home/mfavrett/project/securebench/runs/campaign/securebench/terminal-bench/unassigned/rstan-to-pystan
  max_workers: 1
benchmark:
  manifest: /home/mfavrett/project/securebench/benchmarks/terminal-bench/manifest-v2.yaml
  tasks: /home/mfavrett/project/securebench/runs/campaign/configs/securebench/terminal-bench/rstan-to-pystan/task.jsonl
docker:
  memory_limit: 8192m
network_policy:
  mode: extend
  allowed_domains:
  - github.com
  - githubusercontent.com
  - pypi.org
  - pythonhosted.org
  - huggingface.co
  - hf.co
  - xethub.hf.co
  - pytorch.org
  - debian.org
  - ubuntu.com
  - r-project.org
  - youtube.com
  - googlevideo.com
  - ytimg.com
  - povray.org
  - neocities.org
  - qemu.org
  - inria.fr
  - ocaml.org
  - readthedocs.io
  - rcsb.org
  - ncbi.nlm.nih.gov
  - fpbase.org
  - corewar.co.uk
harness:
  type: codex
  config:
    auth: api_key
    model: gpt-6-luna
    reasoning_effort: max
    version: 0.156.1
    task_file: task.json
    prompt: instructions
    timeout_seconds: 1800
    allow_external_tools: false
capture:
  max_candidate_bytes: 10737418240
```

### configs/securebench/terminal-bench/sqlite-db-truncate/config.yaml (sha256 `9173ce012ebd7526`)

```yaml
schema_version: '1.0'
run:
  id: campaign-securebench-terminal-bench-sqlite-db-truncate
  output_dir: /home/mfavrett/project/securebench/runs/campaign/securebench/terminal-bench/unassigned/sqlite-db-truncate
  max_workers: 1
benchmark:
  manifest: /home/mfavrett/project/securebench/benchmarks/terminal-bench/manifest-v2.yaml
  tasks: /home/mfavrett/project/securebench/runs/campaign/configs/securebench/terminal-bench/sqlite-db-truncate/task.jsonl
docker:
  memory_limit: 2048m
network_policy:
  mode: extend
  allowed_domains:
  - github.com
  - githubusercontent.com
  - pypi.org
  - pythonhosted.org
  - huggingface.co
  - hf.co
  - xethub.hf.co
  - pytorch.org
  - debian.org
  - ubuntu.com
  - r-project.org
  - youtube.com
  - googlevideo.com
  - ytimg.com
  - povray.org
  - neocities.org
  - qemu.org
  - inria.fr
  - ocaml.org
  - readthedocs.io
  - rcsb.org
  - ncbi.nlm.nih.gov
  - fpbase.org
  - corewar.co.uk
harness:
  type: codex
  config:
    auth: api_key
    model: gpt-6-luna
    reasoning_effort: max
    version: 0.156.1
    task_file: task.json
    prompt: instructions
    timeout_seconds: 900
    allow_external_tools: false
capture:
  max_candidate_bytes: 10737418240
```

### configs/securebench/terminal-bench/vulnerable-secret/config.yaml (sha256 `f911875ddb5b39be`)

```yaml
schema_version: '1.0'
run:
  id: campaign-securebench-terminal-bench-vulnerable-secret
  output_dir: /home/mfavrett/project/securebench/runs/campaign/securebench/terminal-bench/unassigned/vulnerable-secret
  max_workers: 1
benchmark:
  manifest: /home/mfavrett/project/securebench/benchmarks/terminal-bench/manifest-v2.yaml
  tasks: /home/mfavrett/project/securebench/runs/campaign/configs/securebench/terminal-bench/vulnerable-secret/task.jsonl
docker:
  memory_limit: 2048m
network_policy:
  mode: extend
  allowed_domains:
  - github.com
  - githubusercontent.com
  - pypi.org
  - pythonhosted.org
  - huggingface.co
  - hf.co
  - xethub.hf.co
  - pytorch.org
  - debian.org
  - ubuntu.com
  - r-project.org
  - youtube.com
  - googlevideo.com
  - ytimg.com
  - povray.org
  - neocities.org
  - qemu.org
  - inria.fr
  - ocaml.org
  - readthedocs.io
  - rcsb.org
  - ncbi.nlm.nih.gov
  - fpbase.org
  - corewar.co.uk
harness:
  type: codex
  config:
    auth: api_key
    model: gpt-6-luna
    reasoning_effort: max
    version: 0.156.1
    task_file: task.json
    prompt: instructions
    timeout_seconds: 900
    allow_external_tools: false
capture:
  max_candidate_bytes: 10737418240
```

### configs/securebench/terminal-bench/write-compressor/config.yaml (sha256 `a7f5472957fc2499`)

```yaml
schema_version: '1.0'
run:
  id: campaign-securebench-terminal-bench-write-compressor
  output_dir: /home/mfavrett/project/securebench/runs/campaign/securebench/terminal-bench/unassigned/write-compressor
  max_workers: 1
benchmark:
  manifest: /home/mfavrett/project/securebench/benchmarks/terminal-bench/manifest-v2.yaml
  tasks: /home/mfavrett/project/securebench/runs/campaign/configs/securebench/terminal-bench/write-compressor/task.jsonl
docker:
  memory_limit: 2048m
network_policy:
  mode: extend
  allowed_domains:
  - github.com
  - githubusercontent.com
  - pypi.org
  - pythonhosted.org
  - huggingface.co
  - hf.co
  - xethub.hf.co
  - pytorch.org
  - debian.org
  - ubuntu.com
  - r-project.org
  - youtube.com
  - googlevideo.com
  - ytimg.com
  - povray.org
  - neocities.org
  - qemu.org
  - inria.fr
  - ocaml.org
  - readthedocs.io
  - rcsb.org
  - ncbi.nlm.nih.gov
  - fpbase.org
  - corewar.co.uk
harness:
  type: codex
  config:
    auth: api_key
    model: gpt-6-luna
    reasoning_effort: max
    version: 0.156.1
    task_file: task.json
    prompt: instructions
    timeout_seconds: 900
    allow_external_tools: false
capture:
  max_candidate_bytes: 10737418240
```

## Native commands (condition A)

Built by `tools/native_baseline/campaign.py:native_command`; example:

```
runs/campaign/native-venv/bin/pier run -p runs/campaign/upstream/deep-swe/tasks/cattrs-partial-structuring-recovery -m openai/gpt-6-luna --ak version=0.156.1 --ak reasoning_effort=max -e docker -o <run dir> -n 1 -y -q --env-file .env --agent-import-path tools.native_baseline.codex_agents:PierCodexCapture --ak base_commit=6bc4708fb9b2ac52d9a18997e923da6a58916102
runs/campaign/native-venv/bin/harbor run -p runs/campaign/upstream/tb2/chess-best-move -m openai/gpt-6-luna --ak version=0.156.1 --ak reasoning_effort=max -e docker -o <run dir> -n 1 -y -q --env-file .env --agent-import-path tools.native_baseline.codex_agents:HarborCodexCapture --ak capture_paths=/app/move.txt
```

## Addendum: replacement row (2026-09-25, 19:54–20:58)

`deep-swe/obsidian-linter-auto-table-of-contents` replaced
`deep-swe/returns-validated-error-accumulation` in the admitted set (ISSUES
I-36) and was run alone, with the pins above. Upstream image
`public.ecr.aws/d3j8x8q7/swe-bench-202605:kh74j15mp1vrxx737y8b47tc8h832a37-v1.1`
resolved to the pinned
`sha256:56d3ffcde2ca373ffa0107f830b243d66191020f7021806acc8d609148518092`.
Upstream limits: agent 5400 s, verifier 1800 s, 2 CPUs, 8192 MB, no network.

```yaml
schema_version: '1.0'
run:
  id: campaign-securebench-deep-swe-obsidian-linter-auto-table-of-contents
  output_dir: /home/mfavrett/project/securebench/runs/campaign/securebench/deep-swe/unassigned/obsidian-linter-auto-table-of-contents
  max_workers: 1
benchmark:
  manifest: /home/mfavrett/project/securebench/benchmarks/deep-swe/manifest-v2.yaml
  tasks: /home/mfavrett/project/securebench/runs/campaign/configs/securebench/deep-swe/obsidian-linter-auto-table-of-contents/task.jsonl
docker:
  memory_limit: 8192m
harness:
  type: codex
  config:
    auth: api_key
    model: gpt-6-luna
    reasoning_effort: max
    version: 0.156.1
    task_file: task.json
    prompt: instructions
    timeout_seconds: 5400
    allow_external_tools: false
```

