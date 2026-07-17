"""Applied-state verification for governed action replacement.

Consumes the frozen historical transition corpus read-only and runs every
case through the real governed pipeline (planner, manager, verifier,
matcher, plan builder, authorization, engine), comparing the existing
add-not-replace behavior against authorized replacement. Produces
deterministic evidence; it changes no runtime, no authorization, and no
frozen artifact, and it decides nothing about adoption.
"""

BENCHMARK_VERSION = "1"
SCHEMA_VERSION = "1"
