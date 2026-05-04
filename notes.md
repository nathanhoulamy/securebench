# SecureBench Notes

## Agent Payload Task IDs

`agent_payload()` does not strictly need to include the task ID for the agent to
solve a task. The ID is mainly useful for orchestration: logs, transcripts,
artifacts, retries, and evaluator joins can all reference the same stable task.

Including IDs in the agent-visible payload may weaken benchmark hygiene if the
ID itself is a clue, such as a public benchmark row ID or GitHub issue-style
identifier. This matters most when network access is enabled or when evaluating
against benchmarks that may be memorized.

A cleaner split is to keep the task ID in an evaluator/orchestration envelope
and omit it from the agent-visible payload:

```python
{
    "task_id": task.id,
    "agent_payload": task.agent_payload(),
}
```

This preserves traceability without making the identifier part of the prompt
seen by the agent.
