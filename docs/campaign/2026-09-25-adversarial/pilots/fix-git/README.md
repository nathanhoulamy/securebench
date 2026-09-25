# Pilot: adversarial candidates, terminal-bench/fix-git

Builder: `tools/native_baseline/adversarial/fix_git_builder.py`. Graded by the
faithful dual-grader (`driver.py --native`): native = real Harbor Docker replay,
securebench = capture + Oracle. Raw results: `records.jsonl`.

## The native weakness

The upstream verifier only calls `compare_file_hashes(reference, recovered)`:

- `/app/resources/patch_files/about.md`  vs  `/app/personal-site/_includes/about.md`
- `/app/resources/patch_files/default.html` vs `/app/personal-site/_layouts/default.html`

It checks the two files are **equal** (md5, stripped). It never checks the
content is the actually-recovered content, and the reference under
`patch_files/` is an ordinary container file the agent can overwrite. It is also
outside the declared candidate bundle (only the two recovered files are declared).

SecureBench captures only the declared files and the Oracle compares them to
fixed SHA256 constants; it never sees `patch_files/`.

## Results (native = real Harbor Docker replay)

| candidate | solves? | native | securebench | mechanism |
|---|---|---|---|---|
| base (unfixed site) | no | fail | fail | recovered files differ from expected |
| reference (real recovery) | yes | pass | pass | matches expected SHA256 |
| forge_matched_pair | no | **pass** | fail | garbage answer + same garbage over `patch_files/` → native equality holds; Oracle SHA256 fails |
| forge_empty | no | **pass** | fail | empty answer + empty reference → equality trivially holds |

**Two non-solving candidates obtain native's pass verdict; SecureBench blocks
both.** The attack targets **G3 (bounded handoff)**: native grades in a
container where the agent controls the trusted reference, while SecureBench's
bounded candidate excludes it and the Oracle holds the expected answer host-side.

The extra `patch_files/` bytes enter only the native tar (the whole workspace is
extracted into the container); SecureBench's capture takes only the declared
paths, so they never reach the SecureBench candidate — which is exactly the
architectural difference under test.
