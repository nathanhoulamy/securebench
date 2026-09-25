from __future__ import annotations

import json
from pathlib import Path

import pytest

from securebench.execution_profiles import validate_executable_task
from securebench.schemas.benchmark import ArtifactCheck, FileBundleCandidate
from securebench.verification import VerificationEngine
from tests.qualification_support import (
    DOCKER_INTEGRATION,
    assert_base_capture_rejected,
    assert_file_bundle_capture_rejected,
    assert_missing_candidate_failure,
    load_module,
    load_terminal_task,
    verify_command_candidate,
    verify_workspace,
)


ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "benchmarks" / "terminal-bench"
TASK_ID = "terminal-bench/protein-assembly"
IMAGE = "alexgshaw/protein-assembly@sha256:94de701b57e7ecfdbada6044f8534876e4b58874f8f313184dadc4d7533e0818"
HIDDEN = PACK / "v2" / "hidden" / "protein-assembly"
ORACLE = HIDDEN / "oracle" / "oracle.py"
REFERENCE = HIDDEN / "qualification" / "reference.txt"
SOURCE_VERIFIER = PACK / "hidden" / "protein-assembly" / "tests" / "test_outputs.py"


def compiled_task():
    return load_terminal_task(TASK_ID)


def oracle_module():
    return load_module(ORACLE, "protein_assembly_oracle_under_test")


def reference_gblock() -> str:
    assert REFERENCE.is_file(), f"missing host-only reference material: {REFERENCE}"
    return REFERENCE.read_text(encoding="utf-8").strip()


def verify_gblock(tmp_path: Path, content: str | bytes):
    task = compiled_task()
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "design.log").write_text("excluded", encoding="utf-8")
    target = workspace / "gblock.txt"
    if isinstance(content, bytes):
        target.write_bytes(content)
    else:
        target.write_text(content, encoding="utf-8")
    return verify_workspace(
        task, workspace, tmp_path / "store", run_seed="protein-assembly-test-seed"
    )


def assert_candidate_failure(tmp_path: Path, content: str | bytes, category: str):
    result, _, _ = verify_gblock(tmp_path, content)

    assert result.status == "failed", result
    assert result.score == 0.0
    assert result.infrastructure_error is None, result
    assert category in result.public_diagnostics["failure_categories"], result
    return result


def test_protein_assembly_row_is_bounded_split_and_executable():
    task = compiled_task()
    validate_executable_task(task)

    assert task.environment.image == IMAGE
    assert task.environment.workdir == "/app"
    # The public task names the RCSB PDB and FPbase APIs explicitly.
    assert task.environment.agent_network.mode == "restricted"
    assert task.environment.agent_network.allowed_domains == (
        "rcsb.org",
        "fpbase.org",
        "pypi.org",
        "pythonhosted.org",
    )

    candidate = task.verification.candidate
    assert isinstance(candidate, FileBundleCandidate)
    assert [entry.id for entry in candidate.files] == ["gblock"]
    assert candidate.files[0].path == "/app/gblock.txt"

    (check,) = task.verification.checks
    assert isinstance(check, ArtifactCheck)
    assert check.id == "gblock_artifact"
    assert check.artifacts[0].parser == "securebench.utf8-text/v1"

    assert task.verification.oracle == "host.task_oracle"
    for role in ("agent", "evaluation_runtime"):
        view = str(task.view_for(role))
        assert "oracle" not in view
        assert "qualification" not in view
        assert "DYKDDDDK" not in view


def test_oracle_segments_match_the_source_verifier_exactly():
    module = oracle_module()
    source = SOURCE_VERIFIER.read_text(encoding="utf-8")

    for name in ("FLAG", "DONOR", "DHFR", "ACCEPTOR", "SNAP"):
        sequence = module.SEGMENTS[name]
        assert f'"{sequence}"' in source, f"{name} does not match the source verifier"

    assert module.ORDER == ["FLAG", "DONOR", "DHFR", "ACCEPTOR", "SNAP"]
    assert module.MAX_NUCLEOTIDES == 3000
    assert (module.MIN_LINKER, module.MAX_LINKER) == (5, 20)
    assert (module.MIN_WINDOW_GC, module.MAX_WINDOW_GC, module.WINDOW) == (15, 35, 50)


