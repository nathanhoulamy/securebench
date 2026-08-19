# SecureBench security notes

SecureBench treats the Agent, its output, and its workspace as adversarial.

## Separation model

- `public` resources are the only lane visible to the Agent.
- `evaluation_inputs` are available only to a future evaluation runtime.
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
executed. Parsed observations remain internal evidence. Only the host Oracle
may return correctness, score, check outcomes, and bounded public diagnostics.
Timeouts and rejected captures are also sent to the Oracle as candidate-error
evidence rather than being scored by the runner.

Public `results.jsonl` records contain candidate/evidence digests, check
summaries, public diagnostics, and manifest/row/image/baseline/verification
provenance. Raw Agent
stdout, stderr, metadata, parsed evidence, runtime resources, and host paths are
not serialized. Resume validates the complete result envelope and all current
provenance digests before reusing a row.

## Credentials and network

Named provider harnesses keep real credentials host-side and use a relay to
inject them outside the Agent container. Provider-hosted external tools are
blocked unless tester configuration explicitly enables them. Row
`agent_network` declares benchmark requirements; harness allowlists remain a
tester-owned upper bound on actual connectivity.

## Current limits

- Result records are not signed.
- Writable public asset mounts are schema-valid but blocked by current
  execution preflight until composed stopped-filesystem capture is available.
- `filesystem_overlay`, protocol checks, and `batched-split/v1` are registered
  design surfaces but not executable.
- `git_patch` end-to-end evaluation is not yet executable.
- Pack-local Oracle code is trusted and requires review/admission controls.
- The reference Oracle runs as a sanitized host subprocess; stronger OS-level
  Oracle confinement remains future hardening.
