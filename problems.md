# Problems

## Externally Provided Environment Images

If `harness.mode: container` uses the benchmark row or manifest
`environment.image`, SecureBench does not currently guarantee that the image is
safe, reproducible, or free of vulnerabilities. The environment image should be
treated as untrusted runtime infrastructure unless it is pinned and audited.

Current runtime hardening limits what the container can access, and the harness
workspace should contain only public task data. However, this does not prove the
image itself is trustworthy, prevent all container/runtime escapes, or protect
any secrets explicitly passed through `harness.env`.

Open questions:

- Should SecureBench require pinned image digests instead of mutable tags?
- Should named harnesses use approved/audited images or Dockerfiles?
- Should image vulnerability scanning or version preflight be required?
- What metadata should be recorded for reproducibility and audit?
- How should secrets passed to harness containers be scoped and redacted?

## Harness Workspace Task Filename

The command harness currently writes the public task payload to
`securebench_task.json` by default. That filename is unnecessarily
framework-branded inside the harness workspace.

Preferred behavior: write the public task payload as `task.json`.

Open questions:

- Should `task.json` be the hard default for all harness types?
- Should tester YAML still allow overriding the task filename?
- Should old `securebench_task.json` support remain as a temporary
  compatibility alias?

## Harness and Evaluation Environment Parity

Coding agents need to iterate in an environment that matches the eventual
evaluation environment, minus hidden tests and other non-public evaluator
inputs. If the harness container uses a separate agent image and the test
sandbox uses a different benchmark environment image, the agent may be unable
to reproduce dependency, runtime, system package, browser, or repository
behavior while working.

Decision: container harnesses should use the benchmark row or manifest
`environment.image` as the base runtime. Named agent harnesses can add tooling
through a future overlay, but they should not replace the benchmark runtime.

Open questions:

- Should SecureBench build a derived image that combines the benchmark runtime
  with the selected harness tooling?
- How do we guarantee the harness can run public tests or diagnostics without
  seeing hidden tests?
- How do we keep hidden/evaluation inputs out while still giving the agent the
  same dependencies and runtime as evaluation?
- What metadata or checks prove that the harness and evaluation sandboxes are
  environment-compatible?
