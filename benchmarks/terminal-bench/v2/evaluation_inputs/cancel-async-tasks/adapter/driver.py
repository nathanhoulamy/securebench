"""Public Candidate-call driver for one bounded async task scenario."""

from __future__ import annotations

import asyncio
from contextlib import suppress
import json
import sys
from typing import Any, Awaitable, Callable


def _task_factory(
    *,
    task_id: int,
    host: str,
    port: int,
) -> Callable[[], Awaitable[None]]:
    async def task() -> None:
        reader, writer = await asyncio.open_connection(host, port)
        try:
            writer.write(f"{task_id}\n".encode("ascii"))
            await writer.drain()
            response = await reader.readexactly(1)
            if response != b"D":
                raise RuntimeError("task service returned an invalid response")
        finally:
            writer.close()
            with suppress(OSError):
                await writer.wait_closed()

    return task


async def _run(request: dict[str, Any]) -> None:
    challenge = request["challenge"]
    service = request["task_service"]
    sys.path.insert(0, "/app")
    from run import run_tasks

    tasks = [
        _task_factory(
            task_id=index,
            host=service["host"],
            port=service["port"],
        )
        for index in range(challenge["task_count"])
    ]
    await run_tasks(tasks, challenge["max_concurrent"])


def main() -> None:
    request = json.load(sys.stdin)
    asyncio.run(_run(request))


if __name__ == "__main__":
    main()
