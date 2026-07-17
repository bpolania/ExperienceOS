# Qwen vs deterministic update intelligence

Classification-only comparison over the frozen update corpus (`transition_verification_frozen`). Both implementations are scored in one shared five-class space (NEW / UPDATE / COEXIST / DUPLICATE / IGNORE) derived from the committed transition annotations. Qwen classifies only; it holds no mutation authority and every deterministic governance gate is unchanged.

- comparison version: 1
- cases: 48
- class support: {'NEW': 6, 'UPDATE': 17, 'COEXIST': 3, 'DUPLICATE': 5, 'IGNORE': 17}
- deterministic controller: experienceos_transition_rules_v1
- Qwen controller: qwen_update-1 (prompt v1)
- model: qwen-plus · temperature: 0.0 · timeout(s): 8.0 · inferences/case: 1

## Headline metrics

| metric | deterministic | qwen |
|---|---|---|
| overall accuracy (correct/scored) | 48/48 | 32/48 |
| scored (non-failed) | 48 | 48 |
| UPDATE cases | 17 | 16 |
| UPDATE correct target | 17 | 16 |
| UPDATE wrong target | 0 | 0 |
| false UPDATE | 0 | 6 |
| missed UPDATE | 0 | 1 |

Per-class values are recall = correct/support and precision = correct/predicted (class only; target correctness is the separate wrong-target row).

### Deterministic per class

| class | support | predicted | correct | recall | precision |
|---|---|---|---|---|---|
| NEW | 6 | 6 | 6 | 1.000 | 1.000 |
| UPDATE | 17 | 17 | 17 | 1.000 | 1.000 |
| COEXIST | 3 | 3 | 3 | 1.000 | 1.000 |
| DUPLICATE | 5 | 5 | 5 | 1.000 | 1.000 |
| IGNORE | 17 | 17 | 17 | 1.000 | 1.000 |

### Qwen per class

| class | support | predicted | correct | recall | precision |
|---|---|---|---|---|---|
| NEW | 6 | 15 | 6 | 1.000 | 0.400 |
| UPDATE | 17 | 22 | 16 | 0.941 | 0.727 |
| COEXIST | 3 | 1 | 0 | 0.000 | 0.000 |
| DUPLICATE | 5 | 4 | 4 | 0.800 | 1.000 |
| IGNORE | 17 | 6 | 6 | 0.353 | 1.000 |

## Safety and structured output (Qwen)

- structured-output accepted: 48
- structured-output rejected: 0 {}
- fabricated-target rejected: 0
- provider failures: 0
- unsafe proposals: 0
- rejected proposals reaching mutation authority: 0

The strict parser is the structured-output validator (it rejects fabricated ids, missing / extra targets, and malformed output). The harness holds no store, engine, or manager and applies nothing, so no proposal — valid or rejected — reaches mutation authority. The full transition verifier remains downstream and unchanged; this experiment is classification-only and never constructs an applied transition.

## Latency

- deterministic: {'count': 48, 'median_ms': 1.667, 'p95_ms': 4.4556, 'max_ms': 7.6223, 'total_ms': 90.989}
- qwen: {'count': 48, 'median_ms': 1693.0366, 'p95_ms': 2422.6879, 'max_ms': 2571.6712, 'total_ms': 84379.0069}
