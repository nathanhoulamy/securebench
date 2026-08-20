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

## Questions for our later review

- [ ] Read the complete public instruction.
- [ ] Walk through the verifier entrypoint line by line.
- [ ] Identify every candidate-controlled input consumed by the verifier.
- [ ] Identify every scoring-relevant assertion and expected value.
- [ ] Decide whether the task's intended behavior is fully represented by its tests.
- [ ] Design the split-verification conversion.
- [ ] Record fidelity limitations and the final eligibility decision.

## Future conversion notes

Use black-box challenge/response. The public checkpoint and vocabulary remain available in the Agent VM and are supplied as immutable public runtime data in the Evaluation VM; candidate modifications to those files must either be rejected at extraction or included as explicitly bounded candidate overlays so scoring-relevant state is not silently lost. Extract bounded `gpt2.c`, enforce the original `<5000` byte rule, compile and run it only in the Evaluation VM with the original fixed prompt and model paths, and capture bounded stdout, stderr, exit status, and timeout. The host-side Oracle independently checks the original expected substring. Hidden tests, expected output, and scoring remain host-side. Verdict: clean conversion; confirmed in the final clean-conversion audit.
