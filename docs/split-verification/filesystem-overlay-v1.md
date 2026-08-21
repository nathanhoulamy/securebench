# Filesystem overlay v1

Status: Phase 1 review candidate; `filesystem_overlay` remains non-executable.

This document specifies the first reviewable filesystem-overlay Candidate
format and its threat model. It does not enable capture or replay. The
author-facing schema migration, quota backend, implementation, and activation
are separate security gates.

## Purpose and trust boundary

A filesystem overlay is one bounded, durable diff between selected directory
roots in a digest-pinned image and the stopped Agent filesystem. It is for
terminal and system-configuration tasks whose durable result cannot be
represented as a Git patch or a small set of complete output files.

The overlay is not a container snapshot. SecureBench must never capture a
Docker writable layer, container export, process, mount, connection,
credential, temporary filesystem, or in-memory state. Only changes below the
row's reviewed include roots may enter the Candidate.

The Agent, its final filesystem, path names, file contents, metadata, and
symlink targets are adversarial. The pinned image, framework code, admitted
row, and baseline materializer are trusted inputs, but malformed or oversized
trusted inputs must still fail within framework bounds.

## Planned row contract

The Phase 2 schema gate will replace the current unused overlay limit names.
There is no compatibility path because the existing overlay schema has never
been executable.

~~~yaml
candidate:
  type: filesystem_overlay
  include_roots:
    - /app
    - /etc/example-service
  max_changed_paths: 20000
  max_changed_bytes: 536870912
  allow_internal_symlinks: false
~~~

`include_roots` are canonical, absolute, non-overlapping POSIX directories
that must exist in the pinned image. The image workdir must be equal to or
below one include root. The include-root directory itself is a framework-owned
mount point: it cannot be deleted, replaced, or have Candidate-controlled
metadata.

`max_changed_paths` counts every changed descendant. A recursively deleted
directory does not count as one cheap operation: the directory and every
removed descendant each consume one path. `max_changed_bytes` counts the full
logical bytes of every changed final regular file plus the UTF-8 bytes of every
changed final symlink target. Directories and deletions contribute zero bytes.
A one-byte edit to a 1 GiB file therefore consumes 1 GiB.

`allow_internal_symlinks` defaults to `false`. When enabled, only changed or
new symlinks whose relative targets remain lexically inside the same include
root are permitted. Trusted baseline symlinks may remain unchanged even when
their targets leave an include root; changing such a link requires the same
internal-target rule as a new link.

## Normalized filesystem semantics

Version 1 supports only:

- regular files, normalized to `0644` or `0755` according to whether any
  executable bit is set;
- directories, normalized to `0755`;
- explicit deletions; and
- opt-in internal symlinks with no captured mode.

The baseline materializer normalizes supported ownership to UID 0 and GID 0.
Capture rejects a final supported node with different ownership. Version 1
does not represent ownership changes. Executable v1 rows therefore require a
Linux image whose Agent process runs as UID 0 and GID 0 under dropped
capabilities and `no-new-privileges`; images requiring a different execution
identity are excluded rather than silently remapped.

Capture rejects hardlinks, setuid or setgid state, ACLs, extended attributes,
devices, sockets, FIFOs, nested mounts, and every other special file. The
baseline admission scan rejects include roots that already require any of
those semantics. SecureBench must exclude a benchmark rather than silently
discard unsupported metadata.

Paths and symlink targets must be valid UTF-8. A relative entry path is
canonical POSIX text with no empty component, `.`, `..`, backslash, or NUL;
its encoded length is at most 4,096 bytes and its depth at most 128
components. A changed symlink target is at most 4,096 bytes. Paths that alias
after NFC normalization and case folding are rejected even when the current
Linux filesystem would distinguish them.

## Protected paths

Rows cannot weaken the protected-path policy. An include root is rejected if
it is equal to, inside, or an ancestor of a permanently protected path:

- kernel and runtime state: `/proc`, `/sys`, `/dev`, `/run`, `/var/run`,
  `/tmp`, and `/var/tmp`;
- container runtime state: `/var/lib/docker`, `/var/lib/containerd`, and
  `/run/containerd`;
- account and host credentials: `/root`, `/etc/passwd`, `/etc/group`,
  `/etc/shadow`, `/etc/gshadow`, `/etc/subuid`, `/etc/subgid`, `/etc/sudoers`,
  `/etc/sudoers.d`, and `/etc/ssh`;
