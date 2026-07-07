"""Context builder.

Assembles the context messages sent to the model provider, including
the user's retrieved active experience.
"""

from __future__ import annotations

from experienceos.memory.schema import ExperienceEntry

MEMORY_HEADER = "ExperienceOS retrieved these active user experiences:"


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
            lines = "\n".join(f"- {m.text}" for m in memories)
            context.append(
                {"role": "system", "content": f"{MEMORY_HEADER}\n{lines}"}
            )
        return context
