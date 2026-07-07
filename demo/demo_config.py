"""Configuration for the ExperienceOS demo dashboard."""

DEMO_TITLE = "ExperienceOS"
TAGLINE = (
    "AI today has intelligence but no life experience. ExperienceOS gives "
    "any AI agent the ability to accumulate experience over time."
)
DEMO_NOTE = "Platform demo — the dashboard makes the experience layer observable."

# The repeatable scripted demo: one run shows the full lifecycle —
# remember (preferences, facts, instructions), retrieve with a bounded
# selection, update (supersede), forget, and retrieve again.
SCRIPTED_DEMO = [
    (
        "session-preferences",
        "I prefer aisle seats and morning flights. "
        "I don't like red-eye flights.",
    ),
    ("session-preferences", "I prefer quiet hotels near the airport."),
    ("session-facts", "My home airport is SFO."),
    ("session-facts", "My company is based in San Jose."),
    (
        "session-instructions",
        "When planning work trips, include airport transfer time.",
    ),
    ("session-trip-1", "Help me plan a work trip to New York."),
    ("session-facts-update", "Actually, my home airport is now SJC."),
    ("session-update", "Actually, I prefer evening flights."),
    ("session-forget", "Forget my aisle seat preference."),
    ("session-trip-2", "Help me plan another work trip."),
]
