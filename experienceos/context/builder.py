"""Context builder.

Assembles the context messages sent to the model provider, including
the user's retrieved active experience.
"""

from __future__ import annotations

from experienceos.memory.schema import ExperienceEntry, MemoryKind

MEMORY_HEADER = "ExperienceOS retrieved these active user experiences:"

_KIND_SECTIONS = (
    (MemoryKind.PREFERENCE, "Preferences:"),
    (MemoryKind.FACT, "Facts:"),
    (MemoryKind.INSTRUCTION, "Instructions:"),
)


class ContextBuilder:
    """Builds provider context messages for one interaction."""

    def build_context(
        self,
        user_id: str,
        session_id: str,
        message: str,
        memories: list[ExperienceEntry] | None = None,
    ) -> list[dict[str, str]]:
        context: list[dict[str, str]] = [
            {
                "role": "system",
                "content": (
                    "ExperienceOS is active. Use any retrieved user "
                    "experience to personalize responses."
                ),
            }
        ]
        if memories:
            context.append(
                {
                    "role": "system",
                    "content": f"{MEMORY_HEADER}\n\n"
                    + "\n\n".join(self._kind_sections(memories)),
                }
            )
        return context

    @staticmethod
    def _kind_sections(memories: list[ExperienceEntry]) -> list[str]:
        """Memories grouped under kind labels, known kinds first."""
        known_kinds = {kind for kind, _ in _KIND_SECTIONS}
        groups = [
            *_KIND_SECTIONS,
            *(((m.kind, f"{m.kind.capitalize()}:") for m in memories
               if m.kind not in known_kinds)),
        ]
        sections, rendered = [], set()
        for kind, label in groups:
            if kind in rendered:
                continue
            rendered.add(kind)
            group = [m for m in memories if m.kind == kind]
            if group:
                sections.append(
                    label + "\n" + "\n".join(f"- {m.text}" for m in group)
                )
        return sections
