# SWE-bench Pro

This SecureBench pack contains all 731 rows from the public `test` split of
`ScaleAI/SWE-bench_Pro`.

The pack is self-contained after cloning SecureBench: every row includes its
task, trusted gold patch, candidate policy, and the matching upstream test
runner/parser. Runtime repository environments are pulled from the official
`jefzda/sweap-images` Docker Hub repository using each dataset row's
`dockerhub_tag`.

## Linux requirements

- Docker with enough free disk space for the selected per-task images.
- An x86-64 Linux host, or an environment capable of running `linux/amd64`
  images. The upstream images are `linux/amd64`.
- Generous container limits. SWE-bench Pro's official evaluator allows up to
  30 GiB of memory, while SecureBench defaults to 1 GiB. Set limits appropriate
  for the repository you are running, for example:

  ```bash
  export SECUREBENCH_DOCKER_MEM_LIMIT=30g
  export SECUREBENCH_DOCKER_PIDS_LIMIT=4096
  ```

Install and run from a fresh clone:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m securebench.cli run \
  --config benchmarks/swe-bench-pro/tester-codex.yaml \
  --limit 1
```

The supplied tester config sets `docker.max_cached_images: 2`. After every two
distinct task images finish, SecureBench removes those exact image references
and continues; it does not run a global Docker prune or remove unrelated
images. Change the YAML value or override it for one run:

```bash
.venv/bin/python -m securebench.cli run \
  --config benchmarks/swe-bench-pro/tester-codex.yaml \
  --max-cached-images 5
```

It also sets `run.max_workers: 2`, so two rows can produce candidates and run
verification at the same time. Change that YAML value or override it per run:

```bash
.venv/bin/python -m securebench.cli run \
  --config benchmarks/swe-bench-pro/tester-codex.yaml \
  --workers 4
```

Completed rows are written as they finish, so JSONL order can differ from the
source task order. Writes and image cleanup remain serialized. An image is not
eligible for cleanup until every scheduled row that uses it has finished, so
higher worker counts also increase peak Docker storage and memory requirements.

If a run ends with fewer images than the configured batch size, that final
partial batch remains cached for reuse.

Verification networking is enabled because upstream runners install or start
repository-specific dependencies. The agent still receives no trusted test
runner, expected-test list, test patch, or gold patch.

## Reproducible import

The committed `tasks.jsonl` is generated from pinned revisions of both the
Hugging Face dataset and the official evaluation repository:

```bash
python3 tools/import_swe_bench_pro.py
```

The importer refuses to regenerate if the dataset revision changes, forcing an
explicit review before accepting upstream row or evaluator changes.
