# Terminal-Bench 2.0

This benchmark pack ports 71 of the 89 tasks from
`harbor-framework/terminal-bench-2` to isolated SecureBench `terminal_task`
rows.

Pack notes:

- Audits all 89 tasks from upstream commit
  `2fd12b88aafdd04a52c298e3940bcb189f9766d6`, excludes the 18 incompatible
  rows documented below, and emits the remaining 71 in deterministic task-id
  order.
- Copies each upstream `environment/` directory to `docker/<task>/`.
- Copies upstream `tests/` into SecureBench hidden evaluator assets.
- Omits upstream `solution/` directories from the benchmark pack.
- Enables `environment.materialize_workdir_from_image` for every row, because
  Terminal-Bench task images place starter files in `/app`.
- Declares each committed Docker context through `environment.build_context`,
  allowing SecureBench to build a missing task image on first use.

## Excluded upstream rows

Terminal-Bench normally runs its verifier inside the agent container. That
design couples some rows to mutable system directories, agent-installed global
packages, or processes left running by the agent. SecureBench deliberately does
not reproduce that poorly isolated design: the agent sandbox is destroyed and
the hidden checker runs in a separate, trusted verification sandbox using only
the `/app` candidate handoff.

The following 18 upstream rows cannot preserve their required candidate state
through that handoff and are therefore excluded from this pack and its score:

- `adaptive-rejection-sampler` — installs R outside `/app` and invokes it during verification.
- `build-cython-ext` — installs the candidate into the system Python environment.
- `build-pmars` — installs the candidate under `/usr/local/bin`.
- `build-pov-ray` — installs the candidate under `/usr/local/bin`.
- `caffe-cifar-10` — relies on agent-installed system build and runtime packages.
- `compile-compcert` — creates the candidate under `/tmp/CompCert`.
- `configure-git-webserver` — relies on live SSH/HTTP services and `/git` state.
- `git-multibranch` — relies on live SSH/HTTPS services and `/git` state.
- `hf-model-inference` — relies on a server process left running by the agent.
- `install-windows-3.11` — relies on a QEMU process left running by the agent.
- `kv-store-grpc` — relies on a live gRPC process and agent-installed packages.
- `mailman` — relies on live services and state under `/etc` and `/var`.
- `mcmc-sampling-stan` — installs RStan into the system R environment.
- `nginx-request-logging` — relies on nginx plus state under `/etc` and `/var`.
- `pypi-server` — relies on a package-server process left running by the agent.
- `qemu-alpine-ssh` — relies on QEMU and SSH processes left running by the agent.
- `qemu-startup` — relies on a QEMU process left running by the agent.
- `sqlite-with-gcov` — installs the candidate executable into system `PATH` outside `/app`.

These exclusions are intentional. Reintroducing one requires redesigning that
row around an explicit untrusted artifact or an externally driven service
protocol while keeping checker code in the verification sandbox.

Regenerate the pack from a local checkout:

```bash
python3 tools/import_terminal_bench_2.py --source /path/to/terminal-bench-2
```

Or let the importer clone the pinned upstream revision:

```bash
python3 tools/import_terminal_bench_2.py
```

## Linux requirements

- Docker Engine with permission to build and run containers.
- An x86-64 host is recommended. Several upstream tasks use architecture-
  specific toolchains, emulators, or prebuilt artifacts.
- Enough RAM and disk for the selected worker count. Some individual task
  images are large and some verifiers have multi-gigabyte workloads.

From a fresh clone, install SecureBench and run directly:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m securebench.cli run \
  --config benchmarks/terminal-bench/tester-codex.yaml \
  --limit 1
```

SecureBench builds a row's local image automatically if it is missing. To
prebuild every image instead, use:

```bash
for d in benchmarks/terminal-bench/docker/*; do
  task=$(basename "$d")
  docker build -t "securebench-terminal-bench-${task}:2fd12b88aafd" "$d"
done
```

The supplied tester config runs two rows concurrently and removes each batch of
two finished, no-longer-needed task images. Override either value per run:

```bash
.venv/bin/python -m securebench.cli run \
  --config benchmarks/terminal-bench/tester-codex.yaml \
  --workers 4 \
  --max-cached-images 4
```

Verifier note: upstream Terminal-Bench 2.0 `test.sh` scripts are adapted to use
SecureBench's hidden evaluator mount path and verifier log directory. Many
upstream scripts still use `uvx` to provision checker dependencies, so
`tester-codex.yaml` sets `verification.allow_network: true` for verifier-only
dependency downloads. The harness also permits the upstream task dependency
domains used for package installation and source/model downloads; provider
credentials still stay behind the relay, and external agent tools remain
disabled.
