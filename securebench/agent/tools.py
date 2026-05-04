"""Repository-local tools exposed to the minimal workspace agent."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from securebench.policy import CommandPolicy, PolicyViolation, normalize_command


DEFAULT_COMMAND_ALLOW = {"git", "python", "python3", "pytest"}
DEFAULT_COMMAND_DENY = {"curl", "wget", "ssh", "scp", "rsync"}


TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a bounded line range from a repository file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "start_line": {"type": "integer", "minimum": 1},
                    "max_lines": {"type": "integer", "minimum": 1, "maximum": 500},
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search",
            "description": "Search repository text using ripgrep and return bounded matches.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "path": {"type": "string"},
                    "max_matches": {"type": "integer", "minimum": 1, "maximum": 200},
                },
                "required": ["pattern"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List repository files under a path, optionally filtered by glob.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "glob": {"type": "string"},
                    "max_files": {"type": "integer", "minimum": 1, "maximum": 500},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "apply_patch",
            "description": "Apply a unified git diff patch to the repository.",
            "parameters": {
                "type": "object",
                "properties": {
                    "patch": {"type": "string"},
                },
                "required": ["patch"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Run an allowed command in the repository without shell expansion.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "timeout": {"type": "number", "minimum": 0.1},
                },
                "required": ["command"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finish",
            "description": "Finish the repair attempt.",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
    },
]


class WorkspaceTools:
    """Bounded file, search, patch, and command tools for one repo root."""

    def __init__(
        self,
        repo_root: str | Path,
        *,
        max_output: int = 12_000,
        command_timeout: float = 60.0,
        command_allow: set[str] | None = None,
        command_deny: set[str] | None = None,
    ) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.max_output = max_output
        self.command_timeout = command_timeout
        self.command_policy = CommandPolicy(
            allow=DEFAULT_COMMAND_ALLOW if command_allow is None else set(command_allow),
            deny=DEFAULT_COMMAND_DENY if command_deny is None else set(command_deny),
        )

    def run_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            if name == "read_file":
                return self.read_file(**arguments)
            if name == "search":
                return self.search(**arguments)
            if name == "list_files":
                return self.list_files(**arguments)
            if name == "apply_patch":
                return self.apply_patch(**arguments)
            if name == "run_command":
                return self.run_command(**arguments)
        except Exception as exc:
            return {"ok": False, "error": str(exc), "error_type": type(exc).__name__}
        return {"ok": False, "error": f"Unknown tool {name!r}", "error_type": "UnknownTool"}

    def read_file(self, path: str, start_line: int = 1, max_lines: int = 200) -> dict[str, Any]:
        target = self._resolve_path(path)
        max_lines = _bounded_int(max_lines, default=200, minimum=1, maximum=500)
        start_line = _bounded_int(start_line, default=1, minimum=1, maximum=10_000_000)

        lines = target.read_text(errors="replace").splitlines()
        start_index = start_line - 1
        selected = lines[start_index : start_index + max_lines]
        end_line = start_index + len(selected)
        truncated = start_index + max_lines < len(lines)

        return self._cap_result(
            {
                "ok": True,
                "path": self._relative(target),
                "start_line": start_line,
                "end_line": end_line,
                "truncated": truncated,
                "content": "\n".join(selected),
            }
        )

    def search(self, pattern: str, path: str = ".", max_matches: int = 50) -> dict[str, Any]:
        if not isinstance(pattern, str) or not pattern:
            raise ValueError("pattern must be a non-empty string")
        search_root = self._resolve_path(path)
        max_matches = _bounded_int(max_matches, default=50, minimum=1, maximum=200)

        completed = subprocess.run(
            [
                "rg",
                "--line-number",
                "--no-heading",
                "--color",
                "never",
                "-g",
                "!.env",
                "-g",
                "!.env.*",
                pattern,
                str(search_root),
            ],
            cwd=self.repo_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=self.command_timeout,
            env=_safe_env(),
        )
        if completed.returncode not in (0, 1):
            raise RuntimeError(completed.stderr.strip() or f"rg exited {completed.returncode}")

        matches = completed.stdout.splitlines()[:max_matches]
        return self._cap_result(
            {
                "ok": True,
                "matches": [_shorten_absolute_match(match, self.repo_root) for match in matches],
                "truncated": len(completed.stdout.splitlines()) > max_matches,
                "exit_code": completed.returncode,
            }
        )

    def list_files(self, path: str = ".", glob: str = "*", max_files: int = 200) -> dict[str, Any]:
        root = self._resolve_path(path)
        max_files = _bounded_int(max_files, default=200, minimum=1, maximum=500)
        if not isinstance(glob, str) or not glob:
            raise ValueError("glob must be a non-empty string")

        files: list[str] = []
        for candidate in sorted(root.rglob(glob)):
            if len(files) >= max_files:
                break
            if not candidate.is_file():
                continue
            relative_parts = candidate.relative_to(self.repo_root).parts
            if ".git" in relative_parts or _is_env_path(relative_parts):
                continue
            files.append(self._relative(candidate))
        return {"ok": True, "files": files, "truncated": len(files) >= max_files}

    def apply_patch(self, patch: str) -> dict[str, Any]:
        if not isinstance(patch, str) or not patch.strip():
            raise ValueError("patch must be a non-empty string")
        if ".env" in patch:
            raise ValueError("patch may not reference .env files")

        completed = subprocess.run(
            ["git", "apply", "--whitespace=nowarn", "-"],
            input=patch,
            cwd=self.repo_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=self.command_timeout,
            env=_safe_env(),
        )
        return self._cap_result(
            {
                "ok": completed.returncode == 0,
                "exit_code": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            }
        )

    def run_command(self, command: str, timeout: float | None = None) -> dict[str, Any]:
        if not isinstance(command, str) or not command.strip():
            raise ValueError("command must be a non-empty string")
        if ".env" in command:
            raise PolicyViolation("Commands may not reference .env files")

        normalized = normalize_command(command)
        self.command_policy.enforce(normalized)
        completed = subprocess.run(
            normalized,
            cwd=self.repo_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=self.command_timeout if timeout is None else float(timeout),
            env=_safe_env(),
        )
        return self._cap_result(
            {
                "ok": completed.returncode == 0,
                "command": list(normalized),
                "exit_code": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            }
        )

    def _resolve_path(self, path: str) -> Path:
        if not isinstance(path, str) or not path:
            raise ValueError("path must be a non-empty string")
        requested = Path(path)
        if requested.is_absolute():
            raise ValueError("absolute paths are not allowed")
        if _is_env_path(requested.parts):
            raise ValueError(".env files are not accessible to the agent")

        target = (self.repo_root / requested).resolve()
        if not target.is_relative_to(self.repo_root):
            raise ValueError(f"path may not escape repo root: {path}")
        if not target.exists():
            raise FileNotFoundError(path)
        return target

    def _relative(self, path: Path) -> str:
        return str(path.relative_to(self.repo_root))

    def _cap_result(self, result: dict[str, Any]) -> dict[str, Any]:
        encoded = repr(result)
        if len(encoded) <= self.max_output:
            return result
        capped = dict(result)
        capped["truncated"] = True
        for key in ("content", "stdout", "stderr"):
            if isinstance(capped.get(key), str) and len(repr(capped)) > self.max_output:
                capped[key] = capped[key][: self.max_output // 2] + "\n...[truncated]"
        return capped


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("expected integer")
    return max(minimum, min(maximum, value))


def _is_env_path(parts: tuple[str, ...]) -> bool:
    return any(part == ".env" or part.startswith(".env.") for part in parts)


def _safe_env() -> dict[str, str]:
    allowed = {"PATH", "HOME", "TMPDIR", "LANG", "LC_ALL", "VIRTUAL_ENV"}
    return {key: value for key, value in os.environ.items() if key in allowed}


def _shorten_absolute_match(match: str, repo_root: Path) -> str:
    prefix = str(repo_root) + os.sep
    return match.replace(prefix, "", 1) if match.startswith(prefix) else match
