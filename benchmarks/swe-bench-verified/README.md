# SWE-bench Verified conversion source

This directory preserves 500 source rows imported from
`SWE-bench/SWE-bench_Verified`. `manifest.yaml` and `tasks.jsonl` use the
pre-v2 SecureBench format and are retained only as conversion material. They
cannot be passed to the strict v2 runner.

Each selected row must be redesigned around the v2 split-verification schema
before it becomes executable. The obsolete-format importer was removed.
