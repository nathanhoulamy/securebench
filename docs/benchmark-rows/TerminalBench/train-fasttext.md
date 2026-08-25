# `train-fasttext`

> Review status: **Reviewed with the SecureBench team**.

## Source facts

| Field | Value |
|---|---|
| Benchmark | Terminal-Bench 2.0 |
| Source row | [`train-fasttext`](https://github.com/harbor-framework/terminal-bench-2/tree/2fd12b88aafdd04a52c298e3940bcb189f9766d6/train-fasttext) |
| Source snapshot | `2fd12b88aafdd04a52c298e3940bcb189f9766d6` |
| Difficulty | hard |
| Category | model-training |
| Tags | data-processing, data-science |
| Agent timeout | 3600.0 seconds |
| Verifier timeout | 3600.0 seconds |
| Candidate image | `alexgshaw/train-fasttext:20251031` |
| Internet allowed | `True` |

## Goal in simple terms

Train a FastText text classification model on Yelp review data that achieves >0.62 accuracy while staying under 150MB in size.

### Public instruction, condensed

Please train a fasttext model on the yelp data in the data/ folder. The final model size needs to be less than 150MB but get at least 0.62 accuracy on a private test set that comes from the same yelp review distribution. The model should be saved as /app/model.bin

The complete public instruction remains available in the linked source row. The text above is included only to make this dossier usable during review.

## How the original row is evaluated

Terminal-Bench starts the task environment, allows the agent to work in it, and then invokes the row's verifier entrypoint. The verifier scripts below examine files, processes, services, or other state produced in that environment. Any Python assertion messages and test-function summaries listed here come directly from those verifier files.

### Verifier files

- `tests/private_test.tar.gz`
- `tests/test.sh`
- `tests/test_outputs.py`

### Test entrypoint and important commands

- `tests/test.sh`: `curl -LsSf https://astral.sh/uv/0.9.5/install.sh | sh`
- `tests/test.sh`: `-w pytest==8.4.1 \`
- `tests/test.sh`: `-w pytest-json-ctrf==0.3.5 \`
- `tests/test.sh`: `pytest --ctrf /logs/verifier/ctrf.json /tests/test_outputs.py -rA`

### Candidate artifacts, services, or paths referenced by tests

- `/app/model.bin`
- `/tests/private_test.txt`

## What the tests check

### Test functions

- `test_accuracy` — Test accuracy of the fasttext model on the test set.
- `test_model_size` — Test the size of the model.

### Explicit acceptance or failure messages

- No literal Python assertion messages were extractable; inspect the verifier commands and source files listed below.

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

Use black-box challenge/response plus passive artifact verification with a major redesign. Extract bounded `model.bin` and check the original `<150 MiB` predicate host-side without loading it. Load the same artifact with an immutable FastText runtime in multiple fresh or pre-secret-cloned Evaluation VMs; each receives only a disjoint bounded shard of unlabelled private reviews. The host-side Oracle aggregates per-review predictions, applies the verifier's strict `accuracy > 0.62` rule against host-held labels, and never sends the labels, threshold, tests, reference model, or private corpus as a whole into either VM. Streaming all 40,000 reviews through one persistent Evaluation VM is prohibited; sharding and repeated model loading/cloning are feasible but operationally substantial and do not preserve arbitrary stateful whole-corpus behavior. Verdict: major redesign; manually approved in the final clean-conversion audit.
