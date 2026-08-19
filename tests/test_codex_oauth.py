import base64
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from securebench.harnesses import codex_oauth
from securebench.harnesses.codex_oauth import (
    CHATGPT_AUTH_CLAIM,
    CodexOAuthError,
    ensure_valid_codex_oauth_credentials,
    load_codex_oauth_credentials,
)
from securebench import locking


def jwt(claims):
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').decode().rstrip("=")
    payload = (
        base64.urlsafe_b64encode(json.dumps(claims, separators=(",", ":")).encode())
        .decode()
        .rstrip("=")
    )
    return f"{header}.{payload}.signature"


def auth_document(*, expires_at, access_token="access", refresh_token="refresh"):
    auth_claim = {
        "chatgpt_account_id": "account-1",
        "chatgpt_plan_type": "pro",
    }
    access = jwt({"exp": expires_at, CHATGPT_AUTH_CLAIM: auth_claim})
    if access_token != "access":
        access = access_token
    return {
        "auth_mode": "chatgpt",
        "unrelated": "preserved",
        "tokens": {
            "access_token": access,
            "refresh_token": refresh_token,
            "id_token": jwt({CHATGPT_AUTH_CLAIM: auth_claim}),
            "account_id": "account-1",
        },
        "last_refresh": "2026-01-01T00:00:00Z",
    }


def write_auth(path: Path, document):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document))


def test_securebench_codex_auth_home_is_isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("SECUREBENCH_AUTH_HOME", str(tmp_path))

    assert codex_oauth.codex_auth_home() == tmp_path / "codex"
    assert codex_oauth.codex_auth_file() == tmp_path / "codex" / "auth.json"


def test_load_codex_oauth_credentials_returns_safe_metadata(tmp_path):
    path = tmp_path / "auth.json"
    write_auth(path, auth_document(expires_at=10_000))

    credentials = load_codex_oauth_credentials(path)

    assert credentials.account_id == "account-1"
    assert credentials.plan_type == "pro"
    assert credentials.expires_at == 10_000
    assert credentials.refresh_token == "refresh"
    assert "access_token" not in repr(credentials)
    assert "refresh_token" not in repr(credentials)
    assert "id_token" not in repr(credentials)


def test_valid_codex_oauth_credentials_do_not_refresh(tmp_path):
    path = tmp_path / "auth.json"
    write_auth(path, auth_document(expires_at=10_000))

    def unexpected_opener(request, timeout):
        raise AssertionError("valid credentials should not refresh")

    credentials = ensure_valid_codex_oauth_credentials(
        path,
        now=1_000,
        opener=unexpected_opener,
    )

    assert credentials.expires_at == 10_000


def test_expiring_codex_oauth_credentials_refresh_and_rotate_atomically(tmp_path):
    path = tmp_path / "auth.json"
    write_auth(path, auth_document(expires_at=1_100))
    refreshed_access = jwt(
        {
            "exp": 20_000,
            CHATGPT_AUTH_CLAIM: {"chatgpt_account_id": "account-1"},
        }
    )
    seen = {}

    class Response:
        def __init__(self):
            self.closed = False

        def read(self):
            return json.dumps(
                {
                    "access_token": refreshed_access,
                    "refresh_token": "rotated-refresh",
                }
            ).encode()

        def close(self):
            self.closed = True

    def opener(request, timeout):
        seen["url"] = request.full_url
        seen["timeout"] = timeout
        seen["content_type"] = request.headers["Content-type"]
        seen["body"] = json.loads(request.data)
        seen["response"] = Response()
        return seen["response"]

    credentials = ensure_valid_codex_oauth_credentials(
        path,
        now=1_000,
        opener=opener,
    )

    assert seen == {
        "url": "https://auth.openai.com/oauth/token",
        "timeout": 30,
        "content_type": "application/json",
        "body": {
            "client_id": codex_oauth.CODEX_OAUTH_CLIENT_ID,
            "grant_type": "refresh_token",
            "refresh_token": "refresh",
        },
        "response": seen["response"],
    }
    assert seen["response"].closed is True
    assert credentials.access_token == refreshed_access
    assert credentials.refresh_token == "rotated-refresh"
    saved = json.loads(path.read_text())
    assert saved["unrelated"] == "preserved"
    assert saved["tokens"]["id_token"]
    assert oct(path.stat().st_mode & 0o777) == "0o600"


def test_invalid_refreshed_token_does_not_replace_stored_credentials(tmp_path):
    path = tmp_path / "auth.json"
    original = auth_document(expires_at=1_100)
    write_auth(path, original)

    class Response:
        def read(self):
            return json.dumps({"access_token": "not-a-jwt"}).encode()

    with pytest.raises(CodexOAuthError, match="access token is not a JWT"):
        ensure_valid_codex_oauth_credentials(
            path,
            now=1_000,
            opener=lambda request, timeout: Response(),
        )

    assert json.loads(path.read_text()) == original


def test_missing_codex_subscription_login_has_actionable_error(tmp_path):
    with pytest.raises(CodexOAuthError, match="securebench auth codex login"):
        load_codex_oauth_credentials(tmp_path / "missing.json")


def test_run_codex_login_uses_isolated_codex_home(monkeypatch, tmp_path):
    monkeypatch.setenv("SECUREBENCH_AUTH_HOME", str(tmp_path))
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-be-inherited")
    monkeypatch.setattr(codex_oauth.shutil, "which", lambda name: "/usr/local/bin/codex")
    seen = {}

    def fake_run(command, *, check, env):
        seen["command"] = command
        seen["check"] = check
        seen["env"] = env
        auth_path = Path(env["CODEX_HOME"]) / "auth.json"
        write_auth(auth_path, auth_document(expires_at=10_000))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(codex_oauth.subprocess, "run", fake_run)

    path = codex_oauth.run_codex_login(device_auth=True)

    assert path == tmp_path / "codex" / "auth.json"
    assert seen["command"] == [
        "/usr/local/bin/codex",
        "login",
        "-c",
        'cli_auth_credentials_store="file"',
        "--device-auth",
    ]
    assert seen["env"]["CODEX_HOME"] == str(tmp_path / "codex")
    assert "OPENAI_API_KEY" not in seen["env"]
    assert oct((tmp_path / "codex").stat().st_mode & 0o777) == "0o700"
    assert oct(path.stat().st_mode & 0o777) == "0o600"


def test_codex_oauth_imports_with_only_sidecar_companion_mounts(tmp_path):
    shutil.copy2(codex_oauth.__file__, tmp_path / "codex_oauth.py")
    shutil.copy2(locking.__file__, tmp_path / "locking.py")

    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            f"import sys; sys.path.insert(0, {str(tmp_path)!r}); import codex_oauth",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
