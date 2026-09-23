# write-compressor qualification material

`reference.comp` is a correct 2264-byte `data.comp` for the pinned `data.txt`.

It was produced by compiling the upstream reference compressor
`benchmarks/terminal-bench/docker/write-compressor/main.rs` with `rustc -O`
inside the pinned task image and running it over `data.txt`. The same run
compiled the public `decomp.c` with `gcc -O3` and confirmed the C decoder
reproduces `data.txt` byte-for-byte from this file.

The Oracle's independent Python decoder was then checked against this artifact
and produced identical output, which is the conformance evidence that the
memory-safe reimplementation matches the C semantics.

`main.rs` is deliberately **not** shipped in the task image: the Dockerfile
copies only `decomp.c` and `data.txt`. Keep it out of the Agent environment.
