# `vim-runtime` provenance

This directory vendors the exact packages upstream's own verifier installs at
verification time (`benchmarks/terminal-bench/hidden/headless-terminal/tests/test.sh:4-5`
runs `apt-get install -y vim` before the pytest suite). Split verification
evaluates against a networkless Evaluation container, so the packages are
fetched once during conversion and mounted read-only instead of being
downloaded live.

## How this was built

1. Pulled the row's pinned image digest and confirmed it is Debian 12
   (bookworm), `amd64`, with no `vim`/`vi` present:

   ```
   docker pull alexgshaw/headless-terminal@sha256:eb7e209672bf6cef2785fafd9e13509b10626c327bcc2b37f5bf40ca83eaf3aa
   ```

2. Ran a dependency-resolution dry run against that exact image (`apt-get
   install -y -s vim`) to get the identical package set and versions upstream's
   `apt-get install -y vim` would install there:

   | Package | Version | Architecture |
   |---|---|---|
   | `vim` | `2:9.0.1378-2+deb12u2` | amd64 |
   | `vim-common` | `2:9.0.1378-2+deb12u2` | all |
   | `vim-runtime` | `2:9.0.1378-2+deb12u2` | all |
   | `xxd` | `2:9.0.1378-2+deb12u2` | amd64 |
   | `libgpm2` | `1.20.7-10+b1` | amd64 |
   | `libsodium23` | `1.0.18-1+deb12u1` | amd64 |

   No recommended/suggested packages beyond this set are pulled in (`apt-get
   install -y vim` only adds these six; `gpm`, `ctags`, `vim-doc`, `vim-scripts`
   are merely *suggested*, never installed by upstream's plain command either).

3. Downloaded the `.deb` archives for that resolved set from
   `http://deb.debian.org/debian bookworm/main` (`apt-get install
   --download-only`), inside a container started from the same pinned image
   digest, and recorded their SHA-256 digests:

   | Package `.deb` | SHA-256 |
   |---|---|
   | `vim_2%3a9.0.1378-2+deb12u2_amd64.deb` | `298464600a708a3cc7fd7e55a7719dd1adfa8d2de1645c3ecbd05b5d24ffae73` |
   | `vim-common_2%3a9.0.1378-2+deb12u2_all.deb` | `2092c7bb95334a28ed29630fdcaf0f11a92a5859922318a23bbcd6aa4fbcbf5c` |
   | `vim-runtime_2%3a9.0.1378-2+deb12u2_all.deb` | `6a3dd2317a593742cb247f3494d986b3127887dbe1449253b8efa6112289854e` |
   | `xxd_2%3a9.0.1378-2+deb12u2_amd64.deb` | `892777cf6a60fefcc45d90a8b6b8f91f024d370b011dcf58dbf2686a9f9a55d7` |
   | `libgpm2_1.20.7-10+b1_amd64.deb` | `2ac1236547360284e9e154ad11a14564db65175bd4da393ec652ac1b2dc43571` |
   | `libsodium23_1.0.18-1+deb12u1_amd64.deb` | `bceae6943d6e11fb53ec3f81d9630ec9ed03e51f89364902b05ebe402ae946ec` |

   (Debian rewrites `:` as `%3a` in the on-disk archive filename; the actual
   package `Version:` field is `2:9.0.1378-2+deb12u2`.)

4. Extracted each archive's data payload only (`dpkg-deb -x <deb> root/`) —
   maintainer scripts (`postinst`/`postrm`) were never executed, so no
   package-manager state (`dpkg` status database, `update-alternatives`
   registrations) exists under `root/`.

5. `update-alternatives` would normally create `/usr/bin/vim ->
   /etc/alternatives/vim -> /usr/bin/vim.basic`. Since maintainer scripts did
   not run, this repository adds the single equivalent symlink directly:
   `root/usr/bin/vim -> vim.basic`. This is the only manually added file; every
   other byte under `root/` comes verbatim from the six `.deb` payloads above.

6. Verified end-to-end in a fresh, network-disabled container built from the
   same pinned image digest, mounting only `root/` read-only at
   `/opt/securebench/runtimes/vim` and setting `PATH`, `VIM`, `VIMRUNTIME`, and
   `LD_LIBRARY_PATH` (see `adapter/adapter.py`): `vim --version` runs, and a
   scripted `tmux`-driven insert/write/quit session (matching the restored
   `interactive` Oracle case) produces the expected file content with no
   network access.

`libtinfo`, `libselinux`, `libacl`, and `libpcre2` — vim's remaining dynamic
dependencies — are already present in the pinned image and are not vendored
here.

## Size

`root/` is ~45 MB, matching the ~42 MB upstream's own `apt-get install -y vim`
reports it will add to the image (`After this operation, 41.9 MB of additional
disk space will be used.`). It is mounted read-only into the Evaluation
container only; it is never visible to the Agent environment and is not part
of the captured Candidate.
