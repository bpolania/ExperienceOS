"""Deterministic loader and validator for the transition-verification
annotation corpus.

Read-only and offline: it parses the committed annotation files, enforces
the record contract and cross-record invariants, and (via ``build_manifest``)
produces a reproducible manifest. It is intentionally decoupled from any
runtime transition code — validating annotations must never import or
execute experience-management behavior.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CORPUS_ROOT = REPO_ROOT / "benchmarks/annotations/transition-verification"

HISTORICAL_SCORED = CORPUS_ROOT / "historical-scored.jsonl"
DEVELOPMENT_FIXTURES = CORPUS_ROOT / "development-fixtures.jsonl"
UNRESOLVED_CANDIDATES = CORPUS_ROOT / "unresolved-candidates.jsonl"
SCHEMA_PATH = CORPUS_ROOT / "schema.json"
MANIFEST_PATH = CORPUS_ROOT / "manifest.json"

CORPUS_FILES = (
    "historical-scored.jsonl",
    "development-fixtures.jsonl",
    "unresolved-candidates.jsonl",
)

ANNOTATION_FORMAT_VERSION = "1"

CLASSIFICATIONS = frozenset(
    {"historical_scored", "development_only", "historical_unresolved", "excluded"}
)

# The contract's 14-class transition vocabulary (docs/transition_verification_contract.md §3).
PRIMARY_TYPES = frozenset({
    "create_new", "duplicate_noop", "semantic_duplicate_noop",
    "supersede_existing", "scoped_coexistence", "forget_existing",
    "reject_forget_directive_as_creation", "reject_unsupported",
    "reject_ambiguous", "reject_temporary", "reject_question",
    "reject_hypothetical", "reject_unrelated", "shadow_only",
})
REJECTION_TYPES = frozenset(
    t for t in PRIMARY_TYPES if t.startswith("reject_")
)
NON_MUTATING_TYPES = REJECTION_TYPES | {
    "duplicate_noop", "semantic_duplicate_noop"
}

SCORING_CATEGORIES = frozenset({
    "exact_duplicate", "semantic_duplicate", "direct_replacement",
    "instead_of_replacement", "used_to_now_replacement", "correction",
    "repeated_correction", "current_state_replacement", "instruction_replacement",
    "update_target", "supersession", "scoped_coexistence", "forget_directive",
    "forget_as_creation_prevention", "negative_forget", "forget_question",
    "memory_inspection", "broad_forget", "ambiguous_forget", "temporary_exception",
    "historical_statement", "hypothetical", "unrelated_preservation",
    "unsupported_transition", "ambiguous_transition", "stale_leakage",
    "inactive_contamination", "forgotten_leakage", "superseded_leakage",
    "current_value_preservation", "lineage", "creation", "rejection", "no_op",
})

_ID_RE = re.compile(r"^transition:[a-z0-9-]+:[A-Za-z0-9_.-]+:[a-z0-9_]+$")
_PERSONAL_PATH_RE = re.compile(r"/Users/|/home/[^/\s]+/|[A-Za-z]:\\\\Users\\\\")
_SECRET_RE = re.compile(r"(?i)(api[_-]?key|secret|password|bearer\s|sk-[a-z0-9]{8})")

_REQUIRED_TOP_FIELDS = (
    "case_id", "annotation_format_version", "annotation_classification",
    "benchmark_scored", "development_only", "source_family", "source_case_id",
    "source_paths", "oracle_origin", "ambiguity", "scoring_categories",
    "before_state", "expected_transition", "notes",
)


class AnnotationError(ValueError):
    """A transition annotation record or file is invalid."""


def _read_jsonl(path: Path) -> list:
    if not path.exists():
        raise AnnotationError(f"corpus file missing: {path}")
    out = []
    for i, line in enumerate(path.read_text().splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except ValueError as exc:
            raise AnnotationError(f"{path.name} line {i + 1}: {exc}")
    return out


def load_corpus() -> dict:
    return {
        "historical_scored": _read_jsonl(HISTORICAL_SCORED),
        "development_fixtures": _read_jsonl(DEVELOPMENT_FIXTURES),
        "unresolved_candidates": _read_jsonl(UNRESOLVED_CANDIDATES),
    }


def _refs(block) -> list:
    return block or []


def _lid(ref) -> str | None:
    return ref.get("logical_id") if isinstance(ref, dict) else None


def _validate_record(rec: dict, partition: str, seen_ids: set) -> None:
    cid = rec.get("case_id", "<no-id>")
    for field in _REQUIRED_TOP_FIELDS:
        if field not in rec:
            raise AnnotationError(f"{cid}: missing required field {field!r}")
    if rec["annotation_format_version"] != ANNOTATION_FORMAT_VERSION:
        raise AnnotationError(f"{cid}: unsupported format version")
    if cid in seen_ids:
        raise AnnotationError(f"duplicate case_id: {cid}")
    seen_ids.add(cid)
    if not _ID_RE.match(cid):
        raise AnnotationError(f"{cid}: id does not match the deterministic format")

    cls = rec["annotation_classification"]
    if cls not in CLASSIFICATIONS:
        raise AnnotationError(f"{cid}: invalid classification {cls!r}")

    # flag/classification consistency
    scored = rec["benchmark_scored"]
    dev = rec["development_only"]
    if cls == "historical_scored" and not (scored and not dev):
        raise AnnotationError(f"{cid}: historical_scored must be scored, not dev")
    if cls == "development_only" and not (dev and not scored):
        raise AnnotationError(f"{cid}: development_only must be dev, not scored")
    if cls in ("historical_unresolved", "excluded") and scored:
        raise AnnotationError(f"{cid}: {cls} must not be benchmark_scored")
    if dev and scored:
        raise AnnotationError(f"{cid}: cannot be both development_only and scored")

    # partition ↔ classification agreement (mechanical separation)
    expected_partition = {
        "historical_scored": "historical_scored",
        "development_only": "development_fixtures",
        "historical_unresolved": "unresolved_candidates",
        "excluded": "unresolved_candidates",
    }[cls]
    if partition != expected_partition:
        raise AnnotationError(
            f"{cid}: classification {cls} in wrong file partition {partition}")

    # scoring categories vocabulary
    for cat in rec["scoring_categories"]:
        if cat not in SCORING_CATEGORIES:
            raise AnnotationError(f"{cid}: unknown scoring category {cat!r}")

    # privacy / secret scan on the record text
    blob = json.dumps(rec, ensure_ascii=False)
    if _PERSONAL_PATH_RE.search(blob):
        raise AnnotationError(f"{cid}: personal filesystem path present")
    if _SECRET_RE.search(blob):
        raise AnnotationError(f"{cid}: secret-like material present")

    if cls in ("historical_unresolved", "excluded"):
        _validate_unresolved(rec, cid)
        return

    _validate_scorable(rec, cid, cls)


def _validate_unresolved(rec, cid):
    if rec["expected_transition"] is not None:
        raise AnnotationError(f"{cid}: unresolved/excluded must not carry an oracle")
    res = rec.get("resolution")
    if not isinstance(res, dict) or not res.get("reason", "").strip():
        raise AnnotationError(f"{cid}: unresolved/excluded needs a bounded reason")
    if not rec["source_paths"]:
        raise AnnotationError(f"{cid}: unresolved/excluded needs a source reference")


def _validate_scorable(rec, cid, cls):
    if cls == "historical_scored":
        if not rec["source_paths"]:
            raise AnnotationError(f"{cid}: scored record needs source provenance")
        if rec["oracle_origin"] in (None, "", "not_available"):
            raise AnnotationError(f"{cid}: scored record needs an oracle origin")
        # committed source paths must exist
        for p in rec["source_paths"]:
            if not (REPO_ROOT / p).exists():
                raise AnnotationError(f"{cid}: source path does not exist: {p}")

    et = rec["expected_transition"]
    if et is None:
        raise AnnotationError(f"{cid}: scorable record needs expected_transition")
    primary = et["primary_type"]
    if primary not in PRIMARY_TYPES:
        raise AnnotationError(f"{cid}: primary type {primary!r} not in taxonomy")

    before_lids = {_lid(m["memory_ref"]) for m in rec["before_state"]}
    active_before = {
        _lid(m["memory_ref"]) for m in rec["before_state"]
        if m["lifecycle_state"] == "active"
    }
    created = et.get("created") or []
    superseded = et.get("superseded_refs") or []
    forgotten = et.get("forgotten_refs") or []
    preserved = et.get("preserved_refs") or []
    canon = et.get("canonical_effect")

    # supersession/forget targets must be active in the before-state
    if primary == "supersede_existing":
        if not superseded:
            raise AnnotationError(f"{cid}: supersede_existing needs a superseded target")
        for r in superseded:
            if _lid(r) not in active_before:
                raise AnnotationError(
                    f"{cid}: supersede target {_lid(r)} not active in before-state")
        if not created:
            raise AnnotationError(f"{cid}: supersede_existing needs a replacement create")
    if primary == "forget_existing":
        if not forgotten:
            raise AnnotationError(f"{cid}: forget_existing needs a forget target")
        # forget targets are matched by term in the frozen oracle; require the
        # forgotten set be non-empty and no positive creation is expected
        if created:
            raise AnnotationError(
                f"{cid}: forget_existing must not expect positive creation")

    # preserved IDs must exist in the before-state
    for r in preserved:
        lid = _lid(r)
        if lid is not None and lid not in before_lids:
            raise AnnotationError(f"{cid}: preserved id {lid} not in before-state")

    # created refs must not reuse an existing before-state id
    for c in created:
        cref = c.get("_ref") if isinstance(c, dict) else None
        # created carries no _ref after generation; guard defensively
        if cref and _lid(cref) in before_lids:
            raise AnnotationError(f"{cid}: created id reuses existing before-state id")

    # lifecycle sets must not conflict
    superseded_lids = {_lid(r) for r in superseded}
    forgotten_lids = {_lid(r) for r in forgotten}
    if superseded_lids & forgotten_lids:
        raise AnnotationError(f"{cid}: a memory is both superseded and forgotten")

    # no-op / rejection expectations
    if primary in NON_MUTATING_TYPES:
        if created or superseded or forgotten:
            raise AnnotationError(f"{cid}: {primary} must expect no mutation")
        if canon:
            raise AnnotationError(f"{cid}: {primary} must have canonical_effect false")
    if primary in REJECTION_TYPES and et.get("rejection_reason") in (None, ""):
        raise AnnotationError(f"{cid}: rejection needs a rejection_reason")

    # duplicate / semantic-duplicate must create nothing
    if primary in ("duplicate_noop", "semantic_duplicate_noop"):
        if rec["after_state"].get("created_count", 0) != 0:
            raise AnnotationError(f"{cid}: {primary} must create no active memory")

    # scoped coexistence preserves the existing scoped memory
    if primary == "scoped_coexistence":
        if not preserved:
            raise AnnotationError(f"{cid}: scoped_coexistence must preserve a memory")
        if superseded:
            raise AnnotationError(f"{cid}: scoped_coexistence must not supersede")

    # forget-question / memory-inspection / hypothetical / temporary no mutation
    cats = set(rec["scoring_categories"])
    if "negative_forget" in cats and forgotten:
        raise AnnotationError(f"{cid}: negative_forget must not expect a forget action")
    if "forget_question" in cats and forgotten:
        raise AnnotationError(f"{cid}: forget_question must not expect a forget action")
    if rec["ambiguity"].get("ambiguous") and canon:
        raise AnnotationError(f"{cid}: ambiguous case must not expect a mutation")


def validate_corpus() -> dict:
    """Validate the whole corpus; return summary counts. Raises on any defect."""
    corpus = load_corpus()
    seen: set = set()
    for partition, records in corpus.items():
        for rec in records:
            _validate_record(rec, partition, seen)
    # development fixtures never benchmark-scored (redundant belt-and-suspenders)
    for rec in corpus["development_fixtures"]:
        if rec["benchmark_scored"]:
            raise AnnotationError(f"{rec['case_id']}: development fixture is scored")
    return {
        "historical_scored": len(corpus["historical_scored"]),
        "development_fixtures": len(corpus["development_fixtures"]),
        "unresolved_candidates": len(corpus["unresolved_candidates"]),
        "total": sum(len(v) for v in corpus.values()),
    }


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _contract_commit() -> str:
    """Best-effort git commit of the contract file; 'uncommitted' if unknown."""
    import subprocess
    try:
        out = subprocess.run(
            ["git", "log", "-1", "--format=%H", "--",
             "docs/transition_verification_contract.md"],
            cwd=str(REPO_ROOT), capture_output=True, text=True, check=True)
        return out.stdout.strip() or "uncommitted"
    except Exception:
        return "unknown"


def build_manifest() -> dict:
    """Deterministic manifest of the corpus (no volatile timestamps)."""
    corpus = load_corpus()
    all_records = (corpus["historical_scored"]
                   + corpus["development_fixtures"]
                   + corpus["unresolved_candidates"])
    from collections import Counter
    by_class = Counter(r["annotation_classification"] for r in all_records)
    scorable = [r for r in all_records if r["expected_transition"] is not None]
    by_primary = Counter(
        r["expected_transition"]["primary_type"] for r in scorable)
    by_category = Counter(
        c for r in all_records for c in r["scoring_categories"])
    families = sorted({r["source_family"] for r in all_records})
    complete_before = sum(
        1 for r in scorable if r["before_state"])
    partial_before = sum(
        1 for r in scorable if not r["before_state"])
    return {
        "annotation_format_version": ANNOTATION_FORMAT_VERSION,
        "transition_contract_path": "docs/transition_verification_contract.md",
        "transition_contract_commit": _contract_commit(),
        "corpus_files": {
            name: {"sha256": file_digest(CORPUS_ROOT / name),
                   "records": len(_read_jsonl(CORPUS_ROOT / name))}
            for name in CORPUS_FILES
        },
        "counts_by_classification": dict(sorted(by_class.items())),
        "counts_by_primary_type": dict(sorted(by_primary.items())),
        "counts_by_scoring_category": dict(sorted(by_category.items())),
        "source_families": families,
        "historical_scored": by_class.get("historical_scored", 0),
        "development_only": by_class.get("development_only", 0),
        "historical_unresolved": by_class.get("historical_unresolved", 0),
        "excluded": by_class.get("excluded", 0),
        "complete_before_state": complete_before,
        "partial_before_state": partial_before,
        "manual_adjudication": sum(
            1 for r in all_records if r.get("manual_adjudication")),
        "ambiguous_cases": sum(
            1 for r in all_records if r["ambiguity"].get("ambiguous")),
        "total_records": len(all_records),
        "commands": {
            "validate": "python -m pytest tests/test_transition_verification_annotations.py",
            "manifest": "python -m benchmarks.annotations.transition_verification manifest",
            "verify_manifest": "python -m benchmarks.annotations.transition_verification verify",
        },
    }


def _canonical(data) -> str:
    return json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def write_manifest() -> dict:
    manifest = build_manifest()
    MANIFEST_PATH.write_text(_canonical(manifest))
    return manifest


def verify_manifest() -> bool:
    if not MANIFEST_PATH.exists():
        raise AnnotationError("manifest.json missing")
    committed = json.loads(MANIFEST_PATH.read_text())
    fresh = build_manifest()
    # the contract commit may legitimately advance; compare the rest
    committed_cmp = dict(committed)
    fresh_cmp = dict(fresh)
    committed_cmp.pop("transition_contract_commit", None)
    fresh_cmp.pop("transition_contract_commit", None)
    if committed_cmp != fresh_cmp:
        raise AnnotationError("manifest does not match the corpus")
    return True


def _main(argv=None) -> int:
    import sys
    args = argv if argv is not None else sys.argv[1:]
    cmd = args[0] if args else "validate"
    if cmd == "validate":
        summary = validate_corpus()
        print(f"RESULT: transition annotations valid ({summary['total']} records)")
        return 0
    if cmd == "manifest":
        write_manifest()
        print(f"wrote {MANIFEST_PATH}")
        return 0
    if cmd == "verify":
        validate_corpus()
        verify_manifest()
        print("RESULT: transition annotation manifest verified")
        return 0
    print(f"unknown command: {cmd} (expected validate, manifest, verify)")
    return 2


if __name__ == "__main__":
    raise SystemExit(_main())
