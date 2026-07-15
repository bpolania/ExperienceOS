"""Read-only evaluation of transition proposal verification.

Consumes the frozen transition-verification annotation corpus without
modifying it. Proposals are **oracle-derived**: built directly from the
committed expected transitions. This measures whether the verifier
accepts correct transitions and rejects corrupted ones — it measures
nothing about a proposal controller's precision or recall, because no
controller generates these proposals.
"""

EVALUATION_VERSION = "1"
