# Dead Code Sweep Report

Date: 2026-07-25

Scope: full SecureBench Python package, CLI, tests, documentation references,
packaging metadata, and untracked build artifacts.

Method: repository inventory, reference searches, AST/token occurrence checks,
runtime-path tracing, test/import inspection, dependency review, exact-duplicate
comparison, and independent orphan/redundancy/security reviews.

## Summary

- No orphaned production modules, broken test imports, skipped test suites, or
  unused runtime dependencies were found.
- Five high-confidence cleanup groups are ready to remove or consolidate.
- Two broader provider-harness consolidations need a separate refactor because
  they affect live shared infrastructure.
- The untracked `build/` directory is a stale generated source mirror. It is
  safe to regenerate, but it is user-owned and should not be deleted without
  explicit approval.
- Estimated removable tracked code: roughly 120-150 lines, plus tests that
  assert the dead implementation.

## Ready to Remove

### Dead Codex file-based configuration path

Locations:

- `securebench/harnesses/codex.py`: `CODEX_CONFIG_TARGET`, `config_cleanup`,
  `config_root`, the config bind mount, `write_codex_relay_config`,
  `write_codex_config`, and `write_codex_subscription_config`
- `tests/test_harnesses.py`: direct tests of the unused config-file writers

Evidence:

- The generated directory is mounted at `/opt/securebench/codex-config`.
- Runtime `HOME` and `CODEX_HOME` both point to
  `/opt/securebench/codex-home`.
- No command or environment variable references the config mount.
- All effective Codex settings are supplied through `codex_config_args()` as
  `-c` command-line options.

Risk: low. Preserve the active command-line configuration tests.

### Orphan audit helpers

Locations:

- `securebench/audit/static_checks.py`: `default_output_dir`
- `securebench/audit/smoke.py`: `temp_output_dir`

Evidence: each symbol occurs only at its definition and has never had a caller.
Their `Path` and `tempfile` imports also become unused.

Risk: low.

### Duplicate OAuth document reader

Location: `securebench/harnesses/codex_oauth.py`

Evidence: `load_codex_oauth_credentials()` duplicates the JSON read and error
translation already implemented by `_read_auth_document()`.

Action: route the public loader through `_read_auth_document()`.

Risk: low; preserve the existing public error messages.

### Unused returned ID-token state

Location: `CodexOAuthCredentials.id_token` in
`securebench/harnesses/codex_oauth.py`

Evidence: ID-token claims are required while parsing the stored document, but
the token is never read after the credentials object is returned.

Risk: low to medium because the dataclass is importable. Remove only if it is
not intended as public API.

### Redundant CLI exception name

Location: `securebench/cli.py`

Evidence: `CodexOAuthError` subclasses `OSError`, so listing both in the same
exception tuple is redundant.

Risk: low.

## Needs Review

### Claude/Codex shared harness utilities

Live implementations duplicate validation, environment checks, overlay cache
paths, prompt construction, work-directory selection, and configuration parsing.
Claude also imports generic overlay and repository-baseline helpers from the
Codex module, making Codex an accidental shared base.

Recommendation: move genuinely provider-neutral pieces into
`securebench/harnesses/shared.py` or a focused overlay helper module in a
separate refactor. Do not combine this with the subscription-auth cleanup
because the blast radius is substantially larger.

### `HarnessEgress` result fields

`allowed_domains` and `allow_external_tools` are populated but not consumed by
production callers; tests inspect them. They may be intentional public
diagnostic state, so removal requires an API decision.

### Defensive CLI branches

The unsupported-provider/action branches in `_auth()` are unreachable through
the current required `argparse` choices, but they protect direct/private calls
and future parser changes. Keeping them is reasonable.

### Generated `build/` directory

The untracked `build/` directory contains a stale copy of the package (49 files,
approximately 8,589 Python lines) and lacks the new subscription code. It is not
used by packaging or tests.

Recommendation: delete it as a generated artifact and add `build/` to
`.gitignore` if local builds routinely recreate it. Deletion requires explicit
approval because the directory predates this sweep and is untracked.

## Keep

- `securebench/harnesses/codex_oauth.py`: reachable from the CLI, harness,
  relay sidecar mount, and provider relay.
- Harness and verifier registries: dynamically selected from tester/task
  configuration.
- `PyYAML`: the sole runtime dependency and actively used.
- Subscription examples and provider-authentication guide: both examples are
  linked from the README and match active configuration fields.

## Correctness and Security Findings Addressed During the Sweep

These were not dead-code removals, so they were fixed immediately:

- Rejected traversal, encoded, backslash, duplicate-slash, fragment, and
  control-character variants in the Codex subscription upstream path allowlist.
- Moved relay/proxy outbound access off Docker's shared default bridge and onto
  a per-run upstream network.
- Validated refreshed OAuth JWTs before atomically replacing stored credentials.
- Closed OAuth refresh responses and hid secret token fields from dataclass
  representations.
- Added cross-platform credential-file locking imports and made Docker host UID
  mapping conditional.
- Extended synthetic in-container token lifetime so long benchmarks do not try
  to refresh dummy credentials.
