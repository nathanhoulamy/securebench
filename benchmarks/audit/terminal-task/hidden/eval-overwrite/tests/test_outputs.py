from pathlib import Path


def test_candidate_workspace_eval_input_copy_is_not_trusted():
    evaluator = Path(__file__).resolve().parents[1]
    assert (evaluator / "checker-data.txt").read_text() == "trusted-marker\n"
