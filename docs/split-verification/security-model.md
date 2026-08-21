# Split-verification security model

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

Environment images must be digest-pinned for reproducibility. Pinning establishes
identity, not trust: benchmark images still require provenance review and, where
appropriate, vulnerability scanning. They remain untrusted runtime infrastructure
and must never receive host secrets directly.

## Candidate boundary

Harness output is not a scoreable artifact. After the Agent sandbox stops,
trusted capture exports only the row-declared durable candidate shape. Capture
is bounded, rejects escaping symlinks and special files, protects
framework-owned paths independently of row configuration, and stores canonical
content-addressed manifests and blobs. Replay requires the exact baseline
identity.

The implemented `file_bundle` path reads regular files with no-follow semantics
and change detection. Directory enumeration stops at the row-declared entry
bound rather than first walking an arbitrarily large tree. Directory-tree
symlinks are rejected by default; a row may opt in only to bounded symlinks
whose targets resolve within that same captured tree. Agent command output
is drained without buffering it unboundedly and is capped per stream. Row
workspaces are removed after execution; if the Agent made their permissions
host-inaccessible, cleanup restores only the permissions needed for removal in
a networkless, capability-limited container.

The executable backend also applies framework capacities before Agent launch:
file bundles are limited to 10,000 entries and 256 MiB, while Git patches are
limited to 2,048 changed paths, 128 MiB of changed content, and a 16 MiB
canonical patch. A passive artifact check is limited to 10,000 observed entries
and 256 MiB in aggregate. These ceilings are implementation capacities in
addition to the lower, row-authored bounds.

Paths that cross a host/container boundary are compared conservatively using
Unicode-normalized, case-folded components. This prevents names that alias on a
case-insensitive or normalizing host filesystem from bypassing visibility,
protected-path, mount-collision, or author allow/exclude policies. Structural
containment inside the Linux container workdir remains exact, so a path such as
`/App/result` is not silently treated as being inside `/app`.

For `git_patch`, the digest-pinned image workdir must contain a real, clean Git
repository whose `HEAD` is exactly the row's full lowercase `input.base_commit`.
This is checked before Agent execution and again for each fresh reconstruction.
After the Agent stops, trusted capture mirrors its worktree into a trusted clone,
ignores Agent-controlled Git metadata and framework-owned inputs, enforces row
allow/exclude and materialized bounds, stages all changes, and derives a
canonical full-index, binary-capable patch. An Agent-authored patch file,
stdout, local Git configuration, hooks, and diff drivers are not trusted as the
candidate. Replay requires the same clean commit and verifies that the applied
patch, changed-path manifest, symlinks, and final logical byte count agree.

## Verification and results

Artifact parsers are passive and bounded; candidate code is never imported or
executed on that path. Protocol checks reconstruct the captured candidate from
the immutable image baseline in a fresh writable root for every Challenge. They
mount public and evaluation inputs according to their visibility lanes, run one
reviewed adapter in a networkless Docker container with a read-only container
root filesystem, and pass it only the current bounded JSON challenge. Its
reconstructed candidate workspace is writable but disposable; runtime and
public file resources remain read-only mounts. Hidden Challenge context remains in
the host Oracle. Adapter output must be one finite, duplicate-key-free JSON
value within the row and Adapter bounds.

Parsed artifacts and protocol observations remain internal evidence. Only the
host Oracle may return correctness, score, check outcomes, and bounded public
diagnostics. Candidate-production and capture failures are sent to the Oracle
as Candidate evidence rather than being scored by the runner.

The Adapter format is `securebench.adapter/v2`. Its closed manifest
declares the public protocol ID, command, typed Challenge and Observation
schemas, Evaluation Participants, required Trusted Helpers, Output Artifacts,
and hard maximums. SecureBench assigns a fresh Challenge ID and Evaluation ID
and sends them in a `securebench.adapter-request/v2` envelope. The Adapter must
return exactly one `securebench.adapter-response/v2` envelope containing either
an Observation or an explicit Candidate failure. Adapter timeouts, crashes,
malformed envelopes, and out-of-contract Observations are infrastructure
failures whose source is `adapter`, never Candidate evidence. Adapter responses
cannot contain a verdict.

`securebench.adapter/v2` is the only supported Adapter format. Missing,
different, or malformed formats fail preflight before Candidate production.
Command items beginning with `./` resolve inside the Adapter's declared
read-only mount. Stderr never enters evidence.

Challenge Evidence is internal and binds the check ID, host-generated
Challenge ID, Challenge digest, fresh Evaluation ID, process outcome,
Observation, Trusted Helper evidence, Output Artifact evidence, and any failure
source. Nested evidence is rejected unless its Challenge ID and Evaluation ID
match the enclosing record. Opaque Challenge context remains host-only. Public
results expose only bounded summaries and evidence digests.

The Oracle JSON-lines ABI uses `next_case` responses of either
`{type: exhausted}` or `{type: case, challenge, case_context}`, followed by
`evaluate_case` requests that return the opaque context and framework-built
evidence to the host process. Extra response fields, duplicate JSON keys,
non-finite values, oversized responses, and excess cases fail closed.
The current executable profile accepts declared challenge and observation
bounds up to 1 MiB per Challenge.

Public `results.jsonl` records contain candidate/evidence digests, check
summaries, public diagnostics, and manifest, row, image, baseline, verification,
and execution provenance. Raw Agent
stdout, stderr, metadata, parsed evidence, runtime resources, and host paths are
not serialized. The result component has no live resource view. Resume accepts
only bounded finite, duplicate-key-free JSON records and validates the complete
result envelope, declared checks, stored candidate content, and all
current provenance digests before reusing a row. For a patch candidate, resume
also requires its manifest's `base_commit`, changed-path metadata, and patch blob
to remain valid; the candidate digest binds that manifest while the row and
baseline provenance bind the expected commit and image. One process holds an exclusive
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
  but not executable. The accepted overlay format and threat model are in
  [`filesystem-overlay-v1.md`](filesystem-overlay-v1.md); its row schema and
  static preflight validation do not enable capture or replay.
- Adapter v2, Challenge Evidence, the Trusted Helper Catalog, and bounded
  Output Artifact collection are implemented. `securebench.http-request-recorder/v1`
  is the only executable helper type; unregistered helpers still fail preflight.
- Pack-local Oracle code is trusted and requires review/admission controls.
- The reference Oracle runs as a sanitized host subprocess; stronger OS-level
  Oracle confinement remains future hardening.
- Agent workspaces do not yet have a framework-owned disk quota. Candidate
  capture and observation are bounded, but an Agent can still consume host
  workspace capacity while it is running; deployment-level storage isolation
  is required until a backend quota is implemented.
- Trusted benchmark resources and Git baselines are hash-bound and reviewed,
  but their directory traversal and Git subprocesses do not yet have a
  framework-wide entry-count or wall-clock ceiling. This is not an
  Agent-controlled candidate escape, but a malformed or impractically large
  admitted pack can consume excessive host time or memory during compilation,
  baseline reconstruction, or patch validation.
- Protocol challenge, observation, helper, and artifact payloads have local
  bounds, but the current profile has no aggregate per-row Evaluation budget.
  `max_cases`, cumulative case time, combined helper evidence, and serialized
  Oracle request volume therefore still require admission limits or a
  framework-owned total budget before arbitrarily large reviewed rows are safe
  to execute.
- Candidate blobs are written content-addressably before the manifest commit.
  An interrupted or rejected capture can leave unreferenced, individually
  bounded blobs in the run artifact store. Transactional staging or a
  reference-aware garbage collector is still needed in addition to output
  storage quotas.
