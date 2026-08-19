# SWE-bench Pro conversion source

This directory preserves the 731 rows previously imported from the public
`ScaleAI/SWE-bench_Pro` test split. `manifest.yaml` and `tasks.jsonl` use the
pre-v2 SecureBench format and are conversion inputs, not executable benchmark
packs. The strict v2 loader intentionally rejects them.

A runnable v2 pack must replace hidden test execution with declared candidate,
resource, check, parser, and host-Oracle contracts. The old importer was
removed because regenerating more rows in the obsolete format was misleading.
