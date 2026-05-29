# DeepSWE First 3

Three `repo_patch` tasks derived from the first three rows in Datacurve's DeepSWE `tasks/manifest.json`.

Source: https://github.com/datacurve-ai/deep-swe at `2f0f41255912c9199a1dafa405ca068cd903624b`.

Pack notes:

- Uses DeepSWE's prebuilt Harbor/Pier Docker images.
- Exposes only each task's public instruction to the agent.
- Keeps `tests/test.patch` and `solution/solution.patch` as evaluator-only data.
- Runs the DeepSWE test entrypoint after SecureBench applies the hidden test patch.
