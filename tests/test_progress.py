from io import StringIO

from securebench.progress import StreamProgressReporter


def test_stream_progress_reporter_prints_concise_task_progress():
    stream = StringIO()
    reporter = StreamProgressReporter(stream=stream, color=False)

    reporter.event("task_start", index=2, total=10, task_id="django__django-12741")
    reporter.event("producer_start", task_id="django__django-12741")
    reporter.event("sandbox_command", kind="docker", command="pytest -q")
    reporter.event(
        "task_done",
        task_id="django__django-12741",
        status="passed",
        passed=True,
        score=1.0,
    )

    assert stream.getvalue().splitlines() == [
        "securebench: [2/10] django__django-12741",
        "securebench: PASS django__django-12741 score=1.0",
    ]


def test_stream_progress_reporter_can_show_sandbox_output_when_requested():
    stream = StringIO()
    reporter = StreamProgressReporter(stream=stream, show_command_output=True, color=False)

    reporter.event("sandbox_result", stdout="ok\n", stderr="warn\n")

    assert stream.getvalue().splitlines() == [
        "stdout: ok",
        "stderr: warn",
    ]


def test_stream_progress_reporter_can_show_agent_events():
    stream = StringIO()
    reporter = StreamProgressReporter(stream=stream, show_agent_output=True, color=False)

    reporter.event("agent_output", stream="stdout", line='{"type":"agent_message","text":"I am editing the file."}')
    reporter.event(
        "agent_output",
        stream="stdout",
        line='{"type":"item.started","item":{"type":"command_execution","command":"pytest -q"}}',
    )
    reporter.event(
        "agent_output",
        stream="stdout",
        line='{"type":"item.completed","item":{"type":"command_execution","command":"pytest -q","exit_code":0}}',
    )

    assert stream.getvalue().splitlines() == [
        "codex: I am editing the file.",
        "codex run: pytest -q",
    ]


def test_stream_progress_reporter_writes_full_agent_trace(tmp_path):
    stream = StringIO()
    reporter = StreamProgressReporter(stream=stream, show_agent_output=True, color=False)

    reporter.event("run_start", run_id="run-1", output_dir=tmp_path)
    reporter.event("task_start", index=1, total=1, task_id="task-1")
    reporter.event(
        "agent_output",
        stream="stdout",
        line='{"type":"item.started","item":{"type":"command_execution","command":"pytest -q"}}',
    )
    reporter.event(
        "agent_output",
        stream="stdout",
        line='{"type":"item.completed","item":{"type":"command_execution","command":"pytest -q","exit_code":0}}',
    )

    assert stream.getvalue().splitlines() == [
        "securebench: [1/1] task-1",
        "codex run: pytest -q",
    ]
    assert (tmp_path / "agent-trace.log").read_text().splitlines() == [
        "task-1 | codex run: pytest -q",
        "task-1 | codex done: exit=0 pytest -q",
    ]
