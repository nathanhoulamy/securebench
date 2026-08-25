# `adaptive-rejection-sampler`

> Review status: **Not reviewed with the SecureBench team**. This file documents the original row only; it does not propose a conversion.

## Source facts

| Field | Value |
|---|---|
| Benchmark | Terminal-Bench 2.0 |
| Source row | [`adaptive-rejection-sampler`](https://github.com/harbor-framework/terminal-bench-2/tree/2fd12b88aafdd04a52c298e3940bcb189f9766d6/adaptive-rejection-sampler) |
| Source snapshot | `2fd12b88aafdd04a52c298e3940bcb189f9766d6` |
| Difficulty | medium |
| Category | scientific-computing |
| Tags | applied-statistics, adaptive-rejection-sampling, Bayesian-inference, simulation |
| Agent timeout | 900.0 seconds |
| Verifier timeout | 900.0 seconds |
| Candidate image | `alexgshaw/adaptive-rejection-sampler:20251031` |
| Internet allowed | `True` |

## Goal in simple terms

Evaluates the ability to implement an adaptive rejection sampler in R with proper statistical algorithms, modular design, input validation, log-concavity checking, and formal testing.

### Public instruction, condensed

Your task is to implement an adaptive-rejection sampler as described in Gilks et al. (1992). 1. Your solution should allow the user to provide reasonable inputs, including the number of points to sample, and should check the inputs for validity. The primary input should be a function or expression that calculates the (possibly unnormalized) density of the distribution of interest in a vectorized fashion (e.g., many of the "d" functions in R, such as "dnorm" are legitimate inputs). Your code should include checks that catch cases of non-log-concave densities during the sampling process. 2. Formal testing is required (see 1.), with a set of tests where results are compared to some known truth. You should have tests for the overall function, and for any modules that do anything complicated. Given the output is stochastic, how to do this will require some thought. The output of your testing function should be clear and interpretable. I.e., when I run your test function, it should print informative messages of what it is doing and whether the test was passed or failed. 3. Your solution should involve modular code, with functions or OOP methods that implement discrete tasks. You should have an overall design and style that is consistent across the components, in terms of functions vs. OOP methods, naming of objects, etc. Requirements: - Install R if not already available, then write your code in R - Save your main implementation in a file named "/app/ars.R" - Include a primary function named "ars" that implements the adaptive rejection sampler - Include a test function named "test" that performs formal testing with known distributions - The "ars" function must validate inputs (e.g., reject negative sample counts, invalid domains) - The "ars" function must include checks for…

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

- No absolute candidate paths were extractable automatically.

## What the tests check

### Test functions

- `test_ars_function_exists` — Test that an 'ars' function exists in ars.R as required by the task.
- `test_can_generate_standard_distribution_samples` — Test implementation can generate samples from standard distributions.
- `test_has_test_function` — Test that a 'test' function exists as required by the task.
- `test_formal_testing_with_known_truth` — Test that formal testing outputs correct format as specified.
- `test_sample_files_generated` — Test that required sample files are generated.
- `test_implementation_is_modular` — Test that the implementation follows modular design principles.
- `test_implementation_handles_errors` — Test that the implementation includes error handling.
- `test_input_validation_functionality` — Test that implementation validates inputs.
- `test_log_concavity_functionality` — Test that implementation checks log-concavity.

### Explicit acceptance or failure messages

- No ars.R file found. Task requires implementation in a file named 'ars.R'
- No 'ars' function found in ars.R. Task requires a main function named 'ars' that implements the adaptive rejection sampler.
- No 'test' function found. Task requires a function named 'test' that carries out formal testing of the implementation.
- At least one sample file must be generated. Task requires generating 'normal_samples.txt' or 'exponential_samples.txt' containing test samples
- Implementation should be modular with at least 3 functions (e.g., ars, test, and auxiliary functions)
- Implementation should include proper error handling (e.g., stop(), stopifnot(), tryCatch)
- Test function must output results in format 'TEST_NAME: PASS' or 'TEST_NAME: FAIL'
- Test output should include mean statistics
- Normal samples file should contain at least 100 samples
- Exponential samples file should contain at least 100 samples
- Exponential samples must be non-negative
- Implementation must validate inputs (negative samples, invalid domains)
- Implementation should check for log-concavity

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

Use black-box challenge/response with a reusable, assertion-free R scenario adapter. Keep density specifications, parameters, domains, sample counts, seeds, invalid-input cases, and non-log-concave cases in the host Oracle; return only bounded samples, typed errors, process metadata, and bounded artifact bytes. Drop candidate-reported test truth, static modularity/error-token heuristics, and provenance claims for pre-generated sample files; replace them with host-computed statistical checks and document the resulting semantic change.
