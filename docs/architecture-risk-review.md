# SecureBench Architecture Risk Review

This review focuses on high-level architectural safety, not line-by-line code
quality. It assumes SecureBench is intended to run agentic benchmark tasks where
candidate-producing agents may be adversarial, but the local runner operator is
trusted.

## Architecture Summary

SecureBench has a sensible core separation:

- The host runner loads tester YAML, benchmark packs, `.env`, and provider keys.
- The agent sandbox receives public task data only.
- Named provider harnesses use dummy in-container keys and a host-side provider
  relay to inject real credentials.
- Generic egress is disabled unless `allowed_domains` is configured.
- Verification runs separately from candidate production, with candidate patches
  or workspaces treated as untrusted input.
- Resource visibility is modeled explicitly as `public`, `evaluation_inputs`,
  and `hidden`.

That model is directionally sound. The main risks are not "AI wrote some code."
The main risks are places where the architecture depends on social trust,
mutable infrastructure, or retained artifacts rather than enforcing the desired
boundary mechanically.

## Highest-Risk Architectural Questions

### 1. What is the trust status of benchmark packs and images?

Current docs say benchmark images and tester YAML are authored inputs. The code
allows benchmark rows and manifests to select Docker images, test commands,
checkers, assets, and candidate policies. This is fine if benchmark packs are
trusted research artifacts. It is not fine if SecureBench is expected to safely
run arbitrary third-party packs.

Why it matters:

- Repo-patch verifier commands are benchmark-authored command arrays executed in
  the benchmark image.
- Terminal-task checkers are benchmark-authored pytest or shell scripts executed
  in the benchmark image.
- The benchmark image is used for both agent execution and verification.
- Mutable image tags can change between candidate production and later review.

Architectural decision needed:

- Define two explicit modes: `trusted-pack` and `untrusted-pack`.
- In `trusted-pack` mode, the current model is acceptable with provenance and
  reproducibility hardening.
- In `untrusted-pack` mode, benchmark images/checkers/test commands must be
  treated as hostile, and Docker alone is probably not a sufficient isolation
  story for secrets, host safety, or meaningful scoring.

Recommended hardening:

- Require image digests, not mutable tags, for publishable benchmark runs.
- Record image digests, task row digest, manifest digest, checker digest, and
  verifier code version in every result.
- Add a preflight that refuses unpinned images unless the run is explicitly
  marked experimental.
- Consider a stronger sandbox boundary for untrusted packs, such as rootless
  Docker, user namespaces, or microVM isolation.

### 2. Terminal-task verification can persist evaluation inputs into retained workspaces.

The terminal-task verifier materializes the `test_sandbox` view into the
candidate workspace before running checks. That correctly prevents the agent from
seeing evaluation inputs during candidate production, because the workspace is
reset before each fresh producer run. But after verification, retained run
workspaces can contain `securebench/evaluation_inputs/...`.

Why it matters:

- `runs/<run-id>/workspaces/` is advertised as a run output.
- A public benchmark result bundle could accidentally include verifier-only data.
- Future resume/review tooling may consume workspaces that have already been
  contaminated with evaluation inputs.
- The docs imply evaluation inputs are verifier-only, but retained artifacts do
  not fully preserve that property.

Architectural decision needed:

- Decide whether retained candidate workspaces are public artifacts.
- If yes, verification must never write eval inputs into those retained
  workspaces.
- If no, run outputs need a clear classification and access policy.

Recommended hardening:

- Verify terminal tasks from a fresh temporary verification workspace copied from
  the candidate workspace, then destroy it after scoring.
- Alternatively, mount eval inputs from a separate host directory directly into
  the verifier container and never copy them under the candidate workspace root.
- Add an audit probe that fails if any retained workspace contains
  `securebench/evaluation_inputs` or `securebench/evaluator` after a run.

### 3. Result integrity is currently too weak for benchmark claims.

The docs already identify that result records are unsigned, `--resume` trusts
existing `candidates.jsonl`, and result records lack full pack/verifier digests.
This is an architectural issue because SecureBench is a measurement system. If
results can be edited or resumed from stale inputs, scores are not durable
evidence.

Why it matters:

- A modified `candidates.jsonl` can cause `--resume` to skip tasks.
- A result can outlive the benchmark image, manifest, task rows, and verifier
  code that produced it.
- Reproducibility requires proving which exact benchmark and verifier were used.

Recommended hardening:

- Treat resume records as untrusted unless a result digest/signature matches the
  current manifest, task row, verifier, harness config, and image digest.
- Add append-only run logs or result signing.
- Include enough provenance in each record to re-run or audit one task
  independently.

### 4. Provider relay policy is schema-sensitive.

The provider relay blocks known hosted tool types by inspecting JSON request
bodies and top-level `tools`. This is useful, but it is not a proof that future
provider APIs or CLI versions cannot express external capabilities in a new
shape.

Why it matters:

- The relay forwards arbitrary methods and paths to the provider host.
- The denylist depends on known tool type strings and prefixes.
- `allow_external_tools: true` intentionally bypasses the tool block.
- Agent CLI versions are installed dynamically by version string, including
  `latest`.

Recommended hardening:

- Pin or record exact CLI package versions for scored runs.
- Prefer allowlisting known-safe provider request shapes over denylisting known
  unsafe tools.
- Add relay tests for every provider API surface used by supported CLI versions.
- Record relay decision logs as run artifacts after redaction, or at least record
  their digest and summary.

### 5. Network policy is good for default isolation, not for data-loss prevention.

