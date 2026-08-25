# Real Benchmark Tasks Through a Split-Verification Lens

This document explains how real benchmark rows are graded today and how they could be represented under SecureBench's proposed **full split-verification** standard.

It is written as a design guide, not merely a survey. Each example answers four practical questions:

1. What does the agent actually have to do?
2. What does the original checker inspect or execute?
3. What may cross into or out of the agent VM under full split verification?
4. Can we preserve the original meaning of the task, or must we change it?

The examples were inspected from the official source repositories, not invented examples. Long prompts and test patches are paraphrased so this remains readable. The exact source row is linked in every section.

## The idea in 30 seconds

Most coding benchmarks currently work like this:

```text
agent edits candidate code
        ↓
hidden tests are copied into a verifier sandbox
        ↓
verifier sandbox runs hidden tests against candidate code
        ↓
test process reports pass or fail
```

The problem is that the verifier sandbox executes both attacker-controlled candidate code and trusted hidden test code. Sandboxing reduces the damage, but it does not remove this trust collision.

The target SecureBench design is:

```text
                         secret tests and answers
                                  │
                                  ▼
candidate VM ◀── challenge ── trusted host oracle
     │                            ▲
     └──── bounded observation ───┘
```

The **candidate VM** contains the submitted program and the runtime it needs. The **trusted host oracle** contains the hidden cases, expected answers, scoring rules, and final pass/fail decision. The oracle never imports or executes candidate code.

A challenge may enter the VM, because programs need inputs. What must not enter is the hidden test implementation, its expected answer, the rest of the test corpus, or a credential that lets the VM query the oracle.

Examples of acceptable boundary messages are:

- “Run the submitted CLI with integer `9281`.”
- “Send this HTTP request to the submitted service.”
- “Evaluate this program using the submitted interpreter.”
- “Apply these user actions to the submitted state machine.”

Examples of observations returned to the host are:

- stdout, stderr, exit status, and elapsed time;
- an HTTP status, headers, and a bounded response body;
- a bounded output artifact;
- a database snapshot produced through a fixed observation API;
- a typed event trace.

The candidate VM never says “I passed.” It only produces evidence. The host decides whether that evidence is correct.

## A proposed row shape

The examples below use this conceptual schema. It is illustrative and is **not** a claim that SecureBench already implements these fields.

```yaml
id: benchmark/task-name
candidate:
  image: digest-pinned-vm-image
  submission: patch | workspace | artifact
  entrypoint: public, fixed command or protocol
verification:
  adapter: cli | http | artifact | state_api | scenario_runner
  challenges: hidden host-owned generator or corpus
  observations:
    schema: typed and bounded
    limits: explicit size, time, and count limits
  oracle: host-owned comparison or invariant checks
  forbidden_in_candidate:
    - hidden test source
    - expected outputs
    - scoring code
equivalence:
  preserved: true | partial | false
  caveat: explanation of any semantic change
```

Three components should not be confused:

- The **candidate program** is what the agent changed. It is untrusted.
- The **public adapter** is a small, versioned interface for starting or querying the candidate. The agent knows it exists. It must not contain hidden answers or task-specific assertions.
- The **host oracle** owns secret cases, computes expected results, and scores observations. It is trusted and never loads candidate code.

The public adapter is **not trusted merely because SecureBench supplied it**. Candidate code runs in the same guest and may try to patch, impersonate, exploit, or bypass it. Whenever possible, process launch, network capture, exit status, timing, and output collection should be controlled from outside the guest by the VM supervisor. Any value computed inside the guest is still an untrusted claim that must be checked through unpredictable challenges or corroborated externally.

## Coverage map

The selected rows deliberately cover different kinds of evaluation.

| Benchmark row | What it represents | Split difficulty | Meaning preserved? |
|---|---|---:|---|
| Terminal-Bench: `constraints-scheduling` | Static output artifact | Low | Yes |
| Terminal-Bench: `circuit-fibsqrt` | CLI/program input-output behavior | Low | Yes |
| Terminal-Bench: `configure-git-webserver` | Long-lived service and filesystem state | Medium | Yes |
| Terminal-Bench: `adaptive-rejection-sampler` | Stochastic library behavior and callbacks | Medium-high | Mostly |
| Terminal-Bench: `custom-memory-heap-crash` | Compilation, crashes, and memory instrumentation | High | Only with a declared instrumentation primitive |
| Terminal-Bench: `break-filter-js-from-html` | Malicious artifact and browser behavior | High-risk | Yes, but the observer also needs isolation |
| DeepSWE: `anko-default-function-arguments` | Interpreter feature through a public language interface | Low-medium | Yes |
| DeepSWE: `httpx-streaming-json-iteration` | Library API, streams, async, and errors | Medium-high | Mostly |
| DeepSWE: `fastapi-implicit-head-options` | Web-framework feature and regressions | High | Mostly |
| DeepSWE: `kea-atomic-signal-selectors` | React state, render counts, graphs, and diagnostics | Very high | Partial without a generic scenario interface |
| DeepSWE: `testem-bail-on-test-failure` | Internal events, mocks, sockets, and process control | Very high | Some assertions are not externally observable |
| SWE-bench Pro: Ansible FQCN validation | Traditional repository patch plus regression suite | High | Feature behavior yes; full suite equivalence is difficult |
| τ-bench: retail exchange | Tool-using agent and database end state | Low | Yes; it already resembles split verification |

---

# Part I — Terminal-Bench examples

Terminal-Bench 2.0 contains 89 tasks spanning software engineering, system administration, security, data science, and other terminal work. A typical task directory has an instruction, an environment, a solution, and a `tests/` directory. The original verifier normally places or mounts the tests where they can execute against the candidate environment.

The six rows below are a better representation of the benchmark than six variations of ordinary unit tests.

## 1. `constraints-scheduling`: grade a file without executing it

