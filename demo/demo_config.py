"""Configuration for the ExperienceOS demo dashboard."""

DEMO_TITLE = "ExperienceOS"
TAGLINE = (
    "AI today has intelligence but no life experience. ExperienceOS gives "
    "any AI agent the ability to accumulate experience over time."
)
DEMO_NOTE = "Platform demo — the dashboard makes the experience layer observable."

# The repeatable scripted demo: preferences stated, then changed, then
# retrieved — showing ExperienceOS adapting as experience changes.
SCRIPTED_DEMO = [
    ("session-preferences", "I prefer aisle seats and morning flights."),
    ("session-update", "Actually, I prefer window seats now."),
    ("session-trip", "Help me book a work trip to NYC."),
]
