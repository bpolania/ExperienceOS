"""Provider-backed ExperienceOS extensions, kept outside the kernel.

Nothing here is part of the deterministic kernel. These modules reuse
existing interfaces and can be deleted with no effect on the core
package: keeping them outside ``experienceos/`` preserves the core's
provider-neutrality and its separation from optional learned paths.

``qwen_extraction`` is no longer shadow-only — it is the canonical
extraction controller whenever Qwen Cloud is configured, selected by the
demo composition layer. It still only proposes candidates; the
deterministic governance downstream remains authoritative.

``qwen_update`` is an experimental update-intelligence controller
(classify-and-propose only, not canonical) with a side-by-side
comparison harness over the frozen update corpus. It holds no mutation
authority; the deterministic update path stays authoritative.
"""
