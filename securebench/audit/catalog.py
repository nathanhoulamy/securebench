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
ORACLE_TAMPERING = "oracle_tampering"
TEST_INFRA_TAMPERING = "test_infra_tampering"
NETWORK_EGRESS = "network_egress"
RESULT_INTEGRITY_GAP = "result_integrity_gap"


CATALOG: tuple[VulnerabilityClass, ...] = (
    VulnerabilityClass(
        ANSWER_LEAKAGE,
        "critical",
        ("repo_patch", "terminal_task"),
        "Trusted answers or verifier data are visible to the candidate-producing agent.",
    ),
    VulnerabilityClass(
        VISIBILITY_BYPASS,
        "critical",
        ("repo_patch", "terminal_task"),
        "Compiled task visibility boundaries do not match the intended component view.",
    ),
    VulnerabilityClass(
        MATERIALIZATION_ESCAPE,
        "critical",
        ("repo_patch", "terminal_task"),
        "A benchmark resource can be materialized outside its authorized path root.",
    ),
    VulnerabilityClass(
        ORACLE_TAMPERING,
        "critical",
        ("repo_patch", "terminal_task"),
        "Candidate output can modify trusted host Oracle state.",
    ),
    VulnerabilityClass(
        TEST_INFRA_TAMPERING,
        "high",
        ("repo_patch", "terminal_task"),
        "Candidate output can modify test infrastructure rather than solving the task.",
    ),
    VulnerabilityClass(
        NETWORK_EGRESS,
        "high",
        ("repo_patch", "terminal_task"),
        "Candidate execution can reach undeclared network destinations.",
    ),
    VulnerabilityClass(
        RESULT_INTEGRITY_GAP,
        "medium",
        ("repo_patch", "terminal_task"),
        "Result records do not identify or protect the benchmark inputs they summarize.",
    ),
)


def catalog_entry(vulnerability: str) -> VulnerabilityClass:
    """Return one catalog entry by id."""
    for entry in CATALOG:
        if entry.id == vulnerability:
            return entry
    raise KeyError(vulnerability)
