# DeepSWE conversion source

This directory preserves five rows derived from Datacurve's DeepSWE repository
at revision `578129c4334f6656a92a1c629af63a530596f169`.

The checked-in `manifest.yaml` and `tasks.jsonl` use the pre-v2 format and are
conversion inputs only. In particular, their hidden test-patch execution is
not a valid strict split-verification contract and the v2 loader rejects it.
