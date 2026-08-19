# Provider Authentication

SecureBench supports API-key and subscription authentication for its Codex and
Claude Code harnesses.

| Harness | `harness.config.auth` | Host credential |
|---|---|---|
| Codex | `api_key` (default) | `OPENAI_API_KEY` in `.env` or the host environment |
| Codex | `subscription` | Isolated SecureBench ChatGPT login |
| Claude Code | `api_key` (default) | `ANTHROPIC_API_KEY` in `.env` or the host environment |
| Claude Code | `subscription` | `CLAUDE_CODE_OAUTH_TOKEN` in `.env` or the host environment |

Provider credential names do not need to appear in `harness.env`. SecureBench
removes them from agent-container environment pass-through automatically.

## Before You Start

Install SecureBench and confirm Docker is available:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
docker version
```

Copy the environment template if you plan to use an API key or a Claude
subscription:

```bash
cp .env.example .env
```

The repository ignores `.env`. Keep it that way: it contains credentials and
must not be committed.

## Claude Subscription

Use this mode with an eligible Claude subscription or organization that
includes Claude Code. Anthropic documents the supported sign-in choices in its
[Claude Code setup guide](https://docs.anthropic.com/en/docs/claude-code/getting-started).

### 1. Generate a token

Install Claude Code on the host if `claude` is not already available. Sign in
to the Claude account or organization whose subscription should pay for the
benchmark usage, then run:

```bash
claude setup-token
```

Follow the prompts and copy the printed token. For a managed organization, make
sure Claude Code is signed in to the intended organization before generating
the token. Anthropic's
[Enterprise migration guidance](https://support.claude.com/en/articles/14128775-claude-code-on-console-to-enterprise-migration)
also uses `claude setup-token` with `CLAUDE_CODE_OAUTH_TOKEN` for
non-interactive automation.

### 2. Store the token

Add the token to the host-side `.env` file:

```dotenv
CLAUDE_CODE_OAUTH_TOKEN=your-token
```

Alternatively, export it in the shell that starts SecureBench:

```bash
export CLAUDE_CODE_OAUTH_TOKEN="your-token"
```

Do not place the token in tester YAML or list it under `harness.env`.

### 3. Configure the harness

```yaml
harness:
  type: claude_code
  config:
    auth: subscription
    model: sonnet
    version: latest
    timeout_seconds: 5400
    allow_external_tools: false
```

### 4. Run a benchmark

The repository includes a complete example:

```bash
.venv/bin/python -m securebench.cli run \
  --config docs/examples/tester-claude-code-subscription.yaml \
  --limit 1
```

SecureBench loads `.env` by default. To use another file, pass
`--env-file path/to/file`.

The Claude token is passed only to the provider relay. The untrusted agent
container receives a dummy token and sends its Anthropic requests through the
relay.

### Renewing or changing the Claude login

SecureBench does not own or refresh the Claude setup token. If Anthropic rejects
it, if it is revoked, or if you need to change organizations:

1. Sign in to the intended Claude account or organization.
2. Run `claude setup-token` again.
3. Replace `CLAUDE_CODE_OAUTH_TOKEN` in `.env` or the host environment.
4. Restart the benchmark command.

## ChatGPT Subscription for Codex

Codex officially supports signing in with ChatGPT for subscription access as
well as signing in with an API key. See OpenAI's
[Codex authentication guide](https://learn.chatgpt.com/docs/auth).

SecureBench deliberately creates its own Codex login. It does not copy, import,
or modify the normal login under `~/.codex`.

### 1. Install the Codex CLI

The host needs a working `codex` command for the login flow:

```bash
codex --version
```

The benchmark container still uses the Codex version selected by
`harness.config.version`; the host CLI is used only to perform the official
login and logout flows.

### 2. Sign in through SecureBench

```bash
.venv/bin/python -m securebench.cli auth codex login
```

Complete the browser flow with the ChatGPT account and workspace whose
subscription should be used. If a browser callback is inconvenient, use the
device-code flow:

```bash
.venv/bin/python -m securebench.cli auth codex login --device-auth
```

SecureBench stores this login at:

```text
~/.config/securebench/auth/codex/auth.json
```

To use a different parent directory, set `SECUREBENCH_AUTH_HOME` for login,
status, logout, and benchmark commands:

```bash
export SECUREBENCH_AUTH_HOME="/secure/path/to/securebench-auth"
```

### 3. Check the login

```bash
.venv/bin/python -m securebench.cli auth codex status
```

The status command validates the login and refreshes it if it is close to
expiry.

### 4. Configure the harness

```yaml
harness:
  type: codex
  config:
    auth: subscription
    model: gpt-5.4-mini
    version: latest
    timeout_seconds: 5400
    allow_external_tools: false
