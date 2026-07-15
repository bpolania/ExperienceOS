"""Read-only evaluation of deterministic forget-directive intelligence.

Measures forget classification and target intelligence: the controller
sees only the source statement, its evidence, and the before-state, and
must independently classify the directive and resolve its target. The
verifier then judges what it produced. The oracle is used to score the
output, never to generate it.

Historical-scored and development-only partitions are always reported
separately. Unresolved and excluded records are never scored.
"""

EVALUATION_VERSION = "1"
