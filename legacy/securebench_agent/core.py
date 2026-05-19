"""Tool-mediated workspace agent loop."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Set, Tuple, Union

from securebench_agent.tools import TOOL_SCHEMAS, WorkspaceTools


SYSTEM_PROMPT = """You are a repository repair agent running inside a checked-out Git repository.
Use tools to inspect and modify the repository. Fix the issue described by the task file.
Do not ask for hidden tests, gold patches, private environment variables, or external secrets.
Prefer small, auditable patches. Call finish when the repository changes are complete."""


class ToolModel(Protocol):
    """Model interface used by the workspace agent."""

    def complete(self, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Return the next assistant message, optionally containing tool calls."""


@dataclass(frozen=True)
class AgentRunResult:
    """Summary of one workspace agent run."""

    finished: bool
    steps: int
    summary: str = ""
    messages: List[Dict[str, Any]] = field(default_factory=list)


class WorkspaceAgent:
    """Run a small tool-calling loop against a repository workspace."""

    def __init__(
        self,
        *,
        repo_root: Union[str, Path],
        task_file: Union[str, Path],
        model: ToolModel,
        max_steps: int = 40,
        max_tool_output: int = 12_000,
        command_timeout: float = 60.0,
        command_allow: Optional[Set[str]] = None,
        command_deny: Optional[Set[str]] = None,
    ) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.task_file = Path(task_file)
        self.model = model
        self.max_steps = max_steps
        self.tools = WorkspaceTools(
            self.repo_root,
            max_output=max_tool_output,
            command_timeout=command_timeout,
            command_allow=command_allow,
            command_deny=command_deny,
        )

    def run(self) -> AgentRunResult:
        task_text = self.tools.read_file(str(self.task_file), max_lines=2_000)["content"]
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _task_prompt(task_text)},
        ]

        summary = ""
        finished = False
        steps = 0

        for steps in range(1, self.max_steps + 1):
            assistant_message = self.model.complete(messages, TOOL_SCHEMAS)
            messages.append(assistant_message)

            tool_calls = assistant_message.get("tool_calls") or []
            if not tool_calls:
                summary = str(assistant_message.get("content") or "")
                finished = True
                break

            for tool_call in tool_calls:
                tool_name, arguments = _parse_tool_call(tool_call)
                if tool_name == "finish":
                    summary = str(arguments.get("summary", ""))
                    tool_result = {"ok": True, "finished": True, "summary": summary}
                    finished = True
                else:
                    tool_result = self.tools.run_tool(tool_name, arguments)

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": str(tool_call.get("id", f"step-{steps}")),
                        "content": json.dumps(tool_result, sort_keys=True),
                    }
                )

            if finished:
                break

        return AgentRunResult(
            finished=finished,
            steps=steps,
            summary=summary,
            messages=messages,
        )


def _task_prompt(task_text: str) -> str:
    return (
        "Task file contents follow. Use repository tools to inspect and edit files, "
        "then call finish.\n\n"
        f"{task_text}"
    )


def _parse_tool_call(tool_call: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    function = tool_call.get("function")
    if not isinstance(function, dict):
        raise ValueError("Tool call must contain a function object")

    name = function.get("name")
    if not isinstance(name, str) or not name:
        raise ValueError("Tool call function.name must be a non-empty string")

    raw_arguments = function.get("arguments", "{}")
    if isinstance(raw_arguments, dict):
        arguments = raw_arguments
    elif isinstance(raw_arguments, str):
        try:
            loaded = json.loads(raw_arguments or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError(f"Tool call {name!r} arguments must be valid JSON") from exc
        if not isinstance(loaded, dict):
            raise ValueError(f"Tool call {name!r} arguments must decode to an object")
        arguments = loaded
    else:
        raise ValueError(f"Tool call {name!r} arguments must be a JSON string or object")

    return name, arguments
