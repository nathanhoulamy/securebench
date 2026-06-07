# Berkeley Blog Failure-Class Mapping

| Berkeley failure class | Berkeley profile | Expected SecureBench behavior |
| --- | --- | --- |
| Answers/checker data shipped with task | `leak_probe` | Agent cannot read hidden or evaluation data. |
| No isolation between agent and evaluator | `terminal_poison` | Trusted checker comes from read-only evaluator mount. |
| Test infrastructure tampering | `repo_tamper` | Repo-patch policy rejects test, CI, dependency, and SecureBench paths. |
| `eval()` or command execution on untrusted input | `evaluator_escape` | Candidate-controlled payloads are evaluated only by trusted verifier code, with shell/Python hardening where applicable. |
| Network/tool exfiltration | `network_exfil`, `live_openai` | Generic egress is blocked and provider tools are blocked by default. |
| Weak string matching or evaluation logic that does not evaluate | `output_only` | Hidden/eval checker rejects magic output-only and edge-case candidates. |
| Trusting output of untrusted code | `artifact_forgery` | SecureBench extracts raw candidates and runs trusted verification rather than trusting candidate reward files or logs. |
| Result integrity and replay gaps | documented gap | V1 reports current behavior but does not claim result signing/resume hardening. |
| LLM judge prompt injection | not applicable in current families | V1 implemented families do not use LLM-as-judge verification. |

Use this table when preparing evidence for Berkeley reviewers. The runnable
artifact is the run output: `results.jsonl`, `summary.json`, and per-task traces.
