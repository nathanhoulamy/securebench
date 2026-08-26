"""Sandbox interfaces for untrusted execution."""

from __future__ import annotations

import codecs
import math
import os
import selectors
import subprocess
import tempfile
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Callable


TIMEOUT_EXIT_CODE = 124
MAX_COMMAND_OUTPUT_BYTES = 1024 * 1024
OUTPUT_TRUNCATION_MARKER = b"\n[securebench: output truncated]\n"
OutputCallback = Callable[[str, str], None]
ProcessStartCallback = Callable[[], None]


@dataclass(frozen=True)
class CommandResult:
    """Result from a sandboxed command."""

    command: tuple[str, ...]
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    timeout_seconds: float | None = None
    stdout_bytes: int | None = None
    stderr_bytes: int | None = None
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    stdout_valid_utf8: bool = True
    stderr_valid_utf8: bool = True


@dataclass(frozen=True)
class BoundedProcessResult:
    """Completed subprocess output with raw-byte integrity metadata."""

    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    stdout_bytes: int
    stderr_bytes: int
    stdout_truncated: bool
    stderr_truncated: bool
    stdout_valid_utf8: bool
    stderr_valid_utf8: bool


@dataclass
class _BoundedOutput:
    """Track one hostile output stream without retaining it unboundedly."""

    buffer: bytearray = field(default_factory=bytearray)
    bytes_seen: int = 0
    truncated: bool = False
    valid_utf8: bool = True
    finalized: bool = False
    decoder: codecs.IncrementalDecoder = field(
        default_factory=lambda: codecs.getincrementaldecoder("utf-8")(errors="strict")
    )

    def append(self, chunk: bytes) -> bytes:
        self.bytes_seen += len(chunk)
        self._decode(chunk, final=False)
        remaining = max(MAX_COMMAND_OUTPUT_BYTES - len(self.buffer), 0)
        emitted = chunk[:remaining]
        self.buffer.extend(emitted)
        if len(chunk) > remaining:
            self.truncated = True
        return emitted

    def finalize(self) -> None:
        self._decode(b"", final=True)

    def render(self) -> str:
        value = bytes(self.buffer)
        if self.truncated:
            value = value[: MAX_COMMAND_OUTPUT_BYTES - len(OUTPUT_TRUNCATION_MARKER)]
            value += OUTPUT_TRUNCATION_MARKER
        return value.decode("utf-8", errors="replace")

    def _decode(self, chunk: bytes, *, final: bool) -> None:
        if self.finalized:
            return
        try:
            if self.valid_utf8:
                self.decoder.decode(chunk, final=final)
        except UnicodeDecodeError:
            self.valid_utf8 = False
        if final:
            self.finalized = True


def timeout_command_result(
    command: tuple[str, ...],
    timeout: float | None,
    *,
    stdout: str | bytes | None = None,
    stderr: str | bytes | None = None,
    stdout_bytes: int | None = None,
    stderr_bytes: int | None = None,
    stdout_truncated: bool = False,
    stderr_truncated: bool = False,
    stdout_valid_utf8: bool = True,
    stderr_valid_utf8: bool = True,
) -> CommandResult:
    """Build a structured result for a sandbox command timeout."""
    return CommandResult(
        command=command,
        exit_code=TIMEOUT_EXIT_CODE,
        stdout=timeout_output(stdout),
        stderr=timeout_output(stderr),
        timed_out=True,
        timeout_seconds=timeout,
        stdout_bytes=stdout_bytes,
        stderr_bytes=stderr_bytes,
        stdout_truncated=stdout_truncated,
        stderr_truncated=stderr_truncated,
        stdout_valid_utf8=stdout_valid_utf8,
        stderr_valid_utf8=stderr_valid_utf8,
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
    on_start: ProcessStartCallback | None = None,
) -> BoundedProcessResult:
    """Run a command while draining and bounding hostile stdout and stderr."""
    if timeout is not None:
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
            raise ValueError("timeout must be a finite positive number or None")
        try:
            timeout = float(timeout)
        except OverflowError as exc:
            raise ValueError("timeout must be a finite positive number or None") from exc
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be a finite positive number or None")
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
    except BaseException:
        if input_file is not None:
            input_file.close()
        raise
    try:
        if on_start is not None:
            on_start()
    except BaseException:
        process.kill()
        process.wait()
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                stream.close()
        if input_file is not None:
            input_file.close()
        raise
    selector = selectors.DefaultSelector()
    assert process.stdout is not None
    assert process.stderr is not None
    selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    selector.register(process.stderr, selectors.EVENT_READ, "stderr")
    outputs = {"stdout": _BoundedOutput(), "stderr": _BoundedOutput()}
    deadline = None if timeout is None else time.monotonic() + timeout
    try:
        while selector.get_map():
            remaining = None if deadline is None else deadline - time.monotonic()
            if remaining is not None and remaining <= 0:
                _raise_bounded_timeout(
                    process,
                    command,
                    timeout,
                    outputs,
                )
            wait = 0.2 if remaining is None else min(0.2, remaining)
            events = selector.select(wait)
            if not events and process.poll() is not None:
                for key in list(selector.get_map().values()):
                    outputs[key.data].finalize()
                    selector.unregister(key.fileobj)
                break
            for key, _ in events:
                chunk = os.read(key.fileobj.fileno(), 64 * 1024)
                if not chunk:
                    outputs[key.data].finalize()
                    selector.unregister(key.fileobj)
                    continue
                stream = key.data
                emitted = outputs[stream].append(chunk)
                if on_output is not None and emitted:
                    on_output(stream, emitted.decode("utf-8", errors="replace"))

        remaining = None if deadline is None else max(deadline - time.monotonic(), 0)
        try:
            exit_code = process.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            _raise_bounded_timeout(
                process,
                command,
                timeout,
                outputs,
            )
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

    return BoundedProcessResult(
        args=tuple(command),
        returncode=exit_code,
        stdout=outputs["stdout"].render(),
        stderr=outputs["stderr"].render(),
        stdout_bytes=outputs["stdout"].bytes_seen,
        stderr_bytes=outputs["stderr"].bytes_seen,
        stdout_truncated=outputs["stdout"].truncated,
        stderr_truncated=outputs["stderr"].truncated,
        stdout_valid_utf8=outputs["stdout"].valid_utf8,
        stderr_valid_utf8=outputs["stderr"].valid_utf8,
    )


def _raise_bounded_timeout(
    process: subprocess.Popen[bytes],
    command: list[str] | tuple[str, ...],
    timeout: float | None,
    outputs: dict[str, _BoundedOutput],
) -> None:
    process.kill()
    process.wait()
    for output in outputs.values():
        output.finalize()
    error = subprocess.TimeoutExpired(
        command,
        timeout,
        output=outputs["stdout"].render(),
        stderr=outputs["stderr"].render(),
    )
    error.stdout_bytes = outputs["stdout"].bytes_seen
    error.stderr_bytes = outputs["stderr"].bytes_seen
    error.stdout_truncated = outputs["stdout"].truncated
    error.stderr_truncated = outputs["stderr"].truncated
    error.stdout_valid_utf8 = outputs["stdout"].valid_utf8
    error.stderr_valid_utf8 = outputs["stderr"].valid_utf8
    raise error


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
