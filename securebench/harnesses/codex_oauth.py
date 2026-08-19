"""SecureBench-owned Codex OAuth credential storage and refresh."""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

try:
    from securebench.locking import exclusive_file_lock
except ImportError:  # Standalone provider-relay sidecar mount.
    from locking import exclusive_file_lock


CODEX_OAUTH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
CODEX_OAUTH_TOKEN_URL = "https://auth.openai.com/oauth/token"
CODEX_AUTH_HOME_ENV = "SECUREBENCH_AUTH_HOME"
CODEX_AUTH_REFRESH_SKEW_SECONDS = 300
CHATGPT_ACCOUNT_ID_CLAIM = "https://api.openai.com/auth.chatgpt_account_id"
CHATGPT_AUTH_CLAIM = "https://api.openai.com/auth"


class CodexOAuthError(OSError):
    """Raised when the isolated Codex login cannot be loaded or refreshed."""


@dataclass(frozen=True)
class CodexOAuthCredentials:
    access_token: str = field(repr=False)
    refresh_token: str = field(repr=False)
    account_id: str
    plan_type: str | None
    expires_at: int | None


def securebench_auth_home() -> Path:
    configured = os.environ.get(CODEX_AUTH_HOME_ENV)
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".config" / "securebench" / "auth"


def codex_auth_home() -> Path:
    return securebench_auth_home() / "codex"


def codex_auth_file() -> Path:
    return codex_auth_home() / "auth.json"


def prepare_codex_auth_home(path: Path | None = None) -> Path:
    home = codex_auth_home() if path is None else path
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(home, 0o700)
    return home


def run_codex_login(*, device_auth: bool = False) -> Path:
    home = prepare_codex_auth_home()
    command = _codex_auth_command("login")
    if device_auth:
        command.append("--device-auth")
    completed = subprocess.run(command, check=False, env=_codex_auth_env(home))
    if completed.returncode != 0:
        raise CodexOAuthError(f"Codex login failed with exit code {completed.returncode}")
    path = home / "auth.json"
    load_codex_oauth_credentials(path)
    os.chmod(path, 0o600)
    return path


def run_codex_logout() -> None:
    home = prepare_codex_auth_home()
    completed = subprocess.run(
        _codex_auth_command("logout"),
        check=False,
        env=_codex_auth_env(home),
    )
    if completed.returncode != 0:
        raise CodexOAuthError(f"Codex logout failed with exit code {completed.returncode}")


def _codex_auth_command(action: str) -> list[str]:
    binary = shutil.which("codex")
    if binary is None:
        raise CodexOAuthError(
            "Codex CLI is required for subscription login; install @openai/codex and try again"
        )
    return [
        binary,
        action,
        "-c",
        'cli_auth_credentials_store="file"',
    ]


