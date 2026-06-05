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
