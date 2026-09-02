# `gpt2-codegolf`

> Portfolio status: See [inventory.csv](../inventory.csv) for the authoritative review decision.

## Source facts

| Field | Value |
|---|---|
| Benchmark | Terminal-Bench 2.0 |
| Source row | [`gpt2-codegolf`](https://github.com/harbor-framework/terminal-bench-2/tree/2fd12b88aafdd04a52c298e3940bcb189f9766d6/gpt2-codegolf) |
| Source snapshot | `2fd12b88aafdd04a52c298e3940bcb189f9766d6` |
| Difficulty | hard |
| Category | software-engineering |
| Tags | software-engineering |
| Agent timeout | 900.0 seconds |
| Verifier timeout | 900.0 seconds |
| Candidate image | `alexgshaw/gpt2-codegolf:20251031` |
| Internet allowed | `True` |

## Goal in simple terms

Evaluates the ability to implement a minimal, dependency-free C program that performs GPT-2 inference from TensorFlow checkpoints in under 5000 bytes.

### Public instruction, condensed

I have downloaded the gpt-2 weights stored as a TF .ckpt. Write me a dependency-free C file that samples from the model with arg-max sampling. Call your program /app/gpt2.c, I will compile with gcc -O3 -lm. It should read the .ckpt and the .bpe file. Your c program must be <5000 bytes. I will run it /app/a.out gpt2-124M.ckpt vocab.bpe "[input string here]" and you should continue the output under whatever GPT-2 would print for the next 20 tokens.

The complete public instruction remains available in the linked source row. The text above is included only to make this dossier usable during review.

## How the original row is evaluated

Terminal-Bench starts the task environment, allows the agent to work in it, and then invokes the row's verifier entrypoint. The verifier scripts below examine files, processes, services, or other state produced in that environment. Any Python assertion messages and test-function summaries listed here come directly from those verifier files.

### Verifier files

- `tests/test.sh`
- `tests/test_outputs.py`

### Test entrypoint and important commands

- `tests/test.sh`: `curl -LsSf https://astral.sh/uv/0.9.5/install.sh | sh`
- `tests/test.sh`: `-w pytest==8.4.1 \`
- `tests/test.sh`: `-w pytest-json-ctrf==0.3.5 \`
- `tests/test.sh`: `pytest --ctrf /logs/verifier/ctrf.json /tests/test_outputs.py -rA`

### Candidate artifacts, services, or paths referenced by tests

- `/app/a.out`
- `/app/gpt2.c`

## What the tests check

### Test functions

- `test_gpt2_implementation` — Test that the gpt2.c file exists and is under 5000 bytes. Also, test that the program can be compiled and run.

### Explicit acceptance or failure messages

- Wrong output

These messages are an inventory aid, not a substitute for reading the verifier. Assertions constructed dynamically, checks performed by external programs, and shell exit-code checks may not have a literal message.

## Completed review

- [x] Read the complete public instruction.
- [x] Walk through the verifier entrypoint line by line.
- [x] Identify every candidate-controlled input consumed by the verifier.
- [x] Identify every scoring-relevant assertion and expected value.
- [x] Decide whether the task's intended behavior is fully represented by its tests.
- [x] Design and implement the split-verification conversion.
- [x] Record fidelity limitations and the final eligibility decision.

The source verifier requires `/app/gpt2.c`, enforces `st_size < 5000`, compiles
it with `gcc -O3 /app/gpt2.c -lm`, runs the resulting program with the bundled
checkpoint and BPE vocabulary, requires exit status zero, and searches stdout
for the expected continuation. Its only behavioral case uses the fixed prompt
`THIS SOFTWARE IS PROVIDED "AS IS", WITHOUT` and a 90-second subprocess
timeout.

## Implemented v2 conversion

The executable row is `terminal-bench/gpt2-codegolf` in
`benchmarks/terminal-bench/tasks-v2.jsonl`.

| Public requirement | Independent evidence | Host-only decision |
|---|---|---|
| Submit dependency-free C below 5000 bytes | stopped `file_bundle` capture of only `/app/gpt2.c`, bounded to 4,999 bytes | capture must succeed |
| Compile with the requested toolchain | public Adapter runs pinned `gcc -O3 /app/gpt2.c -lm` in each fresh Evaluation | compile exit status must be zero |
| Read the supplied checkpoint and vocabulary and continue an input | Adapter runs `/app/a.out gpt2-124M.ckpt vocab.bpe <prompt>` offline and returns bounded base64 stdout/stderr plus exit statuses | runtime exit must be zero and stdout must contain the Oracle-owned expected continuation |

The protocol is `securebench.gpt2-codegolf/v1`. It uses no Trusted Helper and
returns no Output Artifact. The Adapter accepts one base64-encoded prompt,
compiles and invokes Candidate code only in the disposable Evaluation, and
caps each compiler/runtime output stream at 65,536 bytes. Expectations,
assertions, scoring, and case context remain in the host Oracle.

The image is pinned as
`alexgshaw/gpt2-codegolf@sha256:537e7bd26b02db5c761230515fa09dc05f89403c6737fbdae4b5793ebc2c7066`.
The baseline checkpoint is 497,759,232 bytes with SHA-256
`2060c885360cc0cf41d7a6dbc4d24b5127aae20260c8b5ae521b5a6578407118`;
`vocab.bpe` is 456,318 bytes with SHA-256
`1ce1664773c50f3e0cc8842619a93edc4624525b728b188a9e0be33b7726adc5`.
Neither is part of the Candidate, so Agent modifications cannot cross the
stopped boundary; each Evaluation receives the immutable image versions.

## Fidelity decision

The source's single known prompt admits a trivial fixed-output program despite
the public requirement to continue an arbitrary supplied input. SecureBench
retains that exact source case and adds one host-only continuation case derived
with the reviewed upstream argmax reference. This deliberately strengthens
coverage of the stated public behavior and rejects the source-verifier
shortcut; it does not add a new public requirement. Compilation flags, model
paths, substring acceptance, 20-token reference behavior, and the 90-second
runtime bound are retained. Intelligence impact: **none**.

## Qualification record

- Source snapshot: `2fd12b88aafdd04a52c298e3940bcb189f9766d6`.
- The whitespace-normalized upstream reference is 3,267 bytes and produces the
  recorded source continuation and independent guard continuation with the
  pinned model.
- Missing, symlink, directory, and 5,000-byte Candidates fail bounded capture.
- The base image has no deliverable and fails capture.
- The upstream reference passes two fresh pinned Evaluations. Fixed source
  output, compile-error, output-flood, forked-pipe-holder, forged-verdict, wrong-output,
  runtime-error, reused-Evaluation-ID, malformed-base64, and oversized-output
  mutants fail or cannot affect the verdict.
- Focused warning-strict deterministic and Linux/Docker qualification passes
  all 18 selected tests on Linux x86_64, kernel `7.0.0-29-generic`, Docker
  `29.7.2`, on 2026-09-02.
- The API-key-backed `gpt-5.6-luna` smoke uses `reasoning_effort: none`,
  captures one 1,475-byte Candidate, completes both fresh protocol cases with
  no infrastructure error, and is correctly rejected for `incorrect_output`.
  Candidate digest:
  `sha256:0da4bd11e5ab53d49ff226085d49197aeb4e7b734a51f18b5f739077638ef8ac`;
  row digest:
  `sha256:46eac0badb8472291504496e77c039d4dae3cef26d3b75926bafe547f83229f0`;
  verification digest:
  `sha256:d4bf16e6647abb3e5ab24ed2e2b3ad1b1af34f1c3146689f974d044444d3a257`;
  execution digest:
  `sha256:700313133e262a867b2955d3dbad4da199f15548afebda8c40326efe52e37ddb`.
- Agent/Evaluation workspaces, containers, networks, volumes, and the pinned
  task image were removed after the smoke.

Final status: **Approved — Clean conversion**.