Default no-network behavior is strong. When `allowed_domains` is set, the proxy
limits hostnames to public DNS destinations on HTTP/HTTPS and rejects private IP
resolutions. That helps prevent SSRF-style local access. It does not prevent an
agent from exfiltrating public/evaluation-observable data to an allowed domain.

Why it matters:

- `allowed_domains` is an escape hatch, not a confidentiality boundary.
- Any allowed public endpoint can receive arbitrary query strings or request
  bodies.
- Provider-hosted tools are a separate path and are controlled by
  `allow_external_tools`, not by `allowed_domains`.

Recommended hardening:

- Label runs with non-empty `allowed_domains` as network-enabled in result
  metadata and benchmark summaries.
- Treat network-enabled runs as incomparable with fully offline runs unless the
  benchmark explicitly requires network.
- Keep external provider tools disabled for standard benchmark scoring.

### 6. The command harness is not equivalent to named provider harnesses.

The `command` harness passes tester-selected environment variables directly into
the agent container. This makes it useful for local experiments, but it has a
different security model from `codex` and `claude_code`, which keep provider
keys behind a relay.

Recommended hardening:

- Document `command` as tester-trusted and not safe for untrusted agents with
  real secrets.
- Emit a warning when `command` receives any environment variable whose name
  looks secret-bearing.
- Consider requiring explicit `--allow-secret-env-to-command` for names matching
  `*_KEY`, `*_TOKEN`, `*_SECRET`, or `*_PASSWORD`.

### 7. Logs and stdout/stderr can leak sensitive data.

Result records include producer and verifier stdout/stderr. Verifier metadata
redacts exact hidden values, but stdout/stderr are not generally scrubbed. If a
checker prints hidden data or an agent echoes sensitive context, result records
can leak it.

Recommended hardening:

- Treat all logs as potentially sensitive unless a run is marked publishable.
- Add optional redaction over stdout/stderr using exact hidden values and known
  secret patterns.
- Prefer structured verifier result fields over printing sensitive diagnostics.

## What Looks Architecturally Strong

- Resource visibility is explicit and centrally modeled.
- Agent materialization excludes non-public resources.
- File-backed eval resources are resolved under benchmark pack roots and
  symlinks are rejected.
- Docker sandbox defaults drop capabilities, use no-new-privileges, memory and
  PID limits, read-only root filesystem, tmpfs for `/tmp`, and no network.
- Named provider harnesses use dummy in-container keys and host-side relay
  credential injection.
- Generic egress allowlists domains, rejects IP literals in config, restricts
  ports to 80/443, and rejects DNS answers that are not public unicast.
- Repo-patch verification checks declared base commit, enforces candidate path
  policy before and after patch application, and blocks common test/CI/dependency
  tampering paths by default.
- Terminal-task checkers run from trusted eval assets and pytest execution
  removes candidate-owned import paths.
- Built-in audit smoke tests cover several important malicious patterns.

## Invariants SecureBench Should State Explicitly

SecureBench should document and test these as product invariants:

- Agents must only see public resources during candidate production.
- Real provider credentials must never enter the agent workspace or agent
  container environment for named provider harnesses.
- Evaluation inputs must not appear in publishable artifacts unless explicitly
  marked public.
- Hidden resources must never enter the agent or test sandbox.
- Verification must not trust candidate-controlled code, paths, wrappers, test
  infrastructure, or shell startup files.
- A benchmark score must bind to exact benchmark inputs, verifier code, harness
  config, and environment image digest.
- Resuming a run must not allow stale or forged records to influence scores.
- Network-enabled and external-tool-enabled runs must be clearly distinguished
  from offline runs.

## Proposed Validation Plan

1. Add artifact-contamination tests for terminal-task runs:
   - Run a terminal-task benchmark.
   - Assert retained output workspaces do not contain evaluation or evaluator
     material.
   - If current behavior is intentional, classify those workspaces as restricted
     artifacts in docs and output metadata.

2. Add provenance tests:
   - Ensure every result includes manifest digest, task-row digest, verifier
     digest/version, harness config digest, and Docker image digest.
   - Ensure `--resume` rejects records whose provenance does not match.

3. Add provider relay compatibility tests:
   - For each supported CLI/provider version, capture representative API
     requests.
   - Assert hosted tools are blocked when `allow_external_tools` is false.
   - Assert client/local tool calls still work.

4. Add unpinned-image tests:
   - Refuse mutable image tags for publishable runs.
   - Allow them only under an explicit experimental flag.

5. Add command-harness secret tests:
   - Warn or fail when `command` receives secret-like environment variables
     without explicit opt-in.

6. Add log redaction tests:
   - Verify exact hidden values are removed from verifier metadata, stdout, and
     stderr when publishable output is requested.

7. Add pack-trust-mode tests:
   - `trusted-pack` allows current benchmark-authored commands and images with
     provenance checks.
   - `untrusted-pack` either refuses unsafe features or runs under a stronger
     sandbox profile.

## Bottom Line

SecureBench's central architecture is defensible for trusted benchmark packs and
adversarial candidate agents. The biggest unsafe assumption would be presenting
it as safe for arbitrary third-party benchmark packs or as producing
cryptographically durable benchmark evidence. The highest-priority fixes are:

1. Stop terminal-task verification from contaminating retained candidate
   workspaces with evaluation inputs, or classify those workspaces as restricted.
2. Add result provenance, digests, and resume validation.
3. Require pinned/auditable benchmark images for publishable results.
4. Make pack trust mode explicit.
5. Strengthen provider relay policy against API schema drift.
