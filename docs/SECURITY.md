# SecureBench security notes

SecureBench treats the Agent, its output, and its workspace as adversarial.

## Separation model

- `public` resources are the only lane visible to the Agent.
- `evaluation_inputs` are available only to the Evaluation runtime.
- `hidden` resources are host-only and may be read by the Oracle.
- The manifest assigns disjoint pack source roots to all three lanes. The
  compiler rejects root overlap, traversal, symlink traversal, and special
  resource types.
- The Agent receives its prompt/input and explicitly mounted read-only public assets. It
  does not receive the verification graph, Oracle location, runtime resources,
  or candidate-capture policy as task content.

## Candidate boundary

Harness output is not a scoreable artifact. After the Agent sandbox stops,
trusted capture exports only the row-declared durable candidate shape. Capture
is bounded, rejects escaping symlinks and special files, protects
framework-owned paths independently of row configuration, and stores canonical
content-addressed manifests and blobs. Replay requires the exact baseline
identity.

The implemented `file_bundle` path reads regular files with no-follow semantics
and change detection. Directory enumeration stops at the row-declared entry
bound rather than first walking an arbitrarily large tree. Agent command output
is drained without buffering it unboundedly and is capped per stream. Row
workspaces are removed after execution; if the Agent made their permissions
host-inaccessible, cleanup restores only the permissions needed for removal in
a networkless, capability-limited container. `git_patch` capture and replay are
implemented as primitives, but repo-patch artifact
materialization/evaluation is deliberately blocked by execution preflight
until its full engine is available.

## Verification and results

Artifact parsers are passive and bounded; candidate code is never imported or
executed on that path. Protocol checks reconstruct the captured candidate from
the immutable image baseline in a fresh writable root for every case. They
mount public and evaluation inputs according to their visibility lanes, run one
reviewed adapter in a networkless Docker container with a read-only container
root filesystem, and pass it only the current bounded JSON challenge. Its
reconstructed candidate workspace is writable but disposable; runtime and
public file resources remain read-only mounts. Hidden case context remains in
the host Oracle. Adapter output must be one finite, duplicate-key-free JSON
value within the row bound.

Parsed artifacts and protocol observations remain internal evidence. Only the
host Oracle may return correctness, score, check outcomes, and bounded public
diagnostics. Timeouts and rejected captures are also sent to the Oracle as
candidate-error evidence rather than being scored by the runner.

The current protocol-adapter ABI is intentionally small. The referenced
runtime directory must contain an exact `adapter.yaml` object with
`abi: securebench.protocol-adapter/v1`, the row's public `protocol` ID, and a
non-empty argument-vector `command`. Command items beginning with `./` resolve
inside the adapter's declared read-only mount. The command receives canonical
JSON plus a newline on stdin and returns its JSON observation on stdout; stderr
never enters evidence. The Oracle JSON-lines ABI adds `next_case` responses of
either `{type: exhausted}` or `{type: case, challenge, case_context}`, followed
by `evaluate_case` requests that return the opaque context and framework-built
evidence to the host process. Extra response fields, duplicate JSON keys,
non-finite values, oversized responses, and excess cases fail closed.
The current executable profile accepts declared challenge and observation
bounds up to 1 MiB per case.

Public `results.jsonl` records contain candidate/evidence digests, check
summaries, public diagnostics, and manifest, row, image, baseline, verification,
and execution provenance. Raw Agent
stdout, stderr, metadata, parsed evidence, runtime resources, and host paths are
not serialized. The result component has no live resource view. Resume validates
the complete result envelope, declared checks, stored candidate content, and all
current provenance digests before reusing a row. One process holds an exclusive
lock on an output directory for the full run. Execution provenance binds the
normalized harness configuration, effective Agent-visible environment values,
and Docker limit overrides; provider credentials filtered from the Agent are
not included.

## Credentials and network

Named provider harnesses keep real credentials host-side and use a relay to
inject them outside the Agent container. Credential-bearing relay requests are
restricted to the provider's inference paths and required HTTP methods. Tool
declarations fail closed when they cannot be inspected, and relay requests and
decision logs are bounded. Provider-hosted external tools are blocked unless
tester configuration explicitly enables them. Generic allowlisted HTTPS egress
requires the TLS SNI to match the CONNECT authority; plain HTTP forwarding
replaces the Agent-supplied Host header with the validated URL host. Row
`agent_network` declares benchmark requirements; harness allowlists remain a
tester-owned upper bound on actual connectivity.

## Current limits

- Result records are not signed.
- Generic TLS egress does not terminate TLS, so it cannot inspect encrypted HTTP
  authority or content after validating CONNECT, DNS, public IPs, and SNI.
- Writable public asset mounts are schema-valid but blocked by current
  execution preflight until composed stopped-filesystem capture is available.
- `filesystem_overlay` and `batched-split/v1` are registered design surfaces
  but not executable.
- Protocol trusted services and returned protocol artifacts are schema-valid
  but not executable yet.
- `git_patch` end-to-end evaluation is not yet executable.
- Pack-local Oracle code is trusted and requires review/admission controls.
- The reference Oracle runs as a sanitized host subprocess; stronger OS-level
  Oracle confinement remains future hardening.
