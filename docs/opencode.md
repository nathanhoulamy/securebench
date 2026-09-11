# OpenCode harness

Select `harness.type: opencode` to run OpenCode in the Agent environment. The
initial provider is abliteration.ai, using its OpenAI-compatible Chat Completions
API. Set `ABLIT_KEY` in the host environment through your normal secret-management
workflow. Do not put the key in tester YAML or task assets. SecureBench supplies
it only to the provider relay; OpenCode receives a dummy key.

```sh
.venv/bin/python -m securebench.cli run \
  --config benchmarks/terminal-bench/tester-opencode.yaml
```

The example defaults to `provider: abliteration`, `model: abliterated-model`,
`version: "1.18.30"`, `task_file: task.json`, and a 900-second timeout. `model` is
the upstream model ID; SecureBench prefixes it with the configured provider for
OpenCode. Versions must be exact releases, not `latest`. Other versions require
compatibility testing before use in admitted runs.

`allowed_domains` defaults to an empty list. Add only resources permitted by the
benchmark resource policy. Provider access goes through the relay and does not
require adding `api.abliteration.ai` here. `allow_external_tools` defaults to
false; local function tools remain enabled. Harness-controlled OpenCode, XDG,
HOME, PATH, proxy settings and known provider credentials are removed from
`harness.env` forwarding.

The harness uses a read-only Linux tooling cache under
`$SECUREBENCH_AGENT_CACHE/opencode`, or `~/.cache/securebench/agents/opencode`.
Installation occurs outside the Agent. The target image must run the bundled
Linux binary; incompatible images fail preflight. Sharing, automatic updates,
model-catalog fetching, external plugins, and project configuration loading are
disabled. Configuration is an operational default, not a security boundary:
Docker and the host-side relay enforce resource access.

Git patches and file bundles use the existing stopped-workspace capture.
Filesystem overlays use the existing bounded capture path, with OpenCode state
in bounded `/tmp` storage; the repository's native-Linux qualification gate still
applies. No OpenCode logs or tool results are treated as correctness verdicts.

## Validation status

OpenCode 1.18.30's generated configuration was accepted by the locally installed
CLI. Unit tests exercise configuration, credential filtering, relay restrictions,
capture routing, and failure cleanup. Docker runtime and live abliteration.ai
qualification remain **qualification-pending**: the development host's Docker
daemon was unavailable and `ABLIT_KEY` was not set. This is not an Approved
benchmark conversion.

Run the controlled Docker smoke test with:

```sh
SECUREBENCH_OPENCODE_SMOKE=1 .venv/bin/python -m pytest tests/test_opencode_smoke.py -q -rs
```

It installs the pinned CLI, uses a synthetic streaming provider on an isolated
Docker bridge to request a file write, stops the Agent, captures bounded bytes,
and replays them into a fresh directory. It uses no live API key. This tests
runtime compatibility and file-bundle replay, not universal isolation or complete
benchmark qualification. Live provider testing additionally requires a running
Docker daemon and host-side `ABLIT_KEY`.

## Adding providers

Add a reviewed entry to `OPENCODE_PROVIDERS` in
`securebench/harnesses/opencode.py`: bundled OpenCode transport package, default
model, and `ProviderRelaySpec` containing the upstream host, credential source,
wire protocol, methods, paths, and client tool types. The relay's `provider`
field names the wire protocol (`openai` or `anthropic`), while the mapping key
names the service. Add endpoint/authentication tests and run the runtime smoke
against that provider. Subscription refresh and credential storage must stay
host-side; never mount a user's OpenCode auth directory into the Agent. Unknown
providers fail closed.
