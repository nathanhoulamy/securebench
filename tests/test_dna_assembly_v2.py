from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from securebench.execution_profiles import validate_executable_task
from securebench.schemas.benchmark import ArtifactCheck
from securebench.verification import VerificationEngine
from securebench.verification.oligotm import primer3_oligotm_v1
from tests.qualification_support import (
    DOCKER_INTEGRATION,
    load_module,
    load_terminal_task,
    verify_command_candidate,
    verify_workspace,
)


ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "benchmarks" / "terminal-bench"
TASK_ID = "terminal-bench/dna-assembly"
IMAGE = (
    "alexgshaw/dna-assembly@"
    "sha256:d1adf6835f1dd91205ba70e452c699d0aea601010038e5617f370716efb50569"
)
SEQUENCES_SHA256 = "ebdc361b5fba28eb0a2c7a8a8a444ccb12cc842c8cbc6df5a2c24254f130736f"
REFERENCE = """>input_fwd
ggctacggtctcagggttaatgaggatcccgggaattc
>input_rev
ggctacggtctcatcatatgtatatctccttcttaaagttaaac
>egfp_fwd
ggctacggtctcaatgagcaagggcgaggagctg
>egfp_rev
ggctacggtctcactttgtacagctcgtccatgcc
>flag_fwd
ggctacggtctcaaaaggtagtggctccggtagc
>flag_rev
ggctacggtctcatgtctgaaccactacctgaaccag
>snap_fwd
ggctacggtctcagacaaagactgcgaaatgaagcg
>snap_rev
ggctacggtctcaacccagcccaggcttacc
"""


def compiled_task():
    return load_terminal_task(TASK_ID)


def verify_primers(tmp_path: Path, content: str | bytes):
    task = compiled_task()
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "sequences.fasta").write_text("candidate-modified", encoding="utf-8")
    target = workspace / "primers.fasta"
    if isinstance(content, str):
        target.write_text(content, encoding="utf-8")
    else:
        target.write_bytes(content)
    return verify_workspace(
        task,
        workspace,
        tmp_path / "store",
        run_seed="dna-assembly-qualification",
    )


def primer_value(content: str, name: str) -> str:
    lines = content.splitlines()
    return lines[lines.index(f">{name}") + 1]


def replace_primer(content: str, name: str, value: str) -> str:
    lines = content.splitlines()
    lines[lines.index(f">{name}") + 1] = value
    return "\n".join(lines) + "\n"


def set_binding(primer: str, binding: str) -> str:
    site = primer.index("ggtctc")
    binding_start = site + len("ggtctc") + 5
    return primer[:binding_start] + binding


def set_overhang(primer: str, overhang: str) -> str:
    site = primer.index("ggtctc")
    overhang_start = site + len("ggtctc") + 1
    return primer[:overhang_start] + overhang + primer[overhang_start + 4 :]


def mutate_primer(content: str, name: str, transform) -> str:
    return replace_primer(content, name, transform(primer_value(content, name)))


def duplicate_junction_overhang(content: str) -> str:
    vector_right = "tcat"
    content = mutate_primer(content, "egfp_rev", lambda value: set_overhang(value, vector_right))
    return mutate_primer(content, "flag_fwd", lambda value: set_overhang(value, "atga"))


def change_closed_junction(content: str) -> str:
    content = mutate_primer(content, "input_fwd", lambda value: set_overhang(value, "ggga"))
    return mutate_primer(content, "snap_rev", lambda value: set_overhang(value, "tccc"))


def mismatch_input_pair_tm(content: str) -> str:
    content = mutate_primer(
        content,
        "input_fwd",
        lambda value: set_binding(value, "taatgaggatcccgggaa"),
    )
    return mutate_primer(
        content,
        "input_rev",
        lambda value: set_binding(
            value,
            "agactgatcatatgtatatctccttcttaaagttaaac",
        ),
    )


def assert_candidate_failure(tmp_path: Path, content: str | bytes, category: str):
    result, _, _ = verify_primers(tmp_path, content)
    assert result.status == "failed", result
    assert result.infrastructure_error is None, result
    assert result.public_diagnostics["failure_categories"] == [category]


