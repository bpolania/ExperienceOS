# Qwen vs Deterministic Grounded Extraction — Final Comparison

Prompt version 3 · model `qwen-plus` · temperature 0 · one inference, no retries · shadow only, no memory mutation.

## Per corpus

### lifecycle (39 scorable, 15 expected)
- Recall — deterministic **0.3333**, Qwen **0.8667**
- Precision — deterministic 0.8333, Qwen 0.9286
- Over-extraction — deterministic 0.0417, Qwen 0.0417
- Overall correctness — deterministic **0.7179**, Qwen **0.9231**
- False positives — deterministic 1, Qwen 1
- Qwen: 39 ok / 0 failed · grounding-rejected 5 · agreement 0.7949 · latency avg 2816.9 ms (median 2772.8, max 4720.2)

### external (0 scorable)
- Unscorable for durable-memory extraction — see `external/UNSCORABLE.md`. The corpus has no per-message source text or creation oracle; excluded from scoring.

## Combined
- Scorable 39 · expected candidates 15 · Qwen ok 39 / failed 0
- Recall — deterministic **0.3333**, Qwen **0.8667**
- Precision — deterministic 0.8333, Qwen 0.9286
- Overall correctness — deterministic **0.7179**, Qwen **0.9231**
- Qwen unique wins: 8 · deterministic unique wins: 0
- False positives — shared 1, Qwen-only 0, deterministic-only 0
- Average Qwen latency: 2816.9 ms

## Reading these numbers

Three distinct things are reported and never conflated: a **proposal** is what a controller asserted; **accepted** is what the unchanged `GroundedCandidateValidator` allowed through (asserted-but-rejected shows as grounding-rejected); and **oracle-correct** is whether that accepted result matches the corpus `candidate_expected` label. An accepted candidate is not automatically correct.

The quality result rests on **one** creation-scorable corpus (lifecycle, 39 messages / 15 expected). The external corpus is unscorable for extraction, so cross-corpus generalization is **unconfirmed**. Qwen adds ~2.8 s/message latency and a live provider dependency; a failed call is a visible failed record, never a deterministic substitution.

## Reproduce

```
PYTHONPATH=. .venv/bin/python -m experiments.qwen_extraction_shadow run --subset lifecycle
PYTHONPATH=. .venv/bin/python -m experiments.qwen_extraction_shadow run --subset external
PYTHONPATH=. .venv/bin/python -m experiments.qwen_extraction_shadow combine
```

Requires `QWEN_API_KEY` in the environment or `.env`.
