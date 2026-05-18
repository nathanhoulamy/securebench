# Problems

## Tester-Provided Harness Images

If `harness.mode: container` uses an image supplied by the tester, SecureBench
does not currently guarantee that the image is safe, reproducible, or free of
vulnerabilities. The image should be treated as part of the untrusted
candidate-producing side.

Current runtime hardening limits what the container can access, and the harness
workspace should contain only public task data. However, this does not prove the
image itself is trustworthy, prevent all container/runtime escapes, or protect
any secrets explicitly passed through `harness.env`.

Open questions:

- Should SecureBench require pinned image digests instead of mutable tags?
- Should named harnesses use approved/audited images or Dockerfiles?
- Should image vulnerability scanning or version preflight be required?
- What metadata should be recorded for reproducibility and audit?
- How should secrets passed to harness images be scoped and redacted?

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
