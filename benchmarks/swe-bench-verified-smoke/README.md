# SWE-bench Verified Smoke

This smoke pack converts three SWE-bench Verified rows into SecureBench's
`repo_patch` family shape. It uses public prebuilt Docker images and a command
harness that emits each row's gold patch as the candidate patch, so the run
exercises candidate extraction plus repo-patch verification without requiring an
agent.
