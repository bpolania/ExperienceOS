"""Deterministic serialization and manifest hashing for benchmark data.

Two forms, both stable across runs and machines:

- ``canonical_json`` — compact, key-sorted JSON used for hashing and
  equality. Equivalent content always produces identical bytes,
  regardless of dict insertion order.
- ``stable_dump`` — human-reviewable, key-sorted, indented JSON used
  for committed fixtures and small evidence artifacts.

``manifest_hash`` fingerprints a dataset manifest so a benchmark run
can prove exactly which cases it executed.
"""

from __future__ import annotations

import hashlib
import json


def canonical_json(data) -> str:
    """Compact, deterministic JSON: sorted keys, fixed separators."""
    return json.dumps(
        data, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def stable_dump(data) -> str:
    """Reviewable, deterministic JSON for committed artifacts."""
    return json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def manifest_hash(case_payloads: list) -> str:
    """SHA-256 over the canonical JSON of an ordered list of case payloads.

    The list order is part of the manifest: benchmark scenario order is
    deterministic, so reordering cases is a different manifest.
    """
    body = canonical_json({"manifest": list(case_payloads)})
    return hashlib.sha256(body.encode("utf-8")).hexdigest()