- package-manager configuration and state: `/etc/apt`, `/etc/dnf`,
  `/etc/yum.repos.d`, `/etc/pacman.conf`, `/etc/pacman.d`, `/var/lib/apt`,
  `/var/lib/dpkg`, `/var/lib/rpm`, `/var/lib/pacman`, `/var/cache/apt`,
  `/var/cache/dnf`, and `/var/cache/yum`; and
- the filesystem root `/` itself.

Preflight also rejects overlap with dynamic framework-owned locations,
including provider credentials, Agent tool state, the task-instruction file,
Docker sockets, framework control paths, and Evaluation-runtime resources.
These locations must be mounted outside overlay roots before capture becomes
executable.

A read-only public asset may be mounted below an include root only when its
exact target and every required mount-parent path are reserved. The asset is
not part of the overlay; capture must prove that the underlying reserved paths
did not change. An Artifact or Output Artifact may not select a reserved mount
path as Candidate state.

## Canonical tree identity

SecureBench scans each include root without following symlinks. A canonical
tree document contains the absolute root and all descendant nodes sorted by
the UTF-8 bytes of their relative paths. It has exactly this shape:

~~~json
{
  "format": "securebench.filesystem-tree/v1",
  "root": "/app",
  "nodes": [],
  "entries": 0,
  "bytes": 0
}
~~~

`entries` equals the number of nodes. `bytes` is the sum of regular-file
logical sizes and symlink-target UTF-8 sizes; directories contribute zero.
Each node has exactly one of these shapes:

~~~json
{"path":"bin","kind":"directory","mode":493}
{"path":"bin/tool","kind":"regular_file","mode":493,"size":12,"digest":"sha256:..."}
{"path":"current","kind":"symlink","target":"releases/current"}
~~~

The tree digest is SHA-256 over the UTF-8 canonical JSON encoding of this
document: object keys are sorted, arrays are already in required order,
separators are `,` and `:`, non-ASCII characters are emitted directly,
non-finite numbers are forbidden, and one trailing newline is included.

The task's existing Candidate `baseline_digest` binds the row, pinned image,
workdir, and public assets. Per-root baseline tree digests additionally prove
the actual normalized filesystem bytes used for capture and replay. A final
tree digest proves that replay produced the captured final state.

Framework capacities, which rows may only reduce, are initially fixed at:

- 16 include roots;
- 100,000 aggregate entries in either the baseline or final trees;
- 8 GiB aggregate logical bytes in either the baseline or final trees;
- 50,000 changed paths;
- 4 GiB changed logical bytes;
- 4,096 path bytes and 128 path components;
- 4,096 symlink-target bytes; and
- 120 seconds for one aggregate baseline or final-tree scan.

Deployment policy may impose smaller capacities. Exceeding a baseline
capacity rejects the row before Agent execution. Exceeding a final-tree or
Candidate limit rejects Candidate capture.

## Stored Candidate payload

The outer Candidate manifest remains the existing content-addressed manifest:

~~~json
{
  "schema_version": "1",
  "type": "filesystem_overlay",
  "baseline_digest": "sha256:...",
  "payload": {}
}
~~~

Its `payload` has exactly this top-level shape:

~~~json
{
  "format": "securebench.filesystem-overlay/v1",
  "roots": [
    {
      "path": "/app",
      "baseline_tree_digest": "sha256:...",
      "baseline_entries": 10,
      "baseline_bytes": 2048,
      "final_tree_digest": "sha256:...",
      "final_entries": 11,
      "final_bytes": 3072
    }
  ],
  "changes": [],
  "changed_paths": 0,
  "changed_bytes": 0
}
~~~

Roots are sorted by the UTF-8 bytes of their absolute paths. Changes are
sorted by root path and then relative path using UTF-8 byte order. Duplicate
or portable-aliasing roots or change paths are invalid. Empty overlays are
valid.

Each change has exactly one of these forms:

~~~json
{"root":"/app","path":"old.txt","kind":"absent"}
{"root":"/app","path":"results","kind":"directory","mode":493}
{"root":"/app","path":"results/value.json","kind":"regular_file","mode":420,"size":12,"digest":"sha256:...","chunks":[{"digest":"sha256:...","size":12}]}
{"root":"/app","path":"current","kind":"symlink","target":"results/value.json"}
~~~

Regular-file content is split deterministically into consecutive 4 MiB chunks;
only the final chunk may be smaller. Empty files have no chunks and use the
SHA-256 digest of empty bytes. Every chunk is stored as an independently
verified Candidate blob. `size` equals the sum of chunk sizes and `digest` is
the SHA-256 digest of the complete logical file bytes.

