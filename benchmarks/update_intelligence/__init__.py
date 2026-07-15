"""Read-only evaluation of deterministic update intelligence.

Unlike the transition-verification evaluation — which feeds the verifier
oracle-derived proposals — this package measures **proposal
intelligence**: the controller sees only the source statement, its
evidence, and the before-state, and must independently choose the
transition type, the target, the created value, the scope, and the
preservation set. The verifier then judges what it produced.

Historical-scored and development-only partitions are always reported
separately. Unresolved and excluded records are never scored.
"""

EVALUATION_VERSION = "1"
