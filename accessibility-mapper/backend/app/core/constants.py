"""Domain vocabulary: barrier categories, severities, edge kinds, ticket states."""

from __future__ import annotations

from typing import Final, Literal

BarrierCategory = Literal[
    "blocked_ramp",
    "broken_lift",
    "narrow_path",
    "construction",
    "obstacle",
    "missing_signage",
]

BarrierStatus = Literal["unverified", "verified", "in_progress", "resolved", "expired"]

BarrierSource = Literal["yolov8", "heuristic", "citizen_manual", "admin"]

NodeKind = Literal["building", "entrance", "lift", "door", "intersection", "facility"]

EdgeKind = Literal["footpath", "corridor", "stairs", "ramp", "elevator", "crossing"]

TicketPriority = Literal["low", "medium", "high", "critical"]
TicketStatus = Literal["open", "in_progress", "resolved"]

UserRole = Literal["student", "staff", "admin"]

BARRIER_CATEGORIES: Final[tuple[str, ...]] = (
    "blocked_ramp",
    "broken_lift",
    "narrow_path",
    "construction",
    "obstacle",
    "missing_signage",
)

#: Human labels used in the UI and in voice guidance.
CATEGORY_LABELS: Final[dict[str, str]] = {
    "blocked_ramp": "Blocked ramp",
    "broken_lift": "Broken lift",
    "narrow_path": "Narrow path",
    "construction": "Construction zone",
    "obstacle": "Obstacle on path",
    "missing_signage": "Missing signage",
}

#: Severity drives map colour, ticket priority and heatmap intensity.
CATEGORY_SEVERITY: Final[dict[str, int]] = {
    "blocked_ramp": 5,
    "broken_lift": 5,
    "construction": 4,
    "narrow_path": 3,
    "obstacle": 3,
    "missing_signage": 1,
}

#: Categories that make a step-free route physically impossible.
STEP_FREE_BLOCKING: Final[frozenset[str]] = frozenset(
    {"blocked_ramp", "broken_lift", "narrow_path"}
)

SEVERITY_COLORS: Final[dict[int, str]] = {
    5: "#dc2626",  # critical  - red
    4: "#ea580c",  # high      - orange
    3: "#f59e0b",  # medium    - amber
    2: "#eab308",  # low       - yellow
    1: "#64748b",  # cosmetic  - slate
}

CATEGORY_COLORS: Final[dict[str, str]] = {
    "blocked_ramp": "#dc2626",
    "broken_lift": "#b91c1c",
    "construction": "#ea580c",
    "narrow_path": "#f59e0b",
    "obstacle": "#facc15",
    "missing_signage": "#64748b",
}

#: Default TTL (hours) per category before an unconfirmed report lapses.
CATEGORY_TTL_HOURS: Final[dict[str, int]] = {
    "blocked_ramp": 72,
    "broken_lift": 24 * 14,
    "construction": 24 * 21,
    "narrow_path": 24 * 7,
    "obstacle": 48,
    "missing_signage": 24 * 30,
}

#: Free-text synonyms feeding the heuristic detector and the admin search box.
CATEGORY_KEYWORDS: Final[dict[str, tuple[str, ...]]] = {
    "blocked_ramp": (
        "blocked ramp",
        "ramp blocked",
        "bin on ramp",
        "scooter on ramp",
        "ramp obstruction",
    ),
    "broken_lift": ("lift out", "out of service", "elevator broken", "lift fault"),
    "narrow_path": ("narrow", "squeeze", "tight gap", "passage too narrow"),
    "construction": ("construction", "scaffold", "works", "digging", "barrier tape"),
    "obstacle": (
        "scooter",
        "bike",
        "bin",
        "bench",
        "cone",
        "obstacle",
        "puddle",
        "debris",
    ),
    "missing_signage": ("no sign", "signage", "unmarked", "no notice"),
}