The change set is derived from the union of baseline and final paths. A path
is unchanged only when its normalized kind, mode, content digest, or symlink
target is identical. Type replacements use the final node at the replaced
path and explicit `absent` changes for every removed descendant.

### Representative changes

Adding `results/value.json` stores one `regular_file` change with its complete
logical digest and chunks. Modifying one byte or changing only its normalized
mode uses the same form and charges the full final file size.

Deleting this baseline tree:

~~~text
cache/
cache/a
cache/nested/
cache/nested/b
~~~

stores four `absent` changes. Replacing that directory with one regular file
stores `absent` for its three descendants and one `regular_file` change for
`cache`; all four paths count toward `max_changed_paths`.

With symlinks enabled, a change at `current` with target
`releases/current` is valid. Targets `/etc/shadow` and `../../etc/shadow` are
invalid because they leave the include root. With symlinks disabled, every
new or changed symlink is invalid.

A change path such as `../etc/shadow`, a second path that aliases `Config`
as `config`, an include root `/etc`, and an include root containing a runtime
resource mount all fail before their bytes can enter a Candidate.

The Candidate manifest and all new chunks become visible atomically. Failed
or interrupted capture must remove its staging data and may not leave newly
written unreferenced chunks in the durable store.

## Capture flow

1. Prove the Linux quota backend and create one bounded, framework-owned
   workspace volume.
2. Materialize and normalize every admitted include root from the pinned
   image, then record its baseline tree digest.
3. Mount one volume subdirectory at each include root. Keep the remaining
   container root read-only and framework state outside those roots.
4. Run the Agent within its time, memory, process, network, and disk limits.
5. Stop the Agent container. No Agent process may remain during capture.
6. Mount the volume read-only into a trusted collector, scan final roots, and
   derive the bounded canonical diff.
7. Transactionally store exactly one Candidate, then destroy the Agent
   container, volume, loop mount, backing file, and temporary collector state.

The disk quota applies while the Agent runs. Post-run Candidate bounds do not
substitute for it. Failure to prove quota enforcement leaves overlays
non-executable.

## Replay flow

Every Artifact observation and every protocol Challenge starts from a fresh
bounded workspace volume:

1. Materialize the same pinned baseline and verify every stored baseline tree
   digest before applying Candidate state.
2. Strictly validate the Candidate manifest, ordering, totals, chunk sizes,
   and all content digests.
3. Remove explicit deletions and type-conflicting baseline nodes deepest
   first without following symlinks.
4. Create directories shallowest first, write regular files through bounded
   temporary files followed by atomic rename, and create validated symlinks.
5. Apply normalized directory modes deepest first.
6. Rescan every root and require the stored final tree digests and totals to
   match before Candidate-controlled code executes.
7. Mount the reconstructed roots into one fresh Evaluation and destroy all
   Evaluation-local state afterward.

Replay never executes a Candidate file. A protocol Adapter may execute or
exercise Candidate state only after replay verification succeeds.

## Failure ownership

- Invalid row roots, protected-path overlap, unsupported baseline semantics,
  baseline capacity overflow, or unavailable quota capability fail preflight
  before the Agent starts.
- Unsupported or oversized final Agent state, changed ownership, escaping
  links, special files, and row-limit overflow reject Candidate capture and
  become bounded Candidate-production error evidence.
- An Agent or Candidate process that exhausts its enforced quota is a
  Candidate resource failure; inability of the backend to enforce the quota
  is an infrastructure failure.
- Candidate-store corruption, baseline reconstruction mismatch, trusted
  scanner/parser failure, replay mismatch, and cleanup failure are sanitized
  infrastructure failures. They are never converted into an Oracle verdict.

## Phase 1 security review checklist

- [x] One bounded durable Candidate; no live or whole-container state.
- [x] Exact baseline and final tree identities.
- [x] Canonical add, modify, delete, type-replacement, directory, and symlink
  representations.
- [x] Deletion descendants charged to the changed-path limit.
- [x] Deterministic ordering, chunking, hashing, and atomic publication.
- [x] Explicit mode and ownership normalization.
- [x] Hardlinks, extended metadata, mounts, and special files rejected.
- [x] Permanent and dynamic protected-path policy.
- [x] Runtime disk quota required before activation.
- [x] Fresh verified replay and cleanup required for every Evaluation.
- [x] Candidate and infrastructure failure sources kept distinct.

Phase 2 may implement the row-schema and preflight portion of this contract,
but it must retain the unconditional non-executable overlay gate.
