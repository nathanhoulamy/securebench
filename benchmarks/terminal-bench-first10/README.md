# Terminal-Bench First 10

First ten `original-tasks` from `harbor-framework/terminal-bench`, converted to SecureBench `terminal_task` rows.

Converted task IDs:

- `path-tracing`
- `model-extraction-relu-logits`
- `video-processing`
- `dna-assembly`
- `gomoku-planner`
- `implement-eigenvectors-from-eigenvalues-research-paper`
- `swe-bench-astropy-1`
- `regex-log`
- `large-scale-text-editing`
- `stable-parallel-kmeans`

Rows that rely on files generated inside the task image use
`environment.materialize_workdir_from_image: true`; SecureBench copies the image
workdir into the mounted workspace before the harness runs.

## Conversion Notes

SecureBench runs terminal tasks by mounting a host workspace over the configured
container `environment.workdir`. That is fine for tasks whose starter files are
declared as public assets, but it hides any files that the upstream
Terminal-Bench image placed in the workdir at build time. Three of these ten
tasks depend on image-prepared workdirs:

- `implement-eigenvectors-from-eigenvalues-research-paper`: `/app` contains the
  cloned `quimb` repository and the PDF referenced by the prompt.
- `swe-bench-astropy-1`: `/testbed` contains the checked-out Astropy repository
  and its conda test environment.
- `large-scale-text-editing`: `/app` contains the generated starter CSV files.

Those rows opt into `environment.materialize_workdir_from_image: true`, which
asks the harness to copy the image workdir into the host workspace before
mounting that workspace into the agent container. This preserves the upstream
task shape without changing the dataset prompt or requiring agents to download
setup files at runtime.

Materialized image workdirs are public starter state. Do not place hidden tests,
answers, credentials, provider configuration, or trusted verifier artifacts in a
task image workdir when this flag is enabled. Use SecureBench `assets[]` for
small intentional public files and `eval.*` resources under `hidden/` for
verifier-only files.

The hidden verifier scripts were also adjusted for SecureBench's verifier
sandbox model. They run without network access, so test-time downloads and
package installs were moved into the task images. The Astropy task keeps its
tester-provided regression test patch inside the hidden verifier script and
applies it only when checking the candidate. The large CSV task regenerates
`input.csv` during verification and creates `expected.csv` inside the hidden
tests, so candidate code cannot rely on a modified workspace copy.

The `path-tracing` checker uses `chroot` to run the compiled candidate program
without access to the reference image. That row declares
`eval.needed_commands: ["chroot"]`; the provided Codex tester config opts into
dangerous verifier commands so SecureBench grants `SYS_CHROOT` only to the
verifier sandbox. Agent sandboxes still run without this allowance.

Build the local task images before running:

```bash
for d in benchmarks/terminal-bench-first10/docker/*; do
  task=$(basename "$d")
  docker build -t "securebench-terminal-bench-first10-${task}:latest" "$d"
done
```

Run with Codex:

```bash
.venv/bin/python -m securebench.cli run \
  --config benchmarks/terminal-bench-first10/tester-codex.yaml \
  --limit 10
```
