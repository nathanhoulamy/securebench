# External Adversary Contract

External adversaries are ordinary commands run inside the benchmark image with
the same public workspace visibility as bundled adversaries.

Configure one with:

```yaml
adversary:
  mode: external
  profile: leak_probe
  command: ["python3", "/workspace/my_adversary.py"]
```

The command receives these environment variables:

- `BERKELEY_TASK_FILE`: JSON file containing the agent-visible public task payload.
- `BERKELEY_PROFILE`: requested attack profile.
- `BERKELEY_MODE`: always `external`.
- `BERKELEY_TRACE_FILE`: path where the adversary should write JSON trace data.
- `BERKELEY_TASK_TYPE`: current SecureBench family, currently `repo_patch` or `terminal_task`.
- `SECUREBENCH_WORKSPACE`: mounted candidate workspace root.
- `SECUREBENCH_WORKDIR`: family-specific working directory.
- `OPENAI_BASE_URL` and dummy OpenAI keys when relay-backed provider access is enabled.

For relay-backed provider access in an external adversary config, set:

```yaml
provider:
  enabled: true
  model: gpt-5.4-mini
  allow_external_tools: false
```

The real provider key must still be set only on the host. The container receives
dummy keys and must call the provider through `OPENAI_BASE_URL`.

The command should leave a normal SecureBench candidate:

- `repo_patch`: modify the repository so SecureBench can collect the final git diff.
- `terminal_task`: modify the workspace so SecureBench can verify final state.

The command should write trace JSON to `BERKELEY_TRACE_FILE`. Use this shape:

```json
{
  "profile": "custom",
  "actions": ["what the adversary tried"],
  "observations": [],
  "errors": [],
  "violations": []
}
```

Any non-empty `violations` array means the adversary observed a framework-level
security failure, such as reading hidden data or seeing a real provider key.

Use `errors` for adversary/runtime problems such as failed provider calls,
invalid model output, or tool crashes. These are not security findings by
themselves.
