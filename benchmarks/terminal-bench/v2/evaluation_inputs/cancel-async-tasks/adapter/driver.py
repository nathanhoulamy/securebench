"""Public Candidate-call driver for one bounded async task scenario."""

from __future__ import annotations

import asyncio
from contextlib import suppress
import json
import sys
from typing import Any, Awaitable, Callable


# Bound on how long a task's own finally clause waits for the trusted task
# service to acknowledge that its cleanup delay and ledger append are done.
# This is local loopback traffic plus a bounded host-owned sleep, so a
# generous fixed bound (independent of the challenge's own cleanup_ms, which
# stays out of the Candidate-shared process) is enough headroom without
# risking an unbounded wait if the service never responds.
CLEANUP_ACK_TIMEOUT_SECONDS = 5.0


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
            # Cleanup acknowledgement: this must run, on every exit path
            # (normal completion or cancellation), for the trusted task
            # service to credit this task's cleanup as having happened. The
            # adapter never records `task.cleaned` on its own; it only does
            # so after observing this marker arrive from code running
            # inside the Candidate's own process, and only sends this ack
            # back after its own real cleanup delay elapses. This task does
            # not return -- and so does not release any concurrency limit
            # the Candidate's run_tasks is enforcing -- until that ack
            # arrives or a generous bound expires, so recorded concurrency
            # reflects when cleanup genuinely finished, not merely when the
            # marker was sent.
            try:
                writer.write(b"C")
                await writer.drain()
                with suppress(OSError, asyncio.IncompleteReadError, TimeoutError):
                    await asyncio.wait_for(
                        reader.readexactly(1), timeout=CLEANUP_ACK_TIMEOUT_SECONDS
                    )
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
