# Dashboard Retrieval Diagnostics (Phase 11, Prompt 8)

The Streamlit demo (`demo/app.py`) now exposes the Phase 11 retrieval
evidence in a **"Retrieval diagnostics (Phase 11)"** subsection
directly under the existing "Context selection (last turn)" panel,
plus a collapsed **"Phase 11 benchmark summary (committed evidence)"**
expander. The dashboard reads recorded evidence only: it never
constructs providers, loads models, touches the network, recomputes
retrieval or benchmarks, or mutates memory.

## Evidence plumbing

Two additive changes carry the existing diagnostics into events:
`ContextSelectionRecord` gained `semantic`/`fusion`/`gate` fields
(copied from the retrieval candidates; `None` on legacy paths), and
`ContextBuildResult`/the `CONTEXT_BUILT` payload gained a bounded
`retrieval_diagnostics` dict (mode, semantic summary incl. provider/
cache/fallback, gate summary, eligibility counts). Old events without
these keys render exactly as before.

## Retrieval summary

From the last `CONTEXT_BUILT` event, via
`demo/support.py:retrieval_diagnostics`: retrieval mode, embedding
provider/model/dimensions with availability, semantic floor, fusion
profile, fallback state (`No fallback` / sanitized reason +
`lexical_reference` path), eligible and lifecycle-excluded counts,
budget compliance, cache counters, and gate status. Guarded defaults
(`No retrieval event yet`, `Disabled`, `—`) — absent evidence is never
rendered as success. The deterministic provider is always labeled
"deterministic test provider: plumbing evidence, not learned semantic
quality."

## Lifecycle authority notice

Displayed verbatim above the diagnostics
(`LIFECYCLE_AUTHORITY_NOTICE`):

> Lifecycle rules are applied before semantic scoring. Embeddings and
> the shadow gate can rank or propose, but they cannot reactivate
> forgotten experience, override supersession, or bypass the context
> budget.

## Candidate table and detail

`phase11_candidate_rows` extends the canonical audit order (never
re-sorted, reasons never altered) with Semantic/Fused/Evidence/Cache/
Shadow-gate columns. Exclusions are classified by authority level
(`exclusion_kind`): **Lifecycle exclusion (authoritative)** (the
`inactive_*` reasons) is displayed distinctly from relevance
exclusions (`zero_relevance`, `below_semantic_floor`,
`no_fused_evidence`), candidate-limit exclusions, ranking skips
(`not_top_k`), and token-budget skips. Forgotten/superseded records
show `—` for every semantic/gate column — they were never embedded or
gated. A "Per-candidate score breakdowns" expander shows the full
bounded detail (`candidate_detail`): canonical status, raw component
scores, semantic evidence (provider, cosine, floor, cache status),
the reconstructable fusion breakdown (raw/normalized/weights/
contributions/ranks/delta), and gate evidence. No vectors, cache
contents, paths, or stack traces appear anywhere.

## Shadow-gate wording

Gate proposals always carry the shadow qualifier: `Shadow: Reject`
next to `Canonical result: Selected`, `Affected selection: No`, and
the summary line ends with "Proposals did not change context". A
failed evaluation renders as `Shadow eval failed (contained)` with the
exception type name only. Gate-disabled events show `Shadow gate:
Disabled`; pre-Phase 11 events show no gate block.

## Benchmark summary

`phase11_benchmark_summary` reads the committed
`benchmarks/results/committed/report-phase11/report_data_phase11.json`
and `adoption_gates_phase11.json` (small validated artifacts — no
JSONL scanning, no regeneration, no metric duplication): reference
12/50 MRR 0.305 @5,527 tokens; embedding-only 2/50; fused 13/50 MRR
0.293 @5,448; classifications (not_adopted / experimental /
experimental); leakage zero; gate affected selection 0; the
deterministic-provider and no-official-LongMemEval disclosures; and a
pointer to `docs/phase11_semantic_retrieval_report.md`. Missing or
malformed artifacts render "Benchmark summary unavailable" and never
crash.

## Compatibility, reset, and safety

Phase 8/9 events, partial Phase 11 payloads, malformed optional
fields, empty state, and reset all render safely (tested at helper
level and via Streamlit AppTest, which is available in this
environment: initial render, chat turn, reset click, benchmark
expander). Import/monkeypatch tests prove `demo.support` imports
neither Streamlit nor any optional model library, no
`SentenceTransformerEmbeddingProvider` is ever constructed during
render, and rendering leaves memory stores, events, and committed
artifacts byte-unchanged.

## Judge demo talking points

1. The selection table shows *why* each memory entered or missed
   context — with the lifecycle-authoritative exclusions visually
   distinct from ranking/budget skips.
2. Forgotten/superseded rows prove similarity cannot resurrect
   memories: no semantic score exists for them at all.
3. The shadow gate visibly disagrees sometimes — and the affected-
   selection counter stays 0, showing controllers propose while the
   kernel decides.
4. The benchmark expander shows the honest Prompt 7 outcome:
   embedding-only not adopted, fused experimental, everything
   lifecycle-safe, no official-score claims.

## Limitations

The default demo runs the lexical Phase 9 path, so live semantic
panels populate only when a Phase 11 strategy is configured
(fused retrieval remains experimental and is not the default);
benchmark numbers are committed evidence, not live computation; the
deterministic-provider limitation applies to every semantic value
shown.
