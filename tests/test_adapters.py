from securebench.adapters import HumanEvalAdapter, MMLUAdapter, SWEBenchVerifiedAdapter


def test_mmlu_adapter_hides_answer_from_agent_payload():
    row = {
        "question": "2 + 2?",
        "subject": "math",
        "choices": ["1", "2", "4", "5"],
        "answer": 2,
    }

    adapter = MMLUAdapter()
    task_spec = adapter.to_task_spec(row, split="test", row_idx=7)
    task = adapter.to_task(row, split="test", row_idx=7)

    assert task_spec["resources"]["answer"]["visibility"] == "hidden"
    assert task.id == "mmlu/math/test/7"
    assert task.answer == 2
    assert [resource.name for resource in task.resources.by_visibility("hidden")] == ["answer"]
    assert task.agent_payload() == {
        "question": "2 + 2?",
        "choices": ["1", "2", "4", "5"],
        "subject": "math",
    }


def test_humaneval_adapter_hides_tests_and_solution():
    row = {
        "task_id": "HumanEval/0",
        "prompt": "def add(a, b):",
        "canonical_solution": "\n    return a + b",
        "test": "def check(candidate): assert candidate(1, 2) == 3",
        "entry_point": "add",
    }

    adapter = HumanEvalAdapter()
    task_spec = adapter.to_task_spec(row)
    task = adapter.to_task(row)

    assert task_spec["resources"]["tests"]["visibility"] == "hidden"
    assert task_spec["resources"]["canonical_solution"]["visibility"] == "hidden"
    assert task.tests == row["test"]
    assert task.canonical_solution == row["canonical_solution"]
    assert {resource.name for resource in task.resources.by_visibility("hidden")} == {
        "canonical_solution",
        "tests",
    }
    assert "id" not in task.agent_payload()
    assert "test" not in task.agent_payload()
    assert "tests" not in task.agent_payload()
    assert "canonical_solution" not in task.agent_payload()


def test_swebench_adapter_coerces_test_fields_and_formats_prediction():
    row = {
        "repo": "astropy/astropy",
        "instance_id": "astropy__astropy-12907",
        "base_commit": "abc123",
        "patch": "gold patch",
        "test_patch": "hidden tests",
        "problem_statement": "Fix the bug.",
        "hints_text": "",
        "version": "4.3",
        "FAIL_TO_PASS": '["tests/test_bug.py::test_fixed"]',
        "PASS_TO_PASS": ["tests/test_existing.py::test_still_passes"],
    }
    adapter = SWEBenchVerifiedAdapter()

    task_spec = adapter.to_task_spec(row)
    task = adapter.to_task(row)
    prediction = adapter.format_prediction(task, "diff --git ...")

    assert task_spec["resources"]["gold_patch"]["visibility"] == "hidden"
    assert task_spec["resources"]["test_patch"]["visibility"] == "hidden"
    assert task.fail_to_pass == ("tests/test_bug.py::test_fixed",)
    assert task.pass_to_pass == ("tests/test_existing.py::test_still_passes",)
    assert task.test_groups == {
        "fail_to_pass": ("tests/test_bug.py::test_fixed",),
        "pass_to_pass": ("tests/test_existing.py::test_still_passes",),
    }
    assert task.hidden_patches == {"tests": "hidden tests"}
    assert {resource.name for resource in task.resources.by_visibility("hidden")} >= {
        "gold_patch",
        "test_patch",
        "fail_to_pass",
        "pass_to_pass",
        "test_groups",
        "hidden_patches",
    }
    assert "FAIL_TO_PASS" not in task.agent_payload()
    assert "fail_to_pass" not in task.agent_payload()
    assert "pass_to_pass" not in task.agent_payload()
    assert "test_groups" not in task.agent_payload()
    assert "hidden_patches" not in task.agent_payload()
    assert prediction == {
        "instance_id": "astropy__astropy-12907",
        "model_name_or_path": "securebench-agent",
        "model_patch": "diff --git ...",
    }
