# External corpus: unscorable for durable-memory extraction

`benchmarks/annotations/grounded-extraction/external.jsonl` (50 records)
cannot provide extraction evidence and returns 0 scorable records:

- `scorable = false` on all 50 records;
- the records carry **no `source_text`** — the frozen artifacts retain only
  digests/previews of the original multi-session conversations, so there is
  no single message to run through either extractor;
- annotation note: *"Answer-bearing content exists but is spread across
  sessions; frozen artifacts retain only digests/previews of the source, so
  no exact single-message span/kind/normalization oracle can be built.
  Reported as candidate-absence context only."*;
- classification: retrieval-only (20), extraction-oracle-insufficient (10),
  downstream-only (10), not-extraction-related (10) — none is a
  durable-memory creation oracle.

This is a corpus limitation, not a Qwen or deterministic result. The
comparison is therefore reported on `lifecycle.jsonl` only (the sole
creation-scorable corpus), and cross-corpus generalization remains
unconfirmed.
