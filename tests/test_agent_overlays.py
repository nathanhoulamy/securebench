from contextlib import contextmanager

import pytest

from securebench.harnesses import claude_code, codex
from securebench.harnesses.codex import DockerPlatform


@pytest.mark.parametrize(
    ("module", "agent_name", "binary_name", "resolver_name", "populate_name"),
    [
        (
            codex,
            "codex",
            "codex",
            "codex_overlay_for_image",
            "populate_codex_overlay_cache",
        ),
        (
            claude_code,
            "claude-code",
            "claude",
            "claude_code_overlay_for_image",
            "populate_claude_code_overlay_cache",
        ),
    ],
)
def test_overlay_population_holds_cross_process_cache_lock(
    monkeypatch,
    tmp_path,
    module,
    agent_name,
    binary_name,
    resolver_name,
    populate_name,
):
    platform = DockerPlatform(os="linux", architecture="amd64", variant=None)
    lock_held = False

    @contextmanager
    def fake_lock(path):
        nonlocal lock_held
        assert path == tmp_path / agent_name / "1.2.3" / ".linux-amd64.lock"
        lock_held = True
        try:
            yield
        finally:
            lock_held = False

    def populate(path, version, selected_platform):
        assert lock_held is True
        assert version == "1.2.3"
        assert selected_platform == platform
        (path / "bin").mkdir(parents=True)
        (path / "bin" / binary_name).write_text("agent")
        (path / "bin" / "node").write_text("node")

    monkeypatch.setattr(module, "docker_image_platform", lambda image: platform)
    cache_root_name = f"{agent_name.replace('-', '_')}_overlay_cache_root"
    monkeypatch.setattr(module, cache_root_name, lambda: tmp_path)
    monkeypatch.setattr(module, "exclusive_file_lock", fake_lock)
    monkeypatch.setattr(module, populate_name, populate)

    overlay = getattr(module, resolver_name)("benchmark-image", "1.2.3")

    assert overlay.path == tmp_path / agent_name / "1.2.3" / "linux-amd64"
    assert lock_held is False
