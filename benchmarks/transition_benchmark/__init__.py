"""Transition benchmark: reproducible evidence for transition intelligence.

Measures whether transition intelligence keeps accumulated experience more
current, less duplicated, safer to forget, and better preserved across
scopes — against the canonical reference, on the frozen corpus.

Every system runs against an isolated in-memory store seeded from the
same frozen before-state, through the real `ExperienceManager` and
`ExperienceEngine`. The oracle scores output; it never generates it.

Nothing here changes runtime defaults. Adopted infrastructure appearing
in results is isolated evidence that the governed path works — never
evidence of canonical adoption.
"""

BENCHMARK_VERSION = "1"
SCHEMA_VERSION = "1"
