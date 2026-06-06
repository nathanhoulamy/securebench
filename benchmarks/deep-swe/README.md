# Deep SWE

Five deterministic random `repo_patch` tasks derived from Datacurve's Deep SWE task repository.

Source: https://github.com/datacurve-ai/deep-swe at `578129c4334f6656a92a1c629af63a530596f169`.

Pack notes:

- Uses DeepSWE's prebuilt Harbor/Pier Docker images.
- Exposes only each task's public instruction to the agent.
- Keeps `tests/test.patch` and `solution/solution.patch` as evaluator-only data.
- Runs the DeepSWE test entrypoint after SecureBench applies the hidden test patch.