**Actual row:** [`constraints-scheduling`](https://github.com/harbor-framework/terminal-bench-2/tree/2fd12b88aafdd04a52c298e3940bcb189f9766d6/constraints-scheduling)

### What the agent is asked to do

The workspace contains several calendar files. The agent must create `/app/meeting_scheduled.ics` for a one-hour meeting while respecting attendee availability, working hours, conflicts, and tie-breaking preferences. It must not alter the input calendars.

### What the original checker checks

In simple terms, it:

1. verifies that the input files did not change;
2. reads and parses the output calendar;
3. checks that it contains one correctly named event with the required attendees;
4. checks its duration, weekday, date range, business hours, and conflicts;
5. checks preferences such as avoiding Monday or preferring a morning slot.

### Split-verification conversion

This is the cleanest class of task. Nothing from the candidate needs to execute during verification.

```text
Agent VM                                Trusted host
---------                               ------------
creates meeting_scheduled.ics
       │
       └── bounded file bytes ────────▶ strict ICS parser
                                        + hidden calendars
                                        + constraint oracle
                                        + final score
```

The artifact gateway should enforce a maximum file size and treat the file as hostile data. The host should use a strict, memory-safe parser or a small purpose-built parser. It should not invoke a calendar application, shell command, plugin, or macro embedded in the artifact.

Input immutability can be checked from host-owned digests of the original files or, better, by making benchmark inputs read-only and accepting only the named output artifact.

```yaml
id: terminal-bench/constraints-scheduling
verification:
  adapter: artifact
  collect:
    path: /app/meeting_scheduled.ics
    max_bytes: 65536
  oracle:
    parser: trusted_ics_parser_v1
    checks: [schema, attendees, duration, conflicts, tie_breakers]
  forbidden_in_candidate: [hidden_constraints, expected_slot, checker_code]
equivalence:
  preserved: true
```

**Design lesson:** Prefer declarative artifacts when the intended result is a document, configuration, plan, or data file. This class needs no candidate execution at grading time.

## 2. `circuit-fibsqrt`: challenge a program through a fixed CLI

**Actual row:** [`circuit-fibsqrt`](https://github.com/harbor-framework/terminal-bench-2/tree/2fd12b88aafdd04a52c298e3940bcb189f9766d6/circuit-fibsqrt)

### What the agent is asked to do

The agent must write `/app/gates.txt`, a circuit description consumed by a provided simulator. For an input integer `N`, the circuit must output:

```text
Fibonacci(integer_square_root(N)) modulo 2^32
```

The circuit must use fewer than 32,000 lines.

### What the original checker checks

It verifies that `gates.txt` exists and is below the line limit, compiles the supplied C simulator, runs roughly thirty fixed integer cases—including values near perfect squares—and compares every integer result with a Python implementation of the formula.

### Split-verification conversion

Expose one fixed public operation in the candidate VM:

```text
evaluate_circuit(N) -> {stdout, stderr, exit_code, elapsed_ms}
```

The host chooses canonical and secret randomized `N` values, sends one value at a time, computes the expected Fibonacci result itself, and compares it with the returned integer. The host separately collects `gates.txt` through the bounded artifact gateway to count lines.

The public adapter may know how to invoke the simulator. It must not contain the list of cases or the Fibonacci oracle.

```yaml
id: terminal-bench/circuit-fibsqrt
verification:
  adapter: cli
  public_entrypoint: ["/opt/securebench/bin/run-circuit"]
  challenges:
    generator: host_fibsqrt_cases_v1
  observations:
    schema: {stdout: bounded_text, stderr: bounded_text, exit_code: integer}
    limits: {calls: 64, bytes_per_stream: 4096, seconds_per_call: 2}
  oracle: host_fibonacci_isqrt_v1
equivalence:
  preserved: true
```

**Design lesson:** A hidden test does not need to be a hidden program. It can be secret input data plus a host-side mathematical oracle.

## 3. `configure-git-webserver`: test a running service from outside

**Actual row:** [`configure-git-webserver`](https://github.com/harbor-framework/terminal-bench-2/tree/2fd12b88aafdd04a52c298e3940bcb189f9766d6/configure-git-webserver)

### What the agent is asked to do

The agent configures a Git repository reachable over SSH. When a client pushes a web file, the server must deploy it so the file is available from an HTTP server on port 8080.

### What the original checker checks

The verifier, from inside the task environment, effectively does this:

1. connects to the local Git server over SSH;
2. clones the repository;
3. creates `hello.html` containing `hello world`;
4. commits and pushes it;
5. fetches the corresponding URL from port 8080;
6. requires HTTP 200 and the exact body.

### Split-verification conversion

The host can behave like a real external client. It connects to the VM over a dedicated private evaluation network, pushes an unpredictable filename and content, and then requests that filename over HTTP.

```text
Trusted host                  Candidate VM
------------                  ------------
create random file
git push over SSH ──────────▶ Git service + hook
HTTP GET random path ───────▶ Web service
HTTP status/body ◀───────────┘
compare on host
```

The random nonce matters. A candidate that merely serves a hard-coded `hello world` page should not pass.

The evaluation network needs strict policy: the host initiates connections; the candidate cannot initiate arbitrary connections to the host; only the declared ports and protocols are reachable; credentials are per-run and reveal no evaluator secrets.

```yaml
id: terminal-bench/configure-git-webserver
verification:
  adapter: network_service
  endpoints:
    - {name: git, protocol: ssh, guest_port: 22}
    - {name: web, protocol: http, guest_port: 8080}
  challenges:
    generator: random_git_commit_v1
  observations:
    schema: {push_result: status, http_status: integer, body: bounded_bytes}
  oracle: exact_nonce_file_match
equivalence:
  preserved: true
```

**Design lesson:** State such as a Git repository, daemon configuration, or deployed file does not need to be copied to a verifier. Query the state through the system's real public interface.

## 4. `adaptive-rejection-sampler`: test stochastic library behavior

**Actual row:** [`adaptive-rejection-sampler`](https://github.com/harbor-framework/terminal-bench-2/tree/2fd12b88aafdd04a52c298e3940bcb189f9766d6/adaptive-rejection-sampler)

### What the agent is asked to do

The agent implements an adaptive rejection sampler in `/app/ars.R`. It must accept a density function, validate inputs, reject non-log-concave cases, provide multiple helper functions, include its own tests, and write sample outputs.

### What the original checker checks

The checker mixes several kinds of assertion:

- file and function existence;
- sampling normal and exponential distributions;
- rough sample mean, standard deviation, and non-negativity checks;
- invalid-input and non-log-concavity errors;
- the output of a submitted `test()` function;
- static heuristics such as having several functions and error handlers.

### Split-verification conversion

The difficult part is that R functions are not simple values that can safely be sent through JSON. The benchmark therefore needs a **public, generic R probe** with a small expression language, for example:

```json
{
  "operation": "sample",
  "density_family": "normal",
  "parameters": {"mean": 1.7, "sd": 0.8},
  "n": 2000,
  "seed": 49281
}
```

The probe calls the submitted `ars` function and returns bounded samples or a typed error. The host secretly chooses families, parameters, seeds, and invalid cases, then performs distributional checks outside the VM.

This preserves the important behavior, but not every original assertion:

- Requiring “at least three helper functions” is an implementation-style check. It should be removed or made an explicit public artifact rule.
- Trusting the candidate's own `test()` output proves almost nothing; a malicious submission can print `PASS`. The host should test behavior directly.
- Statistical thresholds must include a documented false-positive/false-negative budget and deterministic seeds.

```yaml
id: terminal-bench/adaptive-rejection-sampler
verification:
  adapter: scenario_runner
  public_protocol: ars-probe-v1
  challenges:
    generator: host_distribution_cases_v1
  observations:
    schema: {samples: bounded_float_array, error: optional_typed_error}
  oracle: host_statistical_oracle_v1
equivalence:
  preserved: partial
  caveat: structural heuristics and self-reported tests are removed
```

**Design lesson:** Standardize small public probes for libraries that do not naturally expose a process or network boundary. The probe must be generic enough to reuse across tasks; otherwise it is simply a hidden test rewritten under another name.

## 5. `custom-memory-heap-crash`: where “no tests in the VM” becomes strict

**Actual row:** [`custom-memory-heap-crash`](https://github.com/harbor-framework/terminal-bench-2/tree/2fd12b88aafdd04a52c298e3940bcb189f9766d6/custom-memory-heap-crash)

### What the agent is asked to do

The agent may edit only `user.cpp`. Both debug and optimized release builds must run without crashing against a custom C++ library, and the release build must have no definite memory leaks under Valgrind.

### What the original checker checks

It hashes protected source files to make sure they were not changed, compiles debug and release versions, runs both, and runs the release binary under Valgrind with definite leaks treated as errors.

### Why this is a boundary case

Compilation and ordinary execution fit a public build/run adapter. Valgrind is different: it is verifier-selected instrumentation that must execute alongside the candidate process. Under the literal rule “no verifier code or tooling in any candidate VM,” the original memory-leak property cannot be observed from outside the VM.

There are three honest options:

1. **Declare instrumentation a separate public-instrumented profile.** Valgrind is preinstalled in the base image, its invocation and output schema are public, and only the secret workload is selected by the host. This preserves the task's meaning while keeping hidden tests out, but it does not satisfy the full split-verification standard merely by making the instrument public: an in-VM report is still untrusted unless independently corroborated outside the guest.
2. **Measure only externally visible failure.** Run secret workloads and check crash/resource behavior. This is safer architecturally but no longer proves absence of definite leaks.
3. **Reject the row from the strict profile.** Keep it in a separate “instrumented verification” profile and report it separately.

SecureBench should not claim options 2 and 3 are semantically equivalent to the original task.

```yaml
id: terminal-bench/custom-memory-heap-crash
verification:
  profile: instrumented-public-runtime
  adapter: cli
  public_operations: [build_debug, build_release, run, run_valgrind]
  challenges: host_owned_workloads
  observations:
    schema: {exit_code: integer, sanitizer_report: typed_bounded_report}
  oracle: host_report_interpreter_v1
equivalence:
  preserved: true
  caveat: requires public in-VM instrumentation; ineligible for the strictest profile
```

**Design lesson:** Write down what “test code” includes. If it includes all instrumentation, coverage, tracing, profilers, and sanitizers, some useful properties are fundamentally unavailable to an external observer.

## 6. `break-filter-js-from-html`: the output artifact itself is hostile

**Actual row:** [`break-filter-js-from-html`](https://github.com/harbor-framework/terminal-bench-2/tree/2fd12b88aafdd04a52c298e3940bcb189f9766d6/break-filter-js-from-html)

### What the agent is asked to do

The agent crafts an HTML file that still triggers JavaScript after a supplied filtering program transforms it.

### What the original checker checks

It copies the candidate HTML, applies the filter, opens the result in headless Chromium through Selenium, and waits for a JavaScript alert.

### Split-verification conversion

SecureBench can extract the HTML as bounded bytes, but both sanitizing and
opening attacker-created HTML process hostile input, and Chromium intentionally
executes candidate-controlled JavaScript. The sanitizer and browser therefore
belong in the Evaluation VM as immutable public runtime components. They must
not run on the Oracle host or in an additional candidate-execution cell.

A compliant topology is:

```text
Agent VM ──▶ bounded HTML candidate ──▶ Evaluation VM
                                          ├── pinned public sanitizer
                                          └── network-denied Chromium
                                                   │
external supervisor ◀── dialog/timeout/crash ──────┘
          │
          └──▶ host Oracle decides the verdict
```

This is passive artifact verification followed by black-box
challenge/response. The disposable Chromium compartment is the Evaluation VM,
not a fourth verification pattern. Its output is hostile: a guest-produced
`{alert_seen: true}` or pass flag is not authoritative. The supervisor must own
browser launch and observation capture, while the Oracle owns the expected
condition and final decision. The Evaluation VM contains no hidden corpus,
assertions, expected answer, or scoring logic and is destroyed after the case.

```yaml
id: terminal-bench/break-filter-js-from-html
verification:
  patterns: [passive_artifact, black_box_challenge_response]
  adapter: artifact_then_browser
  collect: {path: /app/out.html, max_bytes: 1048576}
  evaluation_vm:
    transform: canonical_filter_v1
    image: pinned-browser-observer
    network: none
    secrets: none
    lifetime: one_case
  observations:
    schema: {dialog_event: bounded_event, browser_exit: integer, timeout: boolean}
  oracle: host_browser_event_interpreter_v1
equivalence:
  preserved: true
  caveat: Chromium is containment inside the Evaluation VM, not a trust anchor
```

**Design lesson:** “The host does not execute candidate code” must include indirect execution through parsers, office files, compilers, browsers, model loaders, and deserializers.

---

# Part II — DeepSWE examples

[DeepSWE](https://github.com/datacurve-ai/deep-swe) contains 113 original, long-horizon tasks across Python, Go, TypeScript, JavaScript, and Rust. Its row format has a repository/base commit, an instruction, a reproducible image, and a hidden `test.patch` applied at grading time. It already uses a separate verifier environment, but the patched candidate repository and hidden tests still execute together there. That is exactly the collision SecureBench is trying to remove.

The five examples below are also the five deterministic DeepSWE tasks currently packaged in this SecureBench repository. They cover a useful difficulty gradient.

DeepSWE divides tests into:

- **F2P (fail-to-pass):** new behavior that fails before the agent's patch and should pass afterward;
- **P2P (pass-to-pass):** existing behavior that must continue to work.

Under full split verification, both categories must become host-owned challenges and external observations. Merely converting the F2P tests is insufficient because it discards regression coverage.

## 7. `anko-default-function-arguments`: an interpreter has a natural boundary

**Actual row:** [`anko-default-function-arguments`](https://github.com/datacurve-ai/deep-swe/tree/e016041a6ccf8da29906afc9a3f5a8df940a1f78/tasks/anko-default-function-arguments)

**Repository:** `mattn/anko` at base commit `9d2d84b…`
**Original grading:** 2 F2P nodes and 119 P2P nodes.

### What the agent is asked to do

Add default values to function parameters in the Anko scripting language. Defaults must be visible correctly, evaluated at call time, and evaluated in the intended order.

### What the original checker checks

The hidden Go tests import and exercise the interpreter. The feature tests check loading default arguments and their visibility. The existing Go test suite provides regression coverage.

### Split-verification conversion

An interpreter already has a natural public interface: program text in, output or error out. A fixed public adapter can run an Anko program supplied by the host.

Example secret challenge data—not secret test code—could be:

```json
{
  "program": "counter = 0; func f(x = counter++) { return x }; println(f()); println(f())",
  "limits": {"milliseconds": 500, "stdout_bytes": 4096}
}
```

The host knows the expected output and error behavior. It can generate variations in parameter position, dependencies between defaults, side effects, omitted arguments, explicit arguments, and syntax errors.

The 119 regression tests cannot simply be copied into the VM. They must either be represented as a host-side corpus of Anko programs and expected observations or classified as non-observable internal tests.

```yaml
id: deep-swe/anko-default-function-arguments
verification:
  adapter: language_runner
  public_protocol: anko-program-v1
  challenges: hidden_program_corpus_and_generator
  observations: {stdout: bounded_text, stderr: bounded_text, exit_code: integer}
  oracle: exact_or_normalized_program_outcomes
equivalence:
  preserved: true
```

**Design lesson:** Compilers, interpreters, formatters, linters, and query engines are strong candidates because their public language is already a rich test-input protocol.

## 8. `httpx-streaming-json-iteration`: library calls, streaming, and async

**Actual row:** [`httpx-streaming-json-iteration`](https://github.com/datacurve-ai/deep-swe/tree/e016041a6ccf8da29906afc9a3f5a8df940a1f78/tasks/httpx-streaming-json-iteration)

**Repository:** `encode/httpx` at base commit `b5addb6…`
**Original grading:** 108 F2P nodes and 1,404 P2P nodes.

### What the agent is asked to do

Add synchronous and asynchronous response iterators that incrementally parse JSON, newline-delimited JSON, and JSON text sequences from streamed HTTP bodies.

### What the original checker checks

The hidden Python tests directly import `httpx.Response` and custom stream classes. They vary:

- sync versus async execution, including asyncio and Trio;
- media type and character encoding;
- byte-order marks;
- arbitrary chunk boundaries, including splitting a JSON token between chunks;
- invalid and trailing input;
- whether response streams close correctly;
- repeat iteration behavior.

### Split-verification conversion

A generic public HTTPX scenario runner can accept a declarative scenario:

```json
{
  "mode": "asyncio",
  "method": "aiter_json",
  "content_type": "application/x-ndjson; charset=utf-8",
  "chunks_base64": ["eyJh", "IjoxfQo=", "eyJiIjoyfQo="],
  "repeat": 1
}
```

It returns a typed transcript:

```json
{
  "values": [{"a": 1}, {"b": 2}],
  "error_type": null,
  "stream_closed": true
}
```

The host owns the hidden chunk boundaries and expected transcript. The adapter contains no assertions.

This preserves most of the feature. Exact Python object identity, arbitrary callback behavior, stack frames, or unexposed private state cannot be serialized without making the adapter increasingly invasive. Such assertions should be removed unless the prompt explicitly promises a public diagnostic interface.

```yaml
id: deep-swe/httpx-streaming-json-iteration
verification:
  adapter: scenario_runner
  public_protocol: python-http-stream-v1
  challenges: hidden_stream_scenarios
  observations:
    schema: {values: bounded_json_array, error_type: optional_string, stream_closed: boolean}
  oracle: host_stream_transcript_oracle
equivalence:
  preserved: partial
  caveat: private Python object state is intentionally outside the observable contract
```

**Design lesson:** Chunked data, concurrency mode, and failure injection should be first-class challenge types in the standard.

## 9. `fastapi-implicit-head-options`: a library can be observed as a service

**Actual row:** [`fastapi-implicit-head-options`](https://github.com/datacurve-ai/deep-swe/tree/e016041a6ccf8da29906afc9a3f5a8df940a1f78/tasks/fastapi-implicit-head-options)

**Repository:** `fastapi/fastapi` at base commit `11614be…`
**Original grading:** 43 F2P nodes and 3,134 P2P nodes.

### What the agent is asked to do

Add configurable implicit `HEAD` handling and informative automatic `OPTIONS` responses to FastAPI applications, routers, and included routers.

### What the original checker checks

The hidden tests import the modified FastAPI package and construct many applications with `TestClient`. They cover default behavior, disabling and overriding behavior at several routing levels, `OPTIONS` payloads and allowed-method headers, OpenAPI output, CORS, middleware execution, route copying/resetting, and non-HTTP scopes.

### Split-verification conversion

Turn the modified framework into a temporary service through a public declarative app builder. The host sends a route specification; the adapter constructs the FastAPI app and starts it. The host then makes real HTTP requests.

```json
{
  "app": {"implicit_head": true},
  "routers": [
    {"prefix": "/v1", "routes": [{"path": "/item", "methods": ["GET"], "body": "ok"}]}
  ],
  "diagnostics": ["middleware_hit_count"]
}
```

The host can directly observe HTTP status, headers, body, and OpenAPI JSON. Middleware hit counts could be exposed by a documented diagnostics endpoint, but that value remains self-reported by the guest and is weaker evidence. Private route-object identity and internal copying behavior are not externally visible. Adding a diagnostic makes them easier to query, but does not make the report trustworthy against a deliberately malicious candidate.

The difficult part is regression coverage. Thousands of Python unit tests cannot be carried over unchanged. The conversion effort is not writing 3,134 one-off RPC commands; it is designing a smaller behavioral corpus that preserves the important public guarantees and recording which original assertions were dropped.

```yaml
id: deep-swe/fastapi-implicit-head-options
verification:
  adapter: http_service_from_spec
  public_protocol: asgi-app-spec-v1
  challenges: hidden_route_specs_and_http_requests
  observations: {status: integer, headers: bounded_map, body: bounded_bytes, diagnostics: bounded_map}
  oracle: host_http_and_openapi_oracle
equivalence:
  preserved: partial
  caveat: internal-only regression assertions require replacement or exclusion
```

**Design lesson:** Framework tasks often become service tasks. Public protocol behavior converts well; internal object assertions do not.

## 10. `kea-atomic-signal-selectors`: state graphs and React rendering

**Actual row:** [`kea-atomic-signal-selectors`](https://github.com/datacurve-ai/deep-swe/tree/e016041a6ccf8da29906afc9a3f5a8df940a1f78/tasks/kea-atomic-signal-selectors)

**Repository:** `keajs/kea` at base commit `6c7ebba…`
**Original grading:** 12 F2P nodes and 139 P2P nodes.

### What the agent is asked to do

Add an optional fine-grained “atomic signal” selector engine while preserving Kea's existing lifecycle behavior. The feature includes dependency tracking, graph propagation, circular-dependency detection, collection reactivity, health information, batching, and React integration.

### What the original checker checks

The hidden Jest tests import the library and create logic objects and React components. They inspect selector values, dependency propagation through a graph, rerender counts, emitted events, circular errors, Map/Set/Array updates, health metadata, and identity across unmount/remount cycles.

### Split-verification conversion

This requires a generic JavaScript state-machine scenario protocol. The host describes logic, selectors, actions, component subscriptions, and an action sequence. The public runner returns a trace of observable selector values, render counts, events, errors, and documented health data.

```json
{
  "logic": "public declarative logic description",
  "mount": ["CounterView"],
  "steps": [{"dispatch": "increment"}, {"batch": ["increment", "increment"]}],
  "observe": ["selector_values", "render_counts", "events", "health"]
}
```

This is possible, but it is easy to cheat conceptually: if the runner contains task-specific mock components and assertions, the tests have merely moved into the VM. The runner must be public, generic across many Kea tasks, assertion-free, and versioned independently of the secret cases.

Object identity is also process-local. A public runner could assign local identity tokens, but those tokens are still guest-reported and can be forged. The host cannot independently inspect JavaScript references. Therefore strict SecureBench should score externally visible selector results and rendered behavior, and mark internal identity assertions as unpreserved.

```yaml
id: deep-swe/kea-atomic-signal-selectors
verification:
  adapter: scenario_runner
  public_protocol: js-reactive-graph-v1
  challenges: hidden_logic_and_action_scenarios
  observations: {trace: bounded_typed_event_sequence}
  oracle: host_state_trace_oracle
equivalence:
  preserved: partial
  caveat: process-local identity and internal graph assertions require declared diagnostics
```

**Design lesson:** The more a test depends on in-process objects and mocks, the more the benchmark needs a carefully standardized domain protocol rather than a task-specific wrapper.

## 11. `testem-bail-on-test-failure`: some unit tests have no external equivalent

**Actual row:** [`testem-bail-on-test-failure`](https://github.com/datacurve-ai/deep-swe/tree/e016041a6ccf8da29906afc9a3f5a8df940a1f78/tasks/testem-bail-on-test-failure)

**Repository:** `testem/testem` at base commit `06a1adb…`
**Original grading:** 90 F2P nodes and 489 P2P nodes.

### What the agent is asked to do

Add a `bail_on_test_failure` option that stops a run after a configurable number of failures and behaves consistently across runners, reporters, browser adapters, sockets, output formats, and process exit handling.

### What the original checker checks

The hidden Mocha tests cover public configuration but also use in-process mocks, fake sockets, event emitters, monkey-patching, synthetic runners, and reporter internals. They verify threshold resets, abort idempotence, broadcast events, adapter-specific behavior, and output formatting.

### Split-verification conversion

Some behavior is externally visible: create a small test project, start Testem, generate passing and failing results, then inspect whether execution stops and which exit code/output appears.

Other behavior—such as an exact internal method call, event ordering on a private emitter, or an object passed to a mock—is not externally visible. A generic public event-scenario runner could expose some of it, but doing so changes the product's interface and may encode the hidden tests.

The honest conversion is therefore a classification:

- convert public CLI, process, browser, socket, and output behavior;
- replace internal assertions with observable consequences where possible;
- reject assertions that distinguish implementations with identical public behavior;
- record the resulting semantic delta.

```yaml
id: deep-swe/testem-bail-on-test-failure
verification:
  adapter: process_and_event_scenario
  public_protocol: test-runner-scenario-v1
  challenges: hidden_failure_sequences_and_configs
  observations: {exit_code: integer, stdout: bounded_text, events: bounded_typed_sequence}
  oracle: host_bail_behavior_oracle
equivalence:
  preserved: partial
  caveat: private mock-call assertions are deliberately excluded
```

**Design lesson:** Full split verification forces the benchmark author to define the product's observable contract. That is a feature, but it also means not every existing unit-test assertion survives.

---

# Part III — Two useful comparison benchmarks

## 12. SWE-bench Pro: Ansible collection-name validation

**Actual SecureBench row:** `instance_ansible__ansible-f327e65d…` in [`benchmarks/swe-bench-pro/tasks.jsonl`](../benchmarks/swe-bench-pro/tasks.jsonl)
**Source dataset:** Scale AI SWE-bench Pro, public split, source index 4.

### What the agent is asked to do

Ansible incorrectly accepts fully qualified collection names containing Python keywords, such as a namespace named `def` or a collection named `return`. The agent must centralize identifier validation and reject keywords while preserving valid collection names.

### What this real row checks

The row has four named fail-to-pass cases:

- `assert.this` → false;
- `ns4.return` → false;
- `import.that` → false;
- `def.coll3` → false.

It also requires 171 pass-to-pass tests from collection loading and the Galaxy CLI. The current SecureBench command restores the selected test files, applies evaluator-only support scripts, invokes `ansible-test`, parses the logs, and requires every named F2P and P2P node to pass.

### Split-verification conversion

The feature itself is easy to externalize. A public Ansible validation operation can accept candidate names and return a boolean or CLI result. The host supplies hidden valid/invalid identifiers, including Unicode, keywords, punctuation, segment counts, and Python-version edge cases.

The 171 regression tests are the difficult part. Many touch loader objects and CLI internals. They need to be sorted into:

1. behavior expressible through public Ansible CLI operations;
2. behavior expressible through a reusable collection-loader scenario protocol;
3. private implementation checks with no external distinction.

Only groups 1 and 2 can be strictly split-verified without changing what is public.

```yaml
id: swe-bench-pro/ansible-fqcn-keywords
candidate:
  submission: patch
  base_commit: f533d46572113655a0a698beab4b38671744a458
verification:
  adapter: ansible_cli_and_collection_protocol
  challenges: hidden_identifier_and_loader_scenarios
  observations: {accepted: boolean, exit_code: integer, normalized_output: bounded_text}
  oracle: host_python_identifier_oracle
equivalence:
  preserved: partial
  caveat: original internal regression nodes require individual observability review
```

### Why include this in the paper?

SWE-bench-style rows show the central migration problem clearly: a hidden patch containing unit tests is not a valid split-verification interface. The row must be decomposed into behavioral challenges and observations. Also, benchmark quality is independent of sandbox security: OpenAI's 2026 audit estimated that roughly 30% of SWE-bench Pro's public tasks had serious specification or test problems. SecureBench should audit **fairness and validity** as well as isolation.

## 13. τ-bench retail exchange: verify world state, not candidate code

**Actual row:** the first task in [`retail/tasks_test.py`](https://github.com/sierra-research/tau-bench/blob/59a200c6d575d595120f1cb70fea53cef0632f6b/tau_bench/envs/retail/tasks_test.py)
**Reward implementation:** [`envs/base.py`](https://github.com/sierra-research/tau-bench/blob/59a200c6d575d595120f1cb70fea53cef0632f6b/tau_bench/envs/base.py)

### What the agent is asked to do

A customer wants to exchange two delivered products: a mechanical keyboard for a similar clicky model and a thermostat for a Google Home-compatible model. The customer gives fallback preferences if no perfect keyboard exists.

### What the original checker checks

The task row includes the expected sequence of tool calls. More importantly, τ-bench's reward code reconstructs the correct database end state by applying the reference actions, hashes that state, and compares it with the state produced by the agent's actions. For tasks that require a factual answer, it also checks that required output text appeared in the response.

### Why it already resembles split verification

The agent does not need the database or reward function inside its own execution environment. It can receive only a typed tool interface:

```text
Agent process ── tool call ──▶ trusted environment service
Agent process ◀─ tool result ─┘
                               trusted service owns database
                               host scorer inspects final state
```

The candidate generates actions; the trusted environment validates them and mutates trusted state. At the end, a host oracle compares the database with the expected state. No candidate repository needs to be imported by the scorer.

```yaml
id: tau-bench/retail-exchange-0
candidate:
  submission: agent_policy
verification:
  adapter: typed_tool_api
  challenges: hidden_user_goal_and_initial_database
  observations: {tool_calls: typed_sequence, final_response: bounded_text}
  oracle:
    checks: [final_database_state, required_answer_content, policy_constraints]
  forbidden_in_candidate: [database_snapshot, reference_actions, reward_code]
equivalence:
  preserved: true
```

There is one improvement SecureBench should make: compare semantic state fields rather than only a whole-database hash, and separately score unauthorized side effects. A hash says “different” but does not explain whether the agent made the correct exchange plus an unrelated harmful mutation.

**Design lesson:** Tool-use benchmarks are naturally compatible with full split verification when the world state already lives in a trusted service. This pattern should become a first-class SecureBench family.

---

# Part IV — What cannot be converted faithfully?

The key test is not “Can we invent an RPC wrapper?” The key test is:

> Can every scoring-relevant distinction be derived from bounded observations available through a public candidate interface?

Suppose candidate A and candidate B produce exactly the same allowed observations for every permitted challenge, but an original hidden unit test gives them different scores. Then that assertion is **not split-verifiable under the current interface**. One of four things must happen:

1. add a public diagnostic or probe;
2. replace the assertion with an observable consequence;
3. accept and document a semantic change;
4. reject the task from the strict profile.

Common examples that cannot be preserved as written include:

### Private in-process object assertions

Examples: checking Python object identity, private fields, exact internal class types, JavaScript references, or mock call arguments. The host cannot observe these without loading the library or trusting an in-VM reporter.

### Exact internal call sequences

Examples: “method X is called exactly once before method Y” when no public trace exposes those events. Equivalent implementations may legitimately use a different call graph.

### Arbitrary language callbacks

Examples: a Python test passes a closure to a library and inspects interactions with it. A bounded declarative callback DSL may cover common cases, but arbitrary closures cannot cross a language-neutral boundary safely and faithfully.

### Memory safety, races, and coverage without instrumentation

Valgrind, sanitizers, race detectors, coverage tools, debuggers, and profilers must execute with the candidate. If even public instrumentation is forbidden inside the VM, these properties cannot generally be verified from outside.

### Kernel and privileged-system internals

Tasks whose correctness is defined by kernel memory, eBPF state, syscall hooks, firewall tables, mount namespaces, or privileged device behavior require either a trusted observation channel from the hypervisor or a declared in-guest diagnostic. Ordinary network and CLI observations may be insufficient.

### GUI internals with no accessibility or state API

Pixel output can be observed externally, and inputs can be injected. Hidden widget state, accessibility nodes, or application databases cannot be checked unless the platform exposes them through a public observation primitive. OSWorld-like tasks therefore range from easy visual-state checks to impossible internal-state checks.

### Self-reported pass/fail

A script inside the candidate VM that runs tests and returns `PASS` is not evidence under an adversarial threat model. The candidate controls the script and can forge the result. Only raw observations whose correctness is independently determined by the host should count.

### Hostile artifacts requiring dangerous parsers

HTML, PDFs, office documents, media, model checkpoints, archives, and compiler inputs may exploit the host tool that opens them. Prefer strict bounded parsing for passive artifacts. If evaluating the artifact intentionally executes candidate instructions, that processing belongs in the Evaluation VM and becomes black-box verification. A disposable parser or client sandbox is containment infrastructure, not an independent source of truth. “No candidate instruction executed” is not enough.

## Verification-pattern classification

Classify every converted assertion using the smallest applicable pattern or
combination:

- **Passive artifact verification.** The Oracle retrieves bounded bytes or metadata and verifies them externally without executing candidate-controlled code.
- **Black-box challenge/response.** The Oracle sends per-case inputs or actions to candidate code running only in the Evaluation VM and evaluates externally captured outputs, errors, timing, or protocol behavior.
- **Trusted external state.** The candidate interacts with host-owned state or services whose resulting state the Oracle can inspect independently.
- **New pattern.** Introduce one only when the three patterns cannot faithfully describe the evidence relationship and the new boundary still satisfies all full-standard trust requirements.
- **Redesign or exclude.** Use this when scoring depends on unavailable internal state, an uncorroborated in-VM report, or unsafe co-location.

Adapters, scenario runners, proxies, parser sandboxes, and isolated observers
describe implementation or containment. They are not additional verification
patterns and cannot make an untrusted guest claim authoritative. Public
instrumentation such as Valgrind is a separately disclosed weaker profile when
its report cannot be independently corroborated; it must not be silently mixed
into the benchmark's full split-verification headline score.

---

# Part V — End-to-end conversion procedure

Use this process for every Terminal-Bench or DeepSWE row.

## Step 1: Write the behavioral contract

Ignore the existing test implementation for a moment. State what a correct solution must do in terms a user or external client can observe.

Bad contract:

```text
The hidden pytest test must pass.
```

Good contract:

```text
For every valid collection name, validation returns true. If either segment is a
Python keyword or invalid identifier, validation returns false without crashing.
```

## Step 2: Inventory every original assertion

For each F2P and P2P assertion, record:

| Field | Meaning |
|---|---|
| Assertion | What the old checker decides |
| Prompt support | Where the user-visible task requires it |
| Observation | What real evidence proves it |
| Challenge | What input or event elicits that evidence |
| Oracle | How the host computes correctness |
| Fidelity | Exact, approximate, changed, or impossible |

This inventory prevents thousands of regression tests from disappearing behind the phrase “we converted the task.”

## Step 3: Choose the narrowest public adapter

Prefer, in order:

1. bounded artifact collection;
2. an existing public protocol such as HTTP, SSH, CLI, SQL, or a programming language;
3. a generic reusable scenario protocol;
4. a public instrumentation primitive;
5. task rejection if none of the above is faithful.

A task-specific script that imports the candidate and prints whether hidden conditions passed is still a verifier inside the VM.

## Step 4: Separate challenge from oracle

The VM receives only the current challenge. The host retains:

- the rest of the corpus;
- expected values;
- acceptance thresholds;
- scoring weights;
- reference solutions;
- task-specific assertions.

Use per-case nonces and randomized variants when possible. This makes hard-coded responses less useful, although secrecy should never be treated as the primary sandbox boundary.

## Step 5: Bound and type every observation

Each channel needs explicit limits:

- maximum messages and calls;
- request and response byte limits;
- time and CPU limits;
- permitted ports and methods;
- artifact count, path, and size limits;
- schemas for errors, traces, and metadata.

Never deserialize candidate-controlled language objects on the host. Prefer simple typed formats and hardened parsers.

## Step 6: Rebuild regression coverage behaviorally

DeepSWE's P2P lists and SWE-bench's regression tests matter. Convert them by capability cluster rather than mechanically exposing `pytest` or `go test`:

```text
3,134 FastAPI P2P nodes
        ↓ classify
HTTP behavior | OpenAPI | middleware | routing lifecycle | private internals
        ↓
host HTTP corpus + public diagnostics + explicit exclusions
```

Record coverage before and after conversion. A useful paper metric is:

```text
behavioral preservation = externally reproduced original assertions
                          -------------------------------------------
                          all valid original assertions
```

Report this alongside task pass rates.

## Step 7: Differentially validate the conversion

For each row:

1. run the original verifier on the base commit—it should fail the F2P behavior;
2. run it on the reference solution—it should pass;
3. run the split verifier on both and require the same result;
4. collect several real agent patches;
5. compare old and new verdicts;
6. manually review disagreements;
7. add deliberately malicious candidates that forge output, hang, flood channels, probe the host, or special-case public examples.

The goal is not merely “the gold patch passes.” The new verifier should agree on diverse correct and incorrect implementations.

---

# Part VI — What this implies for the SecureBench standard

The examples suggest that the standard needs a small number of reusable
implementation primitives. These are adapters and containment mechanisms, not
an alternative taxonomy: each use must still map to passive artifact
verification, black-box challenge/response, trusted external state, or an
explicitly weaker/non-standard profile.

| Implementation primitive | Pattern mapping | Challenge sent to VM | Evidence returned | Example |
|---|---|---|---|---|
| `artifact` | Passive artifact verification | none | bounded bytes + metadata | ICS schedule |
| `cli` | Black-box challenge/response | argv/stdin/environment subset | stdout/stderr/exit/time | circuit simulator |
| `network_service` | Black-box challenge/response | protocol request | protocol response | Git + web server |
| `language_runner` | Black-box challenge/response | source/program text | output/error | Anko interpreter |
| `scenario_runner` | Black-box, optionally trusted external state | declarative typed scenario | typed trace or host-state effects | HTTPX, Kea, Testem |
| `state_api` | Trusted external state | user/tool actions | semantic state projection | τ-bench |
| `instrumented_runtime` | Weaker public-instrumented profile unless externally corroborated | workload + public instrument selection | hostile typed report | Valgrind/sanitizers |
| `isolated_observer` | Passive or black-box, depending on whether candidate instructions execute | hostile artifact or protocol data | minimal hostile observation | browser-rendered HTML |

Every primitive should specify:

- who owns and pins the adapter;
- whether the adapter is present during the agent phase;
- the exact schema and limits;
- which side initiates communication;
- how the host authenticates a fresh VM;
- how replay and cross-case state are prevented;
- what is secret and what is public;
- which parsers and runtimes enter the trusted computing base;
- how the VM is destroyed and evidence retained.

If an isolated observer intentionally executes candidate-controlled content,
it must be the Evaluation VM (or a compartment within that boundary), not a
third candidate-execution environment. If it only parses hostile bytes for a
passive check, isolation is defense in depth and its report must still be
validated according to the passive-artifact rules.

## Recommended rule for adapters

A public adapter is acceptable only if all of the following are true:

1. its code and protocol are visible to benchmark authors and agents;
2. it contains no task-specific expected value or assertion;
3. it can be reused by multiple tasks or generated from a general schema;
4. it returns observations, never an authoritative pass/fail;
5. the host can independently recompute the verdict;
6. its launch and collection path is controlled by the external VM supervisor where possible;
7. every response—including reports produced by an unchanged adapter—is typed, bounded, and treated as hostile;
8. the standard states whether a guest component can be modified or impersonated and how that affects evidence strength.

## Recommended row-review questions

Before admitting a task, reviewers should answer:

- What exact property is being measured?
- Is every hidden assertion supported by the public prompt?
- What secret stimulus enters the VM?
- What exact observation leaves it?
- Could the candidate forge that observation without exhibiting the required behavior?
- Does the host parse or execute attacker-controlled content?
- Does any test, answer, threshold, or reference patch enter the VM?
- Which original assertions were preserved, changed, or dropped?
- Does the base commit fail and the gold patch pass under both verifiers?
- Would two externally indistinguishable implementations ever receive different scores?

If the answer to the last question is yes, the row is not ready for strict split verification.

---

# Bottom line for the Terminal-Bench and DeepSWE PoC

Converting the **framework plumbing** is manageable: create one-way, capability-limited challenge channels; typed observation channels; disposable VM lifecycle; and host-side oracles.

Converting the **benchmarks faithfully** is the larger research contribution.

For Terminal-Bench, many tasks produce files, CLIs, or services and should convert cleanly. The hardest rows involve privileged system state, instrumentation, hostile file formats, GUI state, or self-reported tests.

For DeepSWE, simple language and protocol features can convert well, but its large in-process regression suites cannot be transplanted under the new rule. Each task needs an assertion inventory, a public behavioral interface, a host challenge corpus, and an explicit fidelity report. The Anko row is a good first success case; HTTPX and FastAPI demonstrate increasingly rich adapters; Kea and Testem reveal the limit of the standard.

A convincing PoC should therefore not claim “all existing tests were moved outside.” It should demonstrate:

1. several reusable adapter primitives;
2. end-to-end conversion of representative rows;
3. measured agreement with the original verifiers;
4. preserved F2P and P2P coverage;
5. malicious-candidate resistance;
6. explicit `SV-X` rejection for assertions that cannot be observed faithfully.

That result is stronger academically than forcing every row to fit. It shows where secure evaluation is possible, how much meaning is preserved, and where existing benchmarks rely on trust that their task format never made explicit.

## Sources and reproducibility notes

- [Terminal-Bench 2.0 task registry](https://www.tbench.ai/benchmarks/terminal-bench-2) and [official task repository](https://github.com/harbor-framework/terminal-bench-2), inspected at commit `2fd12b88aafdd04a52c298e3940bcb189f9766d6`.
- [DeepSWE official repository and task-format description](https://github.com/datacurve-ai/deep-swe), inspected at commit `e016041a6ccf8da29906afc9a3f5a8df940a1f78`.
- [DeepSWE paper](https://arxiv.org/abs/2607.07946).
- [SWE-bench Verified introduction](https://openai.com/index/introducing-swe-bench-verified/) for the repository-issue-patch evaluation pattern.
- [OpenAI's SWE-bench Pro audit](https://openai.com/index/separating-signal-from-noise-coding-evaluations/) for the distinction between secure execution and valid task design.
- [τ-bench official repository](https://github.com/sierra-research/tau-bench), inspected at commit `59a200c6d575d595120f1cb70fea53cef0632f6b`.
- [Anthropic on infrastructure noise in agentic coding evaluations](https://www.anthropic.com/engineering/infrastructure-noise) for why environment control and reproducibility materially affect Terminal-Bench and SWE-bench scores.
- [OpenAI GPT-5.2 release](https://openai.com/index/introducing-gpt-5-2/) and [Anthropic system card](https://www-cdn.anthropic.com/78073f739564e986ff3e28522761a7a0b4484f84.pdf) as examples of major-lab reporting on SWE-bench Pro, Terminal-Bench, τ-bench-family, and OSWorld-family evaluations.

Research snapshot date: **2026-08-06**.
