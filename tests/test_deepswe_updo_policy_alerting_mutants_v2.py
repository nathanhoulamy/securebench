"""Real-code targeted mutants for `deep-swe/updo-policy-alerting`.

`updo-policy-alerting` was admitted with mutant coverage that was Oracle-level
only (`drive_updo` in `test_pilot_conversions_v2.py`, which feeds hand-built
observations straight to the Oracle subprocess) plus the real-Docker generic
"drop the largest non-test file" mutant
(`test_deepswe_first_wave_replay_v2.py::test_incomplete_implementation_mutant_fails`).
Neither exercises a real, compiled near-miss implementation of the feature
running inside a Docker Evaluation. This file adds that: each mutant here is
the upstream gold `solution.patch` plus one small hand edit to the real Go
source, applied to a cloned workspace, captured through the production
`capture_git_patch_workspace` path, and replayed through a real Evaluation
container and the real Oracle (`verify_patch(..., reference=True,
mutate=...)`), per the DeepSWE conversion playbook's Gate 3 and defect #8.

Each mutant targets a distinct semantic axis named in the public
`instruction.md` or exercised by an upstream `test.patch` assertion, and each
was confirmed (defect #8) to make at least one Oracle case actually diverge
before being wired in here -- see the per-mutant docstrings and the row
dossier's "Review correction: real-code mutants" section for the verification
log.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.deepswe_qualification import materialize_baseline, verify_patch
from tests.qualification_support import DOCKER_INTEGRATION


NAME = "updo-policy-alerting"


def _replace_once(path: Path, before: str, after: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(before)
    assert count == 1, (path, count, before)
    path.write_text(text.replace(before, after), encoding="utf-8")


@pytest.fixture(scope="module")
def baseline(tmp_path_factory):
    root = tmp_path_factory.mktemp(f"{NAME}-baseline") / "app"
    return materialize_baseline(NAME, root)


# ---------------------------------------------------------------------------
# Three (plus one bonus) targeted real-code mutants, gold patch + one hand
# edit each, replayed through real Docker Evaluations, each on a distinct
# semantic axis named in the public instruction or an upstream test.
# ---------------------------------------------------------------------------


def _mutate_ssl_expiring_never_rearms(workspace: Path) -> None:
    """Axis: "ssl_expiring ... fires once, then not again until it goes
    above threshold and re-enters it" (instruction) --
    `TestTrackerSSLExpiringFiresOnceUntilRearmed` upstream.

    The gold `alerts.(*Tracker).handleSSL` clears `SSLAlertActive` once the
    certificate's remaining days rise back above the threshold, so a later
    dip below threshold fires `ssl_expiring` again. This hand edit removes
    that clear, leaving `SSLAlertActive` permanently latched after the first
    firing -- a plausible near-miss for an implementation that gets the
    initial "fire once" half right but forgets the re-arm half. Confirmed
    (playbook defect #8) to flip the Oracle's SSL case (`case_1`): its
    `-rearm` check (10 -> 9 -> 20 -> 12 days) expects `ssl_expiring` again at
    12 days, and its `expected["requests"]` list expects two webhook
    deliveries (`-ssl1`, `-ssl2`); with the bug only the first ever fires, so
    both the `decision_4` (event/state) and `request_count`/payload
    checks for `case_1` diverge, while `case_0`, `case_2` and the config/
    simple cases are unaffected.
    """
    target = workspace / "alerts" / "policy.go"
    _replace_once(
        target,
        '\tif check.SSLDaysRemaining <= t.policy.SSLExpiryThresholdDays {\n'
        '\t\tif !t.snapshot.SSLAlertActive {\n'
        '\t\t\tt.snapshot.SSLAlertActive = true\n'
        '\t\t\tdecision.Event = EventSSLExpiring\n'
        '\t\t\tdecision.Reason = fmt.Sprintf("SSL certificate expires in %d days", check.SSLDaysRemaining)\n'
        '\t\t}\n'
        '\t\treturn\n'
        '\t}\n'
        '\n'
        '\tt.snapshot.SSLAlertActive = false\n'
        '}\n',
        '\tif check.SSLDaysRemaining <= t.policy.SSLExpiryThresholdDays {\n'
        '\t\tif !t.snapshot.SSLAlertActive {\n'
        '\t\t\tt.snapshot.SSLAlertActive = true\n'
        '\t\t\tdecision.Event = EventSSLExpiring\n'
        '\t\t\tdecision.Reason = fmt.Sprintf("SSL certificate expires in %d days", check.SSLDaysRemaining)\n'
        '\t\t}\n'
        '\t\treturn\n'
        '\t}\n'
        '\n'
        '\t// BUG: SSL alert never re-arms once triggered\n'
        '}\n',
    )


def _mutate_cooldown_suppression_disabled(workspace: Path) -> None:
    """Axis: "cooldown_seconds suppresses non-recovery notifications for the
    same target during the cooldown window" (instruction) --
    `TestTrackerRepeatedDegradedEventsAreSuppressedByCooldown` and
    `TestTrackerSSLAndCooldown` upstream.

    The gold `shouldSuppress` computes the cooldown window from the last
    non-suppressed non-recovery event. This hand edit hardcodes the
    non-recovery branch to always return `false` -- a plausible near-miss
    for an implementation that models state transitions correctly but drops
    the cooldown-window arithmetic. Confirmed (playbook defect #8) to flip
    the Oracle's `case_0` (tracker with `cooldown_seconds=300`): the
    `-suppressed` check at `at_seconds=60` (40s after the `-down` event at
    `at_seconds=20`) expects `Decision.Suppressed=True` (`decision_6`) and
    expects that check's webhook request to be withheld (it is absent from
    `expected["requests"]`); with the bug it is neither suppressed nor
    withheld, diverging both `decision_6` and `request_count` for `case_0`,
    while the unrelated SSL, config and simple cases are unaffected.
    """
    target = workspace / "alerts" / "policy.go"
    _replace_once(
        target,
        '\tswitch event {\n'
        '\tcase EventTargetRecovered, EventTargetHealthy:\n'
        '\t\treturn false\n'
        '\tdefault:\n'
        '\t\treturn !lastEventAt.IsZero() && now.Sub(lastEventAt) < policy.Cooldown\n'
        '\t}\n'
        '}\n',
        '\tswitch event {\n'
        '\tcase EventTargetRecovered, EventTargetHealthy:\n'
        '\t\treturn false\n'
        '\tdefault:\n'
        '\t\treturn false // BUG: cooldown suppression disabled\n'
        '\t}\n'
        '}\n',
    )


def _mutate_webhook_custom_headers_dropped(workspace: Path) -> None:
    """Axis: "`HandleWebhookDecisionWithHeaders` must preserve custom
    headers" (instruction) -- `TestHandleWebhookDecisionWithHeaders`
    upstream.

    The gold `handleWebhookDecision` builds the outgoing header map from the
    caller-supplied `headers` slice. This hand edit passes `nil` instead --
    a plausible near-miss for an implementation that wires the
    `WithHeaders` entry point through to the shared helper but forgets to
    actually forward the headers argument. Confirmed (playbook defect #8) to
    flip every case that carries a `requests` expectation (`case_0`,
    `case_1`, `case_2`): the Oracle's `_requests` check decodes each
    delivered webhook's `X-SecureBench-Token` header and compares it against
    the per-check token it minted, so every delivered request in those cases
    fails `custom_header`, while the config and simple cases (which send no
    webhook requests) are unaffected.
    """
    target = workspace / "notifications" / "webhook.go"
    _replace_once(
        target,
        # `webhook.go` has two `parseHeaders(headers)` call sites: the
        # pre-existing `HandleWebhookAlert` (unrelated legacy path, followed
        # by a blank line and `SendWebhook(...)`) and the new
        # `handleWebhookDecision` (immediately followed by
        # `SendWebhookWithClient(...)`, no blank line). Anchor on the second
        # line to hit only the new decision path.
        "\theaderMap := parseHeaders(headers)\n"
        "\tif err := SendWebhookWithClient(webhookURL, client, headerMap, payload); err != nil {\n",
        "\theaderMap := parseHeaders(nil) // BUG: custom headers dropped\n"
        "\tif err := SendWebhookWithClient(webhookURL, client, headerMap, payload); err != nil {\n",
    )


def _mutate_config_ssl_threshold_not_inherited(workspace: Path) -> None:
    """Axis: "`global.alert_policy` is inherited unless overridden"
    (instruction) -- `TestLoadConfigAlertPolicyInheritance` upstream.

    The gold `mergeAlertPolicy` falls each zero-valued target field back to
    the corresponding global field, including `SSLExpiryThresholdDays`. This
    hand edit drops that one field's fallback -- a plausible near-miss for
    an implementation that gets five of the six inherited fields right but
    misses one. Confirmed (playbook defect #8) to flip the Oracle's
    config-inheritance case (`case_3`): the second target overrides only
    `consecutive_failures`/`latency_breach_count` and expects
    `ssl_expiry_threshold_days` to inherit the global value `14`; with the
    bug it stays `0`, diverging `config_policy` for `case_3`, while the
    single-target defaults case (`case_4`, where both global and target
    leave it at `0` either way) is unaffected.
    """
    target = workspace / "config" / "config.go"
    _replace_once(
        target,
        '\tif target.SSLExpiryThresholdDays == 0 {\n'
        '\t\ttarget.SSLExpiryThresholdDays = global.SSLExpiryThresholdDays\n'
        '\t}\n',
        '\t// BUG: SSL expiry threshold inheritance dropped\n',
    )


MUTANTS = [
    _mutate_ssl_expiring_never_rearms,
    _mutate_cooldown_suppression_disabled,
    _mutate_webhook_custom_headers_dropped,
    _mutate_config_ssl_threshold_not_inherited,
]


@DOCKER_INTEGRATION
@pytest.mark.parametrize(
    "mutate",
    MUTANTS,
    ids=[
        "ssl-expiring-never-rearms",
        "cooldown-suppression-disabled",
        "webhook-custom-headers-dropped",
        "config-ssl-threshold-not-inherited",
    ],
)
def test_targeted_real_code_mutant_fails(tmp_path, baseline, mutate):
    outcome = verify_patch(
        NAME, baseline, tmp_path, reference=True, mutate=mutate,
        run_seed=f"{NAME}-mutant-{mutate.__name__}",
    )

    assert outcome.status == "failed", (mutate.__name__, outcome.result)
    assert not outcome.infrastructure_errors, outcome.evidence