def test_oracle_translation_matches_the_standard_genetic_code():
    module = oracle_module()

    assert len(module.CODON_TABLE) == 64
    assert module.translate("atgaaataa") == "MK*"
    assert module.translate("atg") == "M"
    # A trailing partial codon is ignored, matching Bio.Seq.translate().
    assert module.translate("atgaa") == "M"
    assert module.translate("tgg") == "W"
    assert module.translate("tga") == "*"


def test_reviewed_reference_passes_real_capture_parser_and_oracle(tmp_path):
    gblock = reference_gblock()
    assert len(gblock) <= 3000

    result, candidate, store = verify_gblock(tmp_path, gblock + "\n")

    assert result.status == "passed", result
    assert result.score == 1.0
    manifest = store.load_candidate(candidate.digest)
    assert [entry["id"] for entry in manifest.payload["entries"]] == ["gblock"]
    assert "design.log" not in json.dumps(manifest.payload)


@pytest.mark.parametrize(
    ("transform", "reason"),
    [
        pytest.param(lambda g: g, "no trailing newline", id="no_trailing_newline"),
        pytest.param(lambda g: g + "\n", "one trailing newline", id="trailing_newline"),
        pytest.param(lambda g: g.upper(), "the source lowercases first", id="uppercase"),
        pytest.param(
            lambda g: g + "   \n", "the source rstrips each line", id="trailing_spaces"
        ),
    ],
)
def test_source_line_handling_is_preserved(tmp_path, transform, reason):
    result, _, _ = verify_gblock(tmp_path, transform(reference_gblock()))

    assert result.status == "passed", f"{reason}: {result}"


@pytest.mark.parametrize(
    ("transform", "category"),
    [
        pytest.param(
            lambda g: g + "\nextra", "invalid_line_count", id="second_line"
        ),
        pytest.param(
            lambda g: "\n" + g, "invalid_line_count", id="leading_blank_line"
        ),
        pytest.param(
            lambda g: g + "\n\n", "invalid_line_count", id="two_trailing_newlines"
        ),
        pytest.param(
            lambda g: g.replace("a", "n", 1),
            "invalid_nucleotide_alphabet",
            id="non_nucleotide_character",
        ),
        pytest.param(
            lambda g: g + "atg", "gblock_does_not_end_with_snap", id="trailing_codon"
        ),
        pytest.param(
            lambda g: "atg" + g,
            "gblock_does_not_start_with_flag",
            id="leading_start_codon",
        ),
        pytest.param(
            lambda g: g[3:], "missing_segment", id="frame_shifted_by_one_codon"
        ),
        pytest.param(lambda g: g[1:], "missing_segment", id="frame_shifted_by_one_base"),
        pytest.param(
            # An in-frame stop right after FLAG translates to "*", which lands
            # inside the first linker and so fails the pure-[GS] rule.
            lambda g: g[:24] + "taa" + g[24:],
            "linker_not_gs",
            id="in_frame_stop_after_flag",
        ),
    ],
)
def test_targeted_semantic_mutants_fail(tmp_path, transform, category):
    assert_candidate_failure(tmp_path, transform(reference_gblock()), category)


def test_linker_length_band_is_enforced_at_both_ends(tmp_path):
    """Linkers must be 5..20 aa; 4 and 21 are the first rejected values."""
    module = oracle_module()
    reference_path = HIDDEN / "qualification" / "build_reference.py"
    builder = load_module(reference_path, "protein_assembly_reference_builder")

    for linker, category in (
        ("GGGG", "linker_length_out_of_range"),
        ("G" * 21, "linker_length_out_of_range"),
        ("GGAGS", "linker_not_gs"),
    ):
        protein = linker.join(module.SEGMENTS[name] for name in module.ORDER)
        gblock = builder.reverse_translate(protein)
        assert module.ProteinAssemblyOracle()._check(gblock + "\n") == category, linker

    # The inclusive bounds themselves are accepted. A 20-aa linker must mix in
    # serine: glycine codons are all >= 2/3 GC, so a poly-glycine linker of that
    # length pushes the 50-nucleotide window past the 70% GC ceiling. That is a
    # real interaction between two source constraints, not a converter artifact.
    for linker in ("GGGGG", "GS" * 10):
        protein = linker.join(module.SEGMENTS[name] for name in module.ORDER)
        gblock = builder.reverse_translate(protein)
        assert module.ProteinAssemblyOracle()._check(gblock + "\n") == "", linker


