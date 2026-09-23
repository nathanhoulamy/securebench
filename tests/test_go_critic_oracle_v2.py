"""Oracle comparison tests, distinct from real candidate qualification."""
from copy import deepcopy
import json
from pathlib import Path
import re

import pytest

from tests.qualification_support import load_module

ROOT = Path(__file__).resolve().parents[1]
ORACLE = ROOT / "benchmarks/deep-swe/v2/hidden/go-critic-doc-link-checker/oracle"
MODULE = load_module(ORACLE / "oracle.py", "go_critic_oracle")
FIXTURES = json.loads((ORACLE / "cases.json").read_text())


def observation(case):
    return {"status":"observed", "observation":{
        "status":"observed", "error":"",
        "diagnostics":[dict(d, column=1) for d in case["expected"]]}}


def test_source_positive_and_negative_fixtures_are_represented():
    counts = {f["id"]:len(f["expected"]) for f in FIXTURES}
    assert counts == {
        "brokenDocLink/negative_tests.go":0, "brokenDocLink/positive_tests.go":20,
        "builtinShadow/negative_tests.go":0, "builtinShadow/positive_tests.go":49,
        "builtinShadowDecl/negative_tests.go":0, "builtinShadowDecl/positive_tests.go":8,
        "commentFormatting/line.go":0, "commentFormatting/negative_tests.go":0,
        "commentFormatting/positive_tests.go":6, "deprecatedComment/negative_tests.go":0,
        "deprecatedComment/positive_tests.go":43, "importShadow/negative_tests.go":0,
        "importShadow/positive_tests.go":12,
    }


def test_challenges_contain_no_grading_directives_or_expectations():
    a, b = MODULE.cases("a"), MODULE.cases("b")
    assert a == MODULE.cases("a") and a != b
    for case in a:
        assert set(case["challenge"]) == {"checker", "files"}
        for item in case["challenge"]["files"]:
            assert "/*!" not in item["source"]
            assert not re.search(r"(?m)^\s*/// ", item["source"])
        assert len(json.dumps(case["challenge"]).encode()) < 65536


def test_oracle_requires_all_cases_and_rejects_repeats():
    oracle = MODULE.GoCriticOracle()
    oracle.initialize({"run_seed":"qualification"})
    assert not oracle.verdict()["verdict"]["passed"]
    for case in oracle.cases:
        oracle.evaluate(case, observation(case))
    assert oracle.verdict()["verdict"]["passed"]
    oracle.evaluate(oracle.cases[0], observation(oracle.cases[0]))
    assert not oracle.verdict()["verdict"]["passed"]


@pytest.mark.parametrize("case_id,index", [
    (f["id"], i) for f in FIXTURES for i in range(len(f["expected"]))
])
def test_each_original_warning_is_required(case_id, index):
    oracle = MODULE.GoCriticOracle()
    oracle.initialize({"run_seed":"qualification"})
    case = next(c for c in oracle.cases if c["id"] == case_id.split('/')[0])
    evidence = observation(case)
    del evidence["observation"]["diagnostics"][index]
    oracle.evaluate(case, evidence)
    assert oracle.failures == ["diagnostics_mismatch"]


@pytest.mark.parametrize("mutation", ["line", "text", "extra", "duplicate", "boolean", "claims"])
def test_oracle_rejects_wrong_locations_extra_warnings_and_claims(mutation):
    oracle = MODULE.GoCriticOracle()
    oracle.initialize({"run_seed":"qualification"})
    case = next(c for c in oracle.cases if c["expected"])
    evidence = observation(case)
    warnings = evidence["observation"]["diagnostics"]
    if mutation == "line": warnings[0]["line"] += 1
    elif mutation == "text": warnings[0]["message"] = "almost correct"
    elif mutation == "extra": warnings.append({"file":"positive_tests.go", "line":1, "column":1, "message":"extra"})
    elif mutation == "duplicate": warnings.append(deepcopy(warnings[0]))
    elif mutation == "boolean": warnings[0]["line"] = True
    else: evidence["observation"] = {"status":"observed", "error":"", "diagnostics":[], "passed":True}
    oracle.evaluate(case, evidence)
    assert oracle.failures


def test_clean_fixture_rejects_false_positive():
    oracle = MODULE.GoCriticOracle()
    oracle.initialize({"run_seed":"qualification"})
    case = oracle.cases[0]
    evidence = observation(case)
    evidence["observation"]["diagnostics"].append({"file":"negative_tests.go","line":1,"column":1,"message":"bogus"})
    oracle.evaluate(case, evidence)
    assert oracle.failures == ["diagnostics_mismatch"]