```

Do not add `OPENAI_API_KEY`, `CODEX_API_KEY`, or `CODEX_ACCESS_TOKEN` to this
configuration. Subscription mode reads the isolated login instead.

### 5. Run a benchmark

The repository includes a complete example:

```bash
.venv/bin/python -m securebench.cli run \
  --config docs/examples/tester-codex-subscription.yaml \
  --limit 1
```

SecureBench refreshes the ChatGPT access token before expiry. If the provider
returns an authentication failure, the relay forces one token refresh and
retries the request once.

To remove the isolated login:

```bash
.venv/bin/python -m securebench.cli auth codex logout
```

This removes only the SecureBench-owned Codex login. It does not log out your
normal Codex CLI, IDE extension, or ChatGPT application.

## API-Key Mode

API-key mode remains the default, so existing tester files continue to work
without an `auth` field.

For Codex:

```dotenv
OPENAI_API_KEY=your-openai-api-key
```

```yaml
harness:
  type: codex
  config:
    auth: api_key
    model: gpt-5.4-mini
```

For Claude Code:

```dotenv
ANTHROPIC_API_KEY=your-anthropic-api-key
```

```yaml
harness:
  type: claude_code
  config:
    auth: api_key
    model: sonnet
```

API usage and subscription usage are billed and governed by their respective
provider accounts. Select the authentication mode intentionally rather than
assuming that an API key draws from a ChatGPT or Claude subscription.

## Security Model

For all four authentication combinations:

- Real provider credentials stay outside the untrusted agent container.
- The agent receives a dummy API key, dummy bearer token, or synthetic Codex
  auth file.
- The provider relay strips the dummy authentication and injects the real
  host-side credential.
- Credential-bearing requests are limited to the provider's configured
  inference paths and HTTP methods; arbitrary provider-account APIs are not
  reachable through the relay.
- Relay internet access uses a per-run outbound Docker network rather than the
  shared default bridge.
- Provider-hosted tools such as web search remain blocked unless
  `allow_external_tools: true` is explicitly configured.
- When external tools are disabled, malformed or unknown typed tool
  declarations fail closed instead of bypassing inspection.
- Provider credentials and `.env` are never mounted into the task workspace.

For Codex subscription mode specifically, the relay mounts only SecureBench's
isolated Codex credential directory, restricts upstream access to
`/backend-api/codex/`, and performs locked, atomic token rotation.

## Troubleshooting

### Missing Claude subscription token

```text
anthropic provider relay requires environment variable: CLAUDE_CODE_OAUTH_TOKEN
```

Confirm that `.env` contains a non-empty `CLAUDE_CODE_OAUTH_TOKEN`, or pass the
correct file with `--env-file`.

### Missing Codex subscription login

```text
Codex subscription login is required; run `securebench auth codex login`
```

Run the login command, then verify it with `securebench auth codex status`.
Make sure `SECUREBENCH_AUTH_HOME` has the same value for login and benchmark
commands.

### Codex login expired or revoked

Run:

```bash
.venv/bin/python -m securebench.cli auth codex login
```

The new browser login replaces the isolated SecureBench credentials.

### Invalid authentication mode

Both named harnesses accept only:

```yaml
auth: api_key
```

or:

```yaml
auth: subscription
```

### The provider credential was added to `harness.env`

Remove it. The named harnesses obtain provider credentials from their dedicated
host-side authentication source. `harness.env` is only for additional,
tester-selected variables that the agent is allowed to receive.