def _codex_auth_env(home: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["CODEX_HOME"] = str(home)
    for name in ("OPENAI_API_KEY", "CODEX_API_KEY", "CODEX_ACCESS_TOKEN"):
        env.pop(name, None)
    return env


def load_codex_oauth_credentials(path: Path | None = None) -> CodexOAuthCredentials:
    auth_path = codex_auth_file() if path is None else path
    document = _read_auth_document(auth_path)
    return _credentials_from_document(document, auth_path)


def ensure_valid_codex_oauth_credentials(
    path: Path | None = None,
    *,
    force_refresh: bool = False,
    now: float | None = None,
    opener: Callable[..., Any] = urlopen,
) -> CodexOAuthCredentials:
    auth_path = codex_auth_file() if path is None else path
    current_time = time.time() if now is None else now
    with _auth_file_lock(auth_path):
        document = _read_auth_document(auth_path)
        credentials = _credentials_from_document(document, auth_path)
        should_refresh = (
            force_refresh
            or credentials.expires_at is None
            or credentials.expires_at <= current_time + CODEX_AUTH_REFRESH_SKEW_SECONDS
        )
        if not should_refresh:
            return credentials
        refreshed = _refresh_document(document, credentials.refresh_token, opener=opener)
        refreshed_credentials = _credentials_from_document(refreshed, auth_path)
        _write_auth_document(auth_path, refreshed)
        return refreshed_credentials


def _credentials_from_document(
    document: Any,
    path: Path,
) -> CodexOAuthCredentials:
    if not isinstance(document, dict) or document.get("auth_mode") != "chatgpt":
        raise CodexOAuthError(
            f"{path} does not contain a ChatGPT subscription login; "
            "run `securebench auth codex login`"
        )
    tokens = document.get("tokens")
    if not isinstance(tokens, dict):
        raise CodexOAuthError(f"{path} is missing Codex OAuth tokens")
    access_token = _required_token(tokens, "access_token", path)
    refresh_token = _required_token(tokens, "refresh_token", path)
    id_token = _required_token(tokens, "id_token", path)
    access_claims = _jwt_claims(access_token, "access token")
    id_claims = _jwt_claims(id_token, "ID token")
    account_id = tokens.get("account_id")
    if not isinstance(account_id, str) or not account_id:
        account_id = _account_id_from_claims(id_claims) or _account_id_from_claims(access_claims)
    if not account_id:
        raise CodexOAuthError(f"{path} is missing the ChatGPT account id")
    auth_claim = id_claims.get(CHATGPT_AUTH_CLAIM)
    plan_type = auth_claim.get("chatgpt_plan_type") if isinstance(auth_claim, dict) else None
    if not isinstance(plan_type, str):
        plan_type = None
    expires_at = access_claims.get("exp")
    if not isinstance(expires_at, int):
        expires_at = None
    return CodexOAuthCredentials(
        access_token=access_token,
        refresh_token=refresh_token,
        account_id=account_id,
        plan_type=plan_type,
        expires_at=expires_at,
    )


def _read_auth_document(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text())
    except FileNotFoundError as exc:
        raise CodexOAuthError(
            "No SecureBench Codex subscription login found; run "
            "`securebench auth codex login` first"
        ) from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise CodexOAuthError(f"Could not read Codex credentials from {path}") from exc
    if not isinstance(document, dict):
        raise CodexOAuthError(f"{path} must contain a JSON object")
    return document


def _refresh_document(
    document: dict[str, Any],
    refresh_token: str,
    *,
    opener: Callable[..., Any],
) -> dict[str, Any]:
    body = json.dumps(
        {
            "client_id": CODEX_OAUTH_CLIENT_ID,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }
    ).encode("utf-8")
    request = Request(
        CODEX_OAUTH_TOKEN_URL,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        response = opener(request, timeout=30)
        try:
            payload = json.loads(response.read())
        finally:
            close = getattr(response, "close", None)
            if close is not None:
                close()
    except HTTPError as exc:
        raise CodexOAuthError(
            "Codex subscription refresh was rejected; run "
            "`securebench auth codex login` again"
        ) from exc
    except (URLError, OSError, json.JSONDecodeError) as exc:
        raise CodexOAuthError("Could not refresh the Codex subscription login") from exc
    if not isinstance(payload, dict):
        raise CodexOAuthError("Codex token endpoint returned an invalid response")
    tokens = document.get("tokens")
    if not isinstance(tokens, dict):
        raise CodexOAuthError("Stored Codex credentials are missing OAuth tokens")
    updated_tokens = dict(tokens)
    for name in ("access_token", "refresh_token", "id_token"):
        value = payload.get(name)
        if value is not None:
            if not isinstance(value, str) or not value:
                raise CodexOAuthError(f"Codex token endpoint returned an invalid {name}")
            updated_tokens[name] = value
    if payload.get("access_token") is None:
        raise CodexOAuthError("Codex token endpoint did not return an access token")
    updated = dict(document)
    updated["tokens"] = updated_tokens
    updated["last_refresh"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return updated


def _write_auth_document(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".auth-", suffix=".json", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(document, stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


@contextmanager
def _auth_file_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_path = path.parent / ".auth.lock"
    with exclusive_file_lock(lock_path):
        yield


def _required_token(tokens: dict[str, Any], name: str, path: Path) -> str:
    value = tokens.get(name)
    if not isinstance(value, str) or not value:
        raise CodexOAuthError(f"{path} is missing {name}")
    return value


def _jwt_claims(token: str, label: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) != 3:
        raise CodexOAuthError(f"Stored Codex {label} is not a JWT")
    try:
        padded = parts[1] + "=" * (-len(parts[1]) % 4)
        claims = json.loads(base64.urlsafe_b64decode(padded))
    except (ValueError, json.JSONDecodeError) as exc:
        raise CodexOAuthError(f"Stored Codex {label} has invalid claims") from exc
    if not isinstance(claims, dict):
        raise CodexOAuthError(f"Stored Codex {label} has invalid claims")
    return claims


def _account_id_from_claims(claims: dict[str, Any]) -> str | None:
    direct = claims.get(CHATGPT_ACCOUNT_ID_CLAIM)
    if isinstance(direct, str) and direct:
        return direct
    auth_claim = claims.get(CHATGPT_AUTH_CLAIM)
    if isinstance(auth_claim, dict):
        nested = auth_claim.get("chatgpt_account_id")
        if isinstance(nested, str) and nested:
            return nested
    return None
