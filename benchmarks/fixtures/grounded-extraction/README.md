# Grounded-Extraction Development Fixtures

**Development-only scenarios.** These cases exist for extractor
design, grounding-validation development, and smoke tests. They are:

- **not held-out evaluation evidence**;
- **not an official benchmark** (and not part of LongMemEval);
- **never to be included in primary result claims**;
- **never consumed by canonical benchmark execution** — loaders must
  opt in explicitly via
  `benchmarks/fixtures/grounded_extraction.load_development_fixtures`.

Frozen historical evidence under `benchmarks/results/committed/`
remains the sole authority for regression comparison.

## Contents

`cases.jsonl` — 37 deterministic cases (24 positive, 13 negative)
across 17 categories covering durable preferences/facts/instructions,
temporary state, one-off requests, hypotheticals, questions,
assistant-only claims, unsupported normalization, duplicate
restatement, ambiguity, third-party statements, negation/polarity, and
preference change. Every positive case carries an exact evidence span
(`user_message[start:end] == expected_evidence_text`, zero-based,
start-inclusive, end-exclusive) and one or more acceptable normalized
texts; every negative case carries an explicit rejection category.
Cases derived from committed failure evidence cite a bounded
`source_reference` (report/scenario ID); the rest are labeled
`synthetic-development-scenario`.

Duplicate-restatement and preference-change cases deliberately
separate the *proposal expectation* (a valid candidate may be
proposed) from the *later lifecycle expectation*
(`lifecycle_expectation`: duplicate/supersede) — extraction never
owns lifecycle decisions.

## Governing rules

Schema, offsets, durability, provenance, and scoring semantics are
defined by `docs/grounded_extraction_contract.md`. Fixture integrity
is enforced by the loader and by
`tests/test_grounded_extraction_fixtures.py`.
