# Qwen vs Deterministic Grounded Extraction — Shadow Comparison

- Model: `qwen-plus` · temperature 0.0 · timeout 30000 ms · one inference, no retries · prompt version 2
- Corpus: `grounded-extraction/lifecycle.jsonl` (39 scorable messages) · shadow only, no memory mutation

## Aggregate
- Qwen inference: 39 succeeded, 0 failed
- Deterministic accepted candidates: 6
- Qwen accepted candidates: 10 (rejected by grounding: 6)
- Agreement: 0.8974 · disagreement: 0.1026
- Average Qwen latency: 2718.8 ms

## Oracle quality (scored on successful Qwen messages)
- Durable-memory recall — deterministic **0.3333**, Qwen **0.6** (of 15 expected candidates)
- Over-extraction — deterministic **0.0417**, Qwen **0.0417** (of 24 not-expected messages)
- Overall correctness vs oracle — deterministic **0.7179**, Qwen **0.8205**

Reproduce: `PYTHONPATH=. .venv/bin/python -m experiments.qwen_extraction_shadow run --subset lifecycle`
