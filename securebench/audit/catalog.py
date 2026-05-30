"""Audit vulnerability catalog."""

from __future__ import annotations

from dataclasses import dataclass

from securebench.audit.models import AuditSeverity


@dataclass(frozen=True)
class VulnerabilityClass:
    """One benchmark-security failure class."""

    id: str
    severity: AuditSeverity
    families: tuple[str, ...]
    description: str


ANSWER_LEAKAGE = "answer_leakage"
VISIBILITY_BYPASS = "visibility_policy_bypass"
MATERIALIZATION_ESCAPE = "materialization_escape"
EVALUATOR_TAMPERING = "evaluator_tampering"
TEST_INFRA_TAMPERING = "test_infra_tampering"
WEAK_SCORING = "weak_scoring"
CANDIDATE_CODE_ESCAPE = "candidate_code_escape"
NETWORK_EGRESS = "network_egress"
RESULT_INTEGRITY_GAP = "result_integrity_gap"
JUDGE_PROMPT_INJECTION = "judge_prompt_injection"


CATALOG: tuple[VulnerabilityClass, ...] = (
    VulnerabilityClass(
        ANSWER_LEAKAGE,
        "critical",
        ("multiple_choice", "short_answer", "free_response", "code_completion", "repo_patch", "terminal_task"),
        "Trusted answers or verifier data are visible to the candidate-producing agent.",
    ),
    VulnerabilityClass(
        VISIBILITY_BYPASS,
        "critical",
        ("multiple_choice", "short_answer", "free_response", "code_completion", "repo_patch", "terminal_task"),
        "Compiled task visibility boundaries do not match the intended component view.",
    ),
    VulnerabilityClass(
        MATERIALIZATION_ESCAPE,
        "critical",
        ("code_completion", "repo_patch", "terminal_task"),
        "A benchmark resource can be materialized outside its authorized path root.",
    ),
    VulnerabilityClass(
        EVALUATOR_TAMPERING,
        "critical",
        ("code_completion", "repo_patch", "terminal_task"),
        "Candidate output can modify trusted evaluator state.",
    ),
    VulnerabilityClass(
        TEST_INFRA_TAMPERING,
        "high",
        ("repo_patch", "terminal_task"),
        "Candidate output can modify test infrastructure rather than solving the task.",
    ),
    VulnerabilityClass(
        WEAK_SCORING,
        "medium",
        ("multiple_choice", "short_answer", "free_response"),
        "A scorer rewards answer spraying, substring collisions, or ambiguous final answers.",
    ),
    VulnerabilityClass(
        CANDIDATE_CODE_ESCAPE,
        "critical",
        ("code_completion", "terminal_task"),
        "Candidate-controlled code can escape process or sandbox assumptions.",
    ),
    VulnerabilityClass(
        NETWORK_EGRESS,
        "high",
        ("code_completion", "repo_patch", "terminal_task"),
        "Candidate execution can reach undeclared network destinations.",
    ),
    VulnerabilityClass(
        RESULT_INTEGRITY_GAP,
        "medium",
        ("multiple_choice", "short_answer", "free_response", "code_completion", "repo_patch", "terminal_task"),
        "Result records do not identify or protect the benchmark inputs they summarize.",
    ),
    VulnerabilityClass(
        JUDGE_PROMPT_INJECTION,
        "high",
        ("free_response",),
        "Candidate text can influence a judge or rubric executor.",
    ),
)


def catalog_entry(vulnerability: str) -> VulnerabilityClass:
    """Return one catalog entry by id."""
    for entry in CATALOG:
        if entry.id == vulnerability:
            return entry
    raise KeyError(vulnerability)