def test_gc_window_bound_is_enforced(tmp_path):
    """A GC-extreme stretch must fail even when the protein is correct."""
    module = oracle_module()
    gblock = reference_gblock()
    # Replace one 60-nt stretch with a GC-free run; this breaks both the window
    # bound and the encoded protein, so it must fail closed either way.
    mutated = gblock[:300] + "ataataataa" * 6 + gblock[360:]

    assert module.ProteinAssemblyOracle()._check(mutated + "\n") != ""


@pytest.mark.parametrize(
    ("content", "category"),
    [
        pytest.param(b"\xff\xfe", "invalid_utf8", id="invalid_utf8"),
        pytest.param(b"", "invalid_nucleotide_alphabet", id="empty_file"),
        pytest.param(
            b'{"verdict":"pass","score":1.0}',
            "invalid_nucleotide_alphabet",
            id="forged_verdict",
        ),
        pytest.param(
            b"atg\x00", "invalid_nucleotide_alphabet", id="nul_byte"
        ),
        pytest.param(b"a" * 3001, "gblock_too_long", id="over_length_cap"),
    ],
)
def test_malformed_and_forged_artifacts_fail(tmp_path, content, category):
    assert_candidate_failure(tmp_path, content, category)


@pytest.mark.parametrize("attack", ["symlink", "directory", "oversized"])
def test_malicious_candidate_filesystem_shapes_are_rejected_at_capture(
    tmp_path, attack
):
    assert_file_bundle_capture_rejected(
        compiled_task(), tmp_path, attack=attack, target_id="gblock"
    )


def test_missing_deliverable_scores_as_candidate_failure():
    assert_missing_candidate_failure(
        compiled_task(),
        run_seed="protein-assembly-missing",
        check_ids=("gblock_artifact",),
    )


def test_stored_candidate_replays_exactly_without_cross_run_state(tmp_path):
    first, candidate, store = verify_gblock(tmp_path, reference_gblock() + "\n")
    second = VerificationEngine().verify(
        compiled_task(), candidate, store, run_seed="protein-assembly-replay"
    )

    assert first.status == second.status == "passed"
    assert first.candidate_digest == second.candidate_digest == candidate.digest


@DOCKER_INTEGRATION
def test_base_image_without_deliverable_is_rejected_at_capture(tmp_path):
    assert_base_capture_rejected(compiled_task(), tmp_path, command=("true",))


@DOCKER_INTEGRATION
def test_pinned_image_ships_the_public_design_inputs(tmp_path):
    result, _, _ = verify_command_candidate(
        compiled_task(),
        tmp_path,
        command=(
            "sh",
            "-c",
            "test -f /app/antibody.fasta && test -f /app/plasmid.gb "
            "&& test -f /app/pdb_ids.txt && printf 'atg' > /app/gblock.txt",
        ),
        run_seed="protein-assembly-inputs-present",
    )

    # The stub gBlock fails scoring; the point is that the inputs exist and no
    # infrastructure error occurred.
    assert result.status == "failed", result
    assert result.infrastructure_error is None, result


@DOCKER_INTEGRATION
def test_pinned_agent_capture_and_verification(tmp_path):
    gblock = reference_gblock()
    result, _, _ = verify_command_candidate(
        compiled_task(),
        tmp_path,
        command=("sh", "-c", f"printf '%s\\n' '{gblock}' > /app/gblock.txt"),
        run_seed="protein-assembly-pinned-reference",
    )

    assert result.status == "passed", result
    assert result.infrastructure_error is None, result
