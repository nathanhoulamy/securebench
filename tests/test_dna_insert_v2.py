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
TASK_ID = "terminal-bench/dna-insert"
IMAGE = (
    "alexgshaw/dna-insert@"
    "sha256:4dd8760694e355de85ecf03605cb487ccdb33322f6afad513d2920829baa33b2"
)
SEQUENCES_SHA256 = "aebe50fe8d43bb432925537aeb2be63abce3fcc259a1e04e0a37ce7af8da3da0"
VECTOR_LEFT = "tctagaaataattttgtttaactttaagaaggagatatacatatg"
VECTOR_RIGHT = "agcaagggcgaggagctgttcaccggggtggtgcccatcctggtc"
INSERTION = "agtagattagaagaagaattaagaagaagattaacagaa"
MUTATED_INSERTION = INSERTION[:5] + "c" + INSERTION[6:]
COMPLEMENT = str.maketrans("acgt", "tgca")


def reverse_complement(sequence: str) -> str:
    return sequence.translate(COMPLEMENT)[::-1]


def make_primers(
    *,
    annealed_reverse: str = VECTOR_LEFT[-30:],
    annealed_forward: str = VECTOR_RIGHT[:15],
    insertion: str = INSERTION,
    insertion_split: int = 0,
    forward_header: str = ">forward",
    reverse_header: str = ">reverse",
) -> str:
    reverse_primer = reverse_complement(
        annealed_reverse + insertion[:insertion_split]
    )
    forward_primer = insertion[insertion_split:] + annealed_forward
    return (
        f"{forward_header}\n{forward_primer}\n"
        f"{reverse_header}\n{reverse_primer}\n"
    )


REFERENCE = make_primers()


def compiled_task():
    return load_terminal_task(TASK_ID)


def verify_primers(tmp_path: Path, content: str | bytes):
    task = compiled_task()
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "sequences.fasta").write_text(
        "candidate-modified",
        encoding="utf-8",
    )
    target = workspace / "primers.fasta"
    if isinstance(content, str):
        target.write_text(content, encoding="utf-8")
    else:
        target.write_bytes(content)
    return verify_workspace(
        task,
        workspace,
        tmp_path / "store",
        run_seed="dna-insert-qualification",
    )


def assert_candidate_failure(tmp_path: Path, content: str | bytes, category: str):
    result, _, _ = verify_primers(tmp_path, content)
    assert result.status == "failed", result
    assert result.infrastructure_error is None, result
    assert result.public_diagnostics["failure_categories"] == [category]


def test_dna_insert_row_is_passive_bounded_and_executable():
    task = compiled_task()

    validate_executable_task(task)
    assert task.environment.image == IMAGE
    assert task.environment.workdir == "/app"
    assert len(task.assets) == 1
    asset = task.assets[0]
    assert asset.path == "dna-insert/sequences.fasta"
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


def test_public_and_oracle_sequence_lanes_are_identical_and_stable():
    paths = (
        PACK / "docker" / "dna-insert" / "sequences.fasta",
        PACK / "v2" / "hidden" / "dna-insert" / "oracle" / "sequences.fasta",
    )
    contents = [path.read_bytes() for path in paths]
    assert contents[0] == contents[1]
    assert len(contents[0]) == 7238
    assert hashlib.sha256(contents[0]).hexdigest() == SEQUENCES_SHA256


def test_oracle_derives_the_source_verifiers_exact_insertion_context():
    source = load_module(
        PACK / "hidden" / "dna-insert" / "tests" / "test_outputs.py",
        "dna_insert_source_context",
    )
    oracle = load_module(
        PACK / "v2" / "hidden" / "dna-insert" / "oracle" / "oracle.py",
        "dna_insert_oracle_context",
    )

    assert oracle.VECTOR_LEFT.endswith(source.vector1)
    assert oracle.VECTOR_RIGHT.startswith(source.vector2)
    assert oracle.INSERTION == source.insert


def test_reviewed_reference_passes_real_capture_parser_and_oracle(tmp_path):
    result, candidate, store = verify_primers(tmp_path, REFERENCE)

    assert result.status == "passed", result
    assert result.score == 1.0
    manifest = store.load_candidate(candidate.digest)
    assert manifest.type == "file_bundle"
    assert [entry["id"] for entry in manifest.payload["entries"]] == ["primers"]
    assert "sequences.fasta" not in str(manifest.payload)