def test_dna_assembly_row_is_passive_bounded_and_executable():
    task = compiled_task()

    validate_executable_task(task)
    assert task.environment.image == IMAGE
    assert task.environment.workdir == "/app"
    assert len(task.assets) == 1
    asset = task.assets[0]
    assert asset.path == "dna-assembly/sequences.fasta"
    assert asset.mount == "/app/sequences.fasta"
    assert asset.read_only is True
    assert len(task.verification.checks) == 1
    check = task.verification.checks[0]
    assert isinstance(check, ArtifactCheck)
    assert check.artifacts[0].parser == "securebench.utf8-text/v1"
    assert not task.verification.resources.runtime
    assert task.verification.candidate.max_total_files == 1
    assert task.verification.candidate.max_total_bytes == 65536
    entry = task.verification.candidate.files[0]
    assert entry.id == "primers"
    assert entry.path == "/app/primers.fasta"
    assert entry.max_bytes == 65536

    oracle_root = Path(task.resources.resources["host.task_oracle"].value["source_path"])
    assert {
        path.relative_to(oracle_root).as_posix()
        for path in oracle_root.rglob("*")
        if path.is_file()
    } == {"oracle.py", "oracle.yaml", "sequences.fasta"}


def test_checked_in_sequence_lanes_are_identical_and_stable():
    paths = (
        PACK / "docker" / "dna-assembly" / "sequences.fasta",
        PACK / "assets" / "dna-assembly" / "sequences.fasta",
        PACK / "v2" / "hidden" / "dna-assembly" / "oracle" / "sequences.fasta",
    )
    contents = [path.read_bytes() for path in paths]
    assert contents[0] == contents[1] == contents[2]
    assert len(contents[0]) == 7712
    assert hashlib.sha256(contents[0]).hexdigest() == SEQUENCES_SHA256


def test_reviewed_reference_passes_real_capture_parser_and_oracle(tmp_path):
    result, candidate, store = verify_primers(tmp_path, REFERENCE)

    assert result.status == "passed", result
    assert result.score == 1.0
    manifest = store.load_candidate(candidate.digest)
    assert manifest.type == "file_bundle"
    assert [entry["id"] for entry in manifest.payload["entries"]] == ["primers"]
    assert "sequences.fasta" not in str(manifest.payload)


def test_reference_matches_the_source_fragment_and_assembly_semantics():
    source = load_module(
        PACK / "hidden" / "dna-assembly" / "tests" / "test_outputs.py",
        "dna_assembly_source_verifier",
    )
    source.calc_tm = primer3_oligotm_v1
    primers = {
        name: primer_value(REFERENCE, name).lower() for name in (
            "input_fwd",
            "input_rev",
            "egfp_fwd",
            "egfp_rev",
            "flag_fwd",
            "flag_rev",
            "snap_fwd",
            "snap_rev",
        )
    }

    vector = source.make_fragment(
        source.vector, primers["input_fwd"], primers["input_rev"], circular=True
    )
    egfp = source.make_fragment(source.egfp, primers["egfp_fwd"], primers["egfp_rev"])
    flag = source.make_fragment(source.flag, primers["flag_fwd"], primers["flag_rev"])
    snap = source.make_fragment(source.snap, primers["snap_fwd"], primers["snap_rev"])
    assert egfp[0] == source.rc(vector[2])
    assert flag[0] == source.rc(egfp[2])
    assert snap[0] == source.rc(flag[2])
    assert vector[0] == source.rc(snap[2])
    assert len({vector[2], egfp[2], flag[2], snap[2]}) == 4
    assembled = vector[0] + vector[1] + egfp[0] + egfp[1] + flag[0] + flag[1] + snap[0] + snap[1]
    assert assembled in source.output + source.output


def test_source_case_and_trailing_whitespace_semantics_are_preserved(tmp_path):
    lines = REFERENCE.splitlines()
    normalized = "\r\n".join(
        f"{line} \t" if line.startswith(">") else f"{line.upper()} \t"
        for line in lines
    ) + "\r\n"

    result, _, _ = verify_primers(tmp_path, normalized)

    assert result.status == "passed", result


@pytest.mark.parametrize(
    ("content", "category"),
    [
        pytest.param(REFERENCE + "\n", "invalid_line_count", id="blank_line"),
        pytest.param(
            REFERENCE.replace(">input_fwd", "input_fwd", 1),
            "invalid_primer_header",
            id="missing_header_marker",
        ),
        pytest.param(
            REFERENCE.replace("ggctac", "Xgctac", 1),
            "invalid_primer_sequence",
            id="non_dna_character",
        ),
        pytest.param(
            REFERENCE.replace(">input_fwd", ">verdict", 1),
            "missing_required_primer",
            id="forged_header",
        ),
        pytest.param('{"verdict":"pass"}', "invalid_line_count", id="structured_verdict"),
        pytest.param(
            REFERENCE.replace("ggctac", "ggc\x00ac", 1),
            "invalid_primer_sequence",
            id="nul_character",
        ),
    ],
)
def test_malformed_and_forged_primer_artifacts_fail(tmp_path, content, category):
    assert_candidate_failure(tmp_path, content, category)


