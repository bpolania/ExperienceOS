# Qwen vs Deterministic Grounded Extraction — Shadow Comparison

- Model: `qwen-plus` · temperature 0.0 · timeout 30000 ms · one inference, no retries · prompt version 3
- Corpus: `grounded-extraction/external.jsonl` (0 scorable messages) · shadow only, no memory mutation

## Aggregate
- Qwen inference: 0 succeeded, 0 failed
- Deterministic accepted candidates: 0
- Qwen accepted candidates: 0 (rejected by grounding: 0)
- Agreement: None · disagreement: None
- Average Qwen latency: None ms

## Oracle quality (scored on successful Qwen messages)
- Durable-memory recall — deterministic **None**, Qwen **None** (of 0 expected candidates)
- Over-extraction — deterministic **None**, Qwen **None** (of 0 not-expected messages)
- Overall correctness vs oracle — deterministic **None**, Qwen **None**

Reproduce: `PYTHONPATH=. .venv/bin/python -m experiments.qwen_extraction_shadow run --subset external`