@pytest.mark.parametrize(
    "content",
    [
        pytest.param(REFERENCE, id="reference"),
        pytest.param(make_primers(insertion_split=20), id="insert_split_between_primers"),
        pytest.param(
            make_primers(
                forward_header="ignored forward header \x00☃",
                reverse_header="also ignored",
            ),
            id="ignored_non_fasta_headers",
        ),
    ],
)
def test_reference_variants_match_the_original_source_verifier(
    tmp_path,
    content,
):
    candidate = tmp_path / "primers.fasta"
    candidate.write_text(content, encoding="utf-8")
    source = load_module(
        PACK / "hidden" / "dna-insert" / "tests" / "test_outputs.py",
        "dna_insert_source_verifier",
    )
    source.Path = lambda _: candidate
    source.calc_tm_oligotm = primer3_oligotm_v1

    source.test_primers()
    result, _, _ = verify_primers(tmp_path / "v2", content)
    assert result.status == "passed", result


def test_source_case_and_trailing_whitespace_semantics_are_preserved(tmp_path):
    lines = REFERENCE.splitlines()
    normalized = "\r\n".join(
        f"{line} \t" if index % 2 == 0 else f"{line.upper()} \t"
        for index, line in enumerate(lines)
    ) + "\r\n"

    result, _, _ = verify_primers(tmp_path, normalized)

    assert result.status == "passed", result


@pytest.mark.parametrize(
    ("content", "category"),
    [
        pytest.param(REFERENCE + "\n", "invalid_line_count", id="blank_line"),
        pytest.param(
            "\n".join(REFERENCE.splitlines()[:3]),
            "invalid_line_count",
            id="missing_reverse",
        ),
        pytest.param(
            make_primers(insertion="X" + INSERTION[1:]),
            "invalid_forward_primer",
            id="non_dna_forward",
        ),
        pytest.param(
            REFERENCE[:-2] + "X\n",
            "invalid_reverse_primer",
            id="non_dna_reverse",
        ),
        pytest.param('{"verdict":"pass"}', "invalid_line_count", id="structured_verdict"),
        pytest.param(
            make_primers(insertion="\x00" + INSERTION[1:]),
            "invalid_forward_primer",
            id="nul_sequence",
        ),
    ],
)
def test_malformed_and_forged_primer_artifacts_fail(tmp_path, content, category):
    assert_candidate_failure(tmp_path, content, category)


@pytest.mark.parametrize(
    ("content", "category"),
    [
        pytest.param(
            make_primers(insertion=MUTATED_INSERTION),
            "insert_missing",
            id="incomplete_insert",
        ),
        pytest.param(
            make_primers(annealed_forward=VECTOR_RIGHT[:14]),
            "forward_annealing_length",
            id="short_forward_annealing",
        ),
        pytest.param(
            make_primers(annealed_reverse=VECTOR_LEFT[-14:]),
            "reverse_annealing_length",
            id="short_reverse_annealing",
        ),
        pytest.param(
            make_primers(annealed_reverse="a" + VECTOR_LEFT[-29:]),
            "reverse_vector_overlap",
            id="wrong_reverse_overlap",
        ),
        pytest.param(
            make_primers(annealed_forward="t" + VECTOR_RIGHT[1:15]),
            "forward_vector_overlap",
            id="wrong_forward_overlap",
        ),
        pytest.param(
            make_primers(annealed_forward=VECTOR_RIGHT[:24]),
            "forward_tm_out_of_range",
            id="high_forward_tm",
        ),
        pytest.param(
            make_primers(annealed_reverse=VECTOR_LEFT[-29:]),
            "reverse_tm_out_of_range",
            id="low_reverse_tm",
        ),
        pytest.param(
            make_primers(annealed_forward=VECTOR_RIGHT[:23]),
            "primer_pair_tm_mismatch",
            id="pair_tm_difference",
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
        compiled_task(),
        candidate,
        store,
        run_seed="dna-insert-replay",
    )

    assert first.status == second.status == "passed"
    assert first.candidate_digest == second.candidate_digest == candidate.digest


@DOCKER_INTEGRATION
@pytest.mark.parametrize(
    ("content", "expected_status"),
    [
        pytest.param(REFERENCE, "passed", id="reference"),
        pytest.param(
            make_primers(insertion=MUTATED_INSERTION),
            "failed",
            id="missing_insert",
        ),
        pytest.param('{"verdict":"pass"}', "failed", id="forged_verdict"),
        pytest.param(
            make_primers(annealed_forward=VECTOR_RIGHT[:23]),
            "failed",
            id="tm_pair_mutant",
        ),
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
        run_seed=f"dna-insert-pinned-{expected_status}",
    )

    assert result.status == expected_status, result
    assert result.infrastructure_error is None, result