@pytest.mark.parametrize(
    ("content", "category"),
    [
        pytest.param(
            mutate_primer(
                REFERENCE,
                "input_fwd",
                lambda value: value.replace("ggtctc", "ggtctt", 1),
            ),
            "missing_bsai_site",
            id="missing_bsai_site",
        ),
        pytest.param(
            mutate_primer(REFERENCE, "input_fwd", lambda value: value[value.index("ggtctc") :]),
            "missing_bsai_clamp",
            id="missing_clamp",
        ),
        pytest.param(
            replace_primer(REFERENCE, "input_fwd", "aggtctcaaaaa"),
            "incomplete_bsai_primer",
            id="incomplete_primer",
        ),
        pytest.param(
            mutate_primer(REFERENCE, "input_fwd", lambda value: set_binding(value, "a" * 15)),
            "forward_binding_site_missing",
            id="unknown_forward_binding",
        ),
        pytest.param(
            mutate_primer(REFERENCE, "input_rev", lambda value: set_binding(value, "a" * 15)),
            "reverse_binding_site_missing",
            id="unknown_reverse_binding",
        ),
        pytest.param(
            mutate_primer(
                REFERENCE,
                "input_fwd",
                lambda value: set_binding(value, primer_value(REFERENCE, "input_fwd")[-21:][:5]),
            ),
            "forward_annealing_length",
            id="short_forward_annealing",
        ),
        pytest.param(
            mutate_primer(
                REFERENCE,
                "input_rev",
                lambda value: set_binding(value, primer_value(REFERENCE, "input_rev")[-5:]),
            ),
            "reverse_annealing_length",
            id="short_reverse_annealing",
        ),
        pytest.param(
            mutate_primer(
                REFERENCE,
                "input_fwd",
                lambda value: set_binding(value, primer_value(REFERENCE, "input_fwd")[-21:][:15]),
            ),
            "forward_tm_out_of_range",
            id="low_forward_tm",
        ),
        pytest.param(
            mutate_primer(
                REFERENCE,
                "input_rev",
                lambda value: set_binding(value, primer_value(REFERENCE, "input_rev")[-15:]),
            ),
            "reverse_tm_out_of_range",
            id="low_reverse_tm",
        ),
        pytest.param(
            mismatch_input_pair_tm(REFERENCE),
            "primer_pair_tm_mismatch",
            id="pair_tm_difference",
        ),
        pytest.param(
            mutate_primer(REFERENCE, "egfp_fwd", lambda value: set_overhang(value, "cccc")),
            "vector_egfp_overhang_mismatch",
            id="junction_mismatch",
        ),
        pytest.param(
            duplicate_junction_overhang(REFERENCE),
            "duplicate_junction_overhang",
            id="duplicate_junction",
        ),
        pytest.param(
            change_closed_junction(REFERENCE),
            "assembled_sequence_mismatch",
            id="incorrect_circular_assembly",
        ),
    ],
)
def test_targeted_semantic_mutants_fail(tmp_path, content, category):
    assert_candidate_failure(tmp_path, content, category)


def test_invalid_utf8_is_candidate_evidence_not_infrastructure(tmp_path):
    assert_candidate_failure(tmp_path, REFERENCE.encode() + b"\xff", "invalid_utf8")


def test_stored_candidate_replays_exactly_without_cross_run_state(tmp_path):
    first, candidate, store = verify_primers(tmp_path, REFERENCE)
    second = VerificationEngine().verify(
        compiled_task(), candidate, store, run_seed="dna-assembly-replay"
    )

    assert first.status == second.status == "passed"
    assert first.candidate_digest == second.candidate_digest == candidate.digest


@DOCKER_INTEGRATION
@pytest.mark.parametrize(
    ("content", "expected_status"),
    [
        pytest.param(REFERENCE, "passed", id="reference"),
        pytest.param(
            mutate_primer(
                REFERENCE,
                "input_fwd",
                lambda value: value.replace("ggtctc", "ggtctt", 1),
            ),
            "failed",
            id="missing_bsai_site",
        ),
        pytest.param('{"verdict":"pass"}', "failed", id="forged_verdict"),
        pytest.param(change_closed_junction(REFERENCE), "failed", id="assembly_mutant"),
    ],
)
def test_pinned_agent_capture_and_replay_matrix(tmp_path, content, expected_status):
    task = compiled_task()
    command = (
        "sh",
        "-c",
        'printf "%s" "$1" > /app/primers.fasta',
        "securebench",
        content,
    )
    result, _, _ = verify_command_candidate(
        task,
        tmp_path,
        command=command,
        run_seed=f"dna-assembly-pinned-{expected_status}",
    )

    assert result.status == expected_status, result
    assert result.infrastructure_error is None, result
