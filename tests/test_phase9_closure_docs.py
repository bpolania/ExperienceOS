"""Phase 9 Prompt 10: final documentation consistency tests."""

import re
from pathlib import Path

README = Path("README.md").read_text()
CLOSURE = Path("docs/phase9_closure.md").read_text()
REPORT_V2 = Path("docs/benchmark_report_v2.md").read_text()

DIGESTS = (
    "8b0e245d914a43bc578923111e8ff40e70d9c8aa487664c00125fc52fa319b33",
    "ee437bb3e9fde909f343112e40aaa6ecf63155a07a81ad67e017e310fbefb547",
    "19b66cacb330e943b0460ccdb33e8cc6577fccb17621cb7a129f7420f5c7868f",
    "3bc955b0c4940ef73a01c4066bff695596fc45cc144f8c850441ed30f5ab76fd",
)


def test_readme_references_final_system_and_report():
    assert "experienceos_hybrid_full_v2" in README
    assert "docs/benchmark_report_v2.md" in README
    assert "docs/phase9_closure.md" in README


def test_readme_carries_required_disclosures():
    lowered = README.lower()
    assert "not an official longmemeval score" in lowered
    assert "scripted-simulated" in lowered
    assert "direct_model_inference: false" in README
    # The selection regression is disclosed, never claimed improved.
    assert "selection rate **fell**" in README
    assert "naive top-k" in lowered
    # Real-local containment framing, not model competence.
    assert "0/15" in README and "0/8" in README
    assert "containment" in lowered


def test_readme_links_resolve():
    for link in re.findall(r"\]\((docs/[^)#]+)\)", README):
        assert Path(link).exists(), link


def test_closure_contains_digests_chain_and_commands():
    for digest in DIGESTS:
        assert digest in CLOSURE, digest
    for commit in ("abf4edd", "a73cea4", "1e166d7", "25fa1d2", "05dd00d",
                   "0a2a3a6", "6997e91", "f8c2815", "315c017"):
        assert commit in CLOSURE, commit
    assert "validate-report-v2" in CLOSURE
    assert "Phase 9 is closed" in CLOSURE


def test_no_prohibited_claims_in_final_docs():
    for text, name in ((README, "README"), (CLOSURE, "closure")):
        lowered = text.lower()
        assert "official longmemeval score" not in lowered.replace(
            "not an official longmemeval score", ""
        ), name
        assert "state-of-the-art" not in lowered, name
        # Scripted mode is never presented as real inference.
        assert "real local-model performance" not in lowered, name


def test_v1_report_untouched_and_v2_report_present():
    v1 = Path("docs/benchmark_report.md")
    assert v1.exists()
    assert "hybrid_full_v2" not in v1.read_text()  # v1 stays historical
    assert "experienceos_hybrid_full_v2" in REPORT_V2


def test_full_v2_system_still_registered():
    from benchmarks.adapters.factory import create_system

    system = create_system("experienceos_hybrid_full_v2")
    assert system.system_id == "experienceos_hybrid_full_v2"
