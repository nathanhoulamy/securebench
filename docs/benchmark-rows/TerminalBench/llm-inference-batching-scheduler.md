# `llm-inference-batching-scheduler`

> Review status: **Reviewed with the SecureBench team**.

## Source facts

| Field | Value |
|---|---|
| Benchmark | Terminal-Bench 2.0 |
| Source row | [`llm-inference-batching-scheduler`](https://github.com/harbor-framework/terminal-bench-2/tree/2fd12b88aafdd04a52c298e3940bcb189f9766d6/llm-inference-batching-scheduler) |
| Source snapshot | `2fd12b88aafdd04a52c298e3940bcb189f9766d6` |
| Difficulty | hard |
| Category | machine-learning |
| Tags | batching, inference, performance-optimization, scheduling |
| Agent timeout | 1800.0 seconds |
| Verifier timeout | 1800.0 seconds |
| Candidate image | `alexgshaw/llm-inference-batching-scheduler:20251031` |
| Internet allowed | `True` |

## Goal in simple terms

Implement a shape-aware batching scheduler for static-graph LLM inference that optimally packs requests into batches while meeting strict performance thresholds on cost, latency, and padding.

### Public instruction, condensed

In this task you will implement an **LLM inference batching scheduler (shape‑aware)** for a static graph LLM inference system. **Background ** When running large language models on hardware accelerators (such as TPUs, RDUs, or bespoke inference chips) the compiled execution graph has to operate on fixed‑sized tensors. Requests arrive with arbitrary prompt lengths and generation lengths, but at runtime everything must be rounded up to a multiple of a common granularity. A naïve strategy of batching each request independently wastes compute, increases the number of cold compilations and leads to poor end‑to‑end latency. **Goal** Your goal is to read a set of incoming requests from ``/app/task_file/input_data/requests_bucket_1.jsonl`` ``/app/task_file/input_data/requests_bucket_2.jsonl`` and produce a plan in ``/app/task_file/output_data/plan_b1.jsonl`` ``/app/task_file/output_data/plan_b2.jsonl`` that assigns every request to a batch along with a concrete tensor shape (defined by ``shape.seq_align``, ``shape.heads_align``, ``shape.hidden_align``). Each entry in ``/app/task_file/input_data/requests_bucket_1.jsonl`` and ``/app/task_file/input_data/requests_bucket_2.jsonl`` is a JSON object containing a unique ``request_id``, a ``prompt_len`` and ``gen_len``: * ``request_id``: A unique string identifier for each inference request (e.g., "r-000010") * ``prompt_len``: The length of the input prompt in tokens (integer). * ``gen_len``: The number of tokens to generate for this request (integer). You must pack these into batches so that: * All input requests are included exactly once (no missing/duplicate request_ids) * Each batch uses shape (seq_align, heads_align=32, hidden_align=4096) where seq_align >= ceil(prompt_len/64)*64. I.e., seq_align is a multiple of 64. * Max 8…

The complete public instruction remains available in the linked source row. The text above is included only to make this dossier usable during review.

## How the original row is evaluated

Terminal-Bench starts the task environment, allows the agent to work in it, and then invokes the row's verifier entrypoint. The verifier scripts below examine files, processes, services, or other state produced in that environment. Any Python assertion messages and test-function summaries listed here come directly from those verifier files.

### Verifier files

- `tests/__init__.py`
- `tests/cost_model_for_tests.py`
- `tests/test.sh`
- `tests/test_outputs.py`

### Test entrypoint and important commands

- `tests/test.sh`: `curl -LsSf https://astral.sh/uv/0.9.5/install.sh | sh`
- `tests/test.sh`: `-w pytest==8.4.1 \`
- `tests/test.sh`: `-w pytest-json-ctrf==0.3.5 \`
- `tests/test.sh`: `pytest --ctrf /logs/verifier/ctrf.json /tests/test_outputs.py -rA`

### Candidate artifacts, services, or paths referenced by tests

- `/app/task_file/input_data`
- `/app/task_file/input_data/requests_bucket_`
- `/app/task_file/input_data/requests_bucket_1.jsonl`
- `/app/task_file/input_data/requests_bucket_2.jsonl`
- `/app/task_file/output_data`
- `/app/task_file/output_data/plan_b`
- `/app/task_file/output_data/plan_b1.jsonl`
- `/app/task_file/output_data/plan_b2.jsonl`

## What the tests check

### Test functions

- `test_output_files_exist` — Test that both required output files exist. This test verifies that the agent has generated the required output files before running any validation logic. This is a prerequisite for all other tests.
- `test_input_data_integrity` — Test that input data files have not been tampered with. This test verifies the SHA256 checksums of the input data files to prevent cheating by modifying the input data. The expected hashes were computed from the original, unmodified input…
- `test_generate_and_schema` — Test that the generated plans have correct schema and coverage. This is the primary functional test that validates: 1. **Coverage**: All input requests appear in output plans exactly once 2. **Schema Compliance**: Output follows expected…
- `test_solution_shape_feasibility_and_batch_consistency` — Test that the solution produces feasible shapes and consistent batches. This test validates the core correctness requirements for the batching scheduler: 1. Shape Feasibility: - All shapes must be aligned to the specified granularity (64)…
- `test_solution_coverage_no_duplicates` — Test that the solution covers all requests exactly once with no duplicates. This test ensures the scheduling completeness requirement: - Every input request must appear in the output plan exactly once - No request should be duplicated in…
- `test_performance_thresholds` — Test solution meets performance thresholds described in task.yaml. **Performance Thresholds:** - Bucket 1: cost ≤ 3.0e11, pad_ratio ≤ 0.055, p95_latency ≤ 2.1e6 ms, sequential_timecost ≤ 2.7e8 ms - Bucket 2: cost ≤ 4.8e10, pad_ratio ≤…

### Explicit acceptance or failure messages

- Missing required output file: /app/task_file/output_data/plan_b1.jsonl
- Missing required output file: /app/task_file/output_data/plan_b2.jsonl

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

Use passive artifact verification. Extract bounded JSONL plans, retain request inputs and the complete cost model in the host-side Oracle, and independently validate coverage, schema, shape feasibility, batch consistency, shape caps, and all cost/padding/latency thresholds. No candidate code executes during evaluation, and no candidate-reported metric is trusted. Verdict: clean conversion; auto-approved under the first-pass policy.
