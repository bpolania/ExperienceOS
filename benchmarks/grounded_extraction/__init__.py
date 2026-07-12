"""Grounded extraction benchmark and ablation evidence.

Evaluates the grounded-extraction controllers as explicit, non-canonical
benchmark systems across four evidence layers — proposal quality,
grounding validation, lifecycle admission, and durable/downstream
outcomes — without changing any default ExperienceOS behavior and
without adopting any controller. All primary extraction aggregates are
computed on the frozen lifecycle dataset against additive annotations;
the external subset is classified for context only.
"""

RUN_SCHEMA_VERSION = "1"
