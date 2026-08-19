"""Sandbox interfaces for untrusted execution."""

from __future__ import annotations

import os
import selectors
import subprocess
import tempfile
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable


TIMEOUT_EXIT_CODE = 124
MAX_COMMAND_OUTPUT_BYTES = 1024 * 1024
OUTPUT_TRUNCATION_MARKER = b"\n[securebench: output truncated]\n"
OutputCallback = Callable[[str, str], None]


@dataclass(frozen=True)
class CommandResult:
    """Result from a sandboxed command."""

    command: tuple[str, ...]
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    timeout_seconds: float | None = None


def timeout_command_result(
    command: tuple[str, ...],
    timeout: float | None,
    *,
    stdout: str | bytes | None = None,
    stderr: str | bytes | None = None,
) -> CommandResult:
    """Build a structured result for a sandbox command timeout."""
    return CommandResult(
        command=command,
        exit_code=TIMEOUT_EXIT_CODE,
        stdout=timeout_output(stdout),
        stderr=timeout_output(stderr),
        timed_out=True,
        timeout_seconds=timeout,
    )


def timeout_output(value: str | bytes | None) -> str:
    """Normalize partial timeout output from subprocess APIs."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value


def run_bounded_subprocess(
    command: list[str] | tuple[str, ...],
    *,
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
    timeout: float | None = None,
    stdin: str | bytes | None = None,
    on_output: OutputCallback | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a command while draining and bounding hostile stdout and stderr."""
    input_file = None
    if stdin is not None:
        input_file = tempfile.TemporaryFile()
        input_file.write(stdin.encode("utf-8") if isinstance(stdin, str) else stdin)
        input_file.seek(0)
    try:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdin=input_file,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,
            bufsize=0,
        )
    except Exception:
        if input_file is not None:
            input_file.close()
        raise
    selector = selectors.DefaultSelector()
    assert process.stdout is not None
    assert process.stderr is not None
    selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    selector.register(process.stderr, selectors.EVENT_READ, "stderr")
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    truncated = {"stdout": False, "stderr": False}
    deadline = None if timeout is None else time.monotonic() + timeout
    try:
        while selector.get_map():
            remaining = None if deadline is None else deadline - time.monotonic()
            if remaining is not None and remaining <= 0:
                _raise_bounded_timeout(process, command, timeout, buffers, truncated)
            wait = 0.2 if remaining is None else min(0.2, remaining)
            events = selector.select(wait)
            if not events and process.poll() is not None:
                for key in list(selector.get_map().values()):
                    selector.unregister(key.fileobj)
                break
            for key, _ in events:
                chunk = os.read(key.fileobj.fileno(), 64 * 1024)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                stream = key.data
                emitted = _append_bounded_output(buffers[stream], chunk, truncated, stream)
                if on_output is not None and emitted:
                    on_output(stream, emitted.decode("utf-8", errors="replace"))

        remaining = None if deadline is None else max(deadline - time.monotonic(), 0)
        try:
            exit_code = process.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            _raise_bounded_timeout(process, command, timeout, buffers, truncated)
    finally:
        selector.close()
        if process.poll() is None:
            process.kill()
            process.wait()
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                stream.close()
        if input_file is not None:
            input_file.close()

    return subprocess.CompletedProcess(
        command,
        exit_code,
        stdout=_render_bounded_output(buffers["stdout"], truncated["stdout"]),
        stderr=_render_bounded_output(buffers["stderr"], truncated["stderr"]),
    )


def _append_bounded_output(
    buffer: bytearray,
    chunk: bytes,
    truncated: dict[str, bool],
    stream: str,
) -> bytes:
    content_limit = MAX_COMMAND_OUTPUT_BYTES
    remaining = max(content_limit - len(buffer), 0)
    emitted = chunk[:remaining]
    buffer.extend(emitted)
    if len(chunk) > remaining:
        truncated[stream] = True
    return emitted


def _render_bounded_output(buffer: bytearray, truncated: bool) -> str:
    value = bytes(buffer)
    if truncated:
        value = value[: MAX_COMMAND_OUTPUT_BYTES - len(OUTPUT_TRUNCATION_MARKER)]
        value += OUTPUT_TRUNCATION_MARKER
    return value.decode("utf-8", errors="replace")


def _raise_bounded_timeout(
    process: subprocess.Popen[bytes],
    command: list[str] | tuple[str, ...],
    timeout: float | None,
    buffers: dict[str, bytearray],
    truncated: dict[str, bool],
) -> None:
    process.kill()
    process.wait()
    raise subprocess.TimeoutExpired(
        command,
        timeout,
        output=_render_bounded_output(buffers["stdout"], truncated["stdout"]),
        stderr=_render_bounded_output(buffers["stderr"], truncated["stderr"]),
    )


class Sandbox(ABC):
    """Minimal file and process API exposed to harnesses and verifiers."""

    @abstractmethod
    def run(
        self,
        command: str | list[str] | tuple[str, ...],
        *,
        workdir: str | None = None,
        timeout: float | None = None,
        stdin: str | bytes | None = None,
    ) -> CommandResult:
        """Run a command in the sandbox."""

    @abstractmethod
    def write_file(self, path: str | PurePosixPath, content: str | bytes) -> None:
        """Write a file inside the sandbox."""

    @abstractmethod
    def read_file(self, path: str | PurePosixPath) -> str:
        """Read a text file from the sandbox."""

    @abstractmethod
    def extract_file(self, path: str | PurePosixPath) -> bytes:
        """Extract a file from the sandbox as bytes."""


def resolve_sandbox_host_path(
    root: str | Path,
    path: str | PurePosixPath,
    *,
    for_write: bool = False,
) -> Path:
    """Resolve a sandbox-relative host path without following escapes.

    The syntactic check rejects explicit traversal, the resolved-path check
    blocks symlinks inside the sandbox from pointing reads or writes outside the
    sandbox root, and write resolution rejects existing symlink components so
    framework-owned writes cannot be redirected within the workspace.
    """
    sandbox_path = PurePosixPath(path)
    if sandbox_path.is_absolute():
        sandbox_path = PurePosixPath(*sandbox_path.parts[1:])
    if ".." in sandbox_path.parts:
        raise ValueError(f"Sandbox path may not escape root: {path}")

    root_path = Path(root)
    target = root_path.joinpath(*sandbox_path.parts)
    root_resolved = root_path.resolve()
    if for_write:
        parent_resolved = target.parent.resolve()
        if not parent_resolved.is_relative_to(root_resolved):
            raise ValueError(f"Sandbox path may not escape root: {path}")
        if target.exists() or target.is_symlink():
            target_resolved = target.resolve()
            if not target_resolved.is_relative_to(root_resolved):
                raise ValueError(f"Sandbox path may not escape root: {path}")
        _reject_write_symlinks(root_path, sandbox_path)
    else:
        target_resolved = target.resolve()
        if not target_resolved.is_relative_to(root_resolved):
            raise ValueError(f"Sandbox path may not escape root: {path}")
    return target


def _reject_write_symlinks(root: Path, relative_path: PurePosixPath) -> None:
    current = root
    for part in relative_path.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"Sandbox path may not write through symlink: {relative_path}")
        if not current.exists():
            break
