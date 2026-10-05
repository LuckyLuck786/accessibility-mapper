"""Barrier report / confirmation contracts."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.constants import BARRIER_CATEGORIES

BarrierCategoryLiteral = Literal[
    "blocked_ramp",
    "broken_lift",
    "narrow_path",
    "construction",
    "obstacle",
    "missing_signage",
]


class DetectionOut(BaseModel):
    category: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    bbox: dict[str, int]
    source: str
    rationale: str = ""


class PrivacyOut(BaseModel):
    faces_redacted: int = 0
    plates_redacted: int = 0
    other_redacted: int = 0
    total_redactions: int = 0
    exif_stripped: bool = True
    engine: str = "opencv-haar"
    regions: list[dict[str, Any]] = Field(default_factory=list)


class CVResultOut(BaseModel):
    category: str
    confidence: float
    engine: str
    detections: list[DetectionOut] = Field(default_factory=list)
    privacy: PrivacyOut
    quality: dict[str, Any] = Field(default_factory=dict)
    image_size: dict[str, int] = Field(default_factory=dict)
    sha256: str | None = None
    features: dict[str, float] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)
    auto_verify_threshold: float = 0.85
    would_auto_verify: bool = False


class BarrierOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: int
    category: BarrierCategoryLiteral
    label: str
    severity: int = Field(..., ge=1, le=5)
    color: str
    latitude: float
    longitude: float
    confidence: float = Field(..., ge=0.0, le=1.0)
    status: Literal["unverified", "verified", "in_progress", "resolved", "expired"]
    description: str | None = None
    redacted_faces: int = 0
    redacted_plates: int = 0
    detection_source: str
    edge_id: str | None = None
    reporter_label: str
    confirmations: int = 0
    ticket_id: int | None = None
    is_active: bool
    is_hard_block: bool
    created_at: str | None = None
    updated_at: str | None = None
    verified_at: str | None = None
    resolved_at: str | None = None
    expires_at: str | None = None
    age_hours: float = 0.0
    resolution_hours: float | None = None
    image_url: str | None = None


class BarrierReportResponse(BaseModel):
    action: Literal["created", "confirmed", "rejected"]
    message: str
    barrier: BarrierOut
    cv: CVResultOut
    analysis: dict[str, Any] = Field(default_factory=dict)
    privacy: PrivacyOut
    image: dict[str, Any] = Field(default_factory=dict)
    edge: dict[str, Any] | None = None
    ticket: dict[str, Any] | None = None
    merged_with: int | None = None
    dedupe: dict[str, Any] = Field(default_factory=dict)
    auto_verify: dict[str, Any] = Field(default_factory=dict)


class BarrierConfirmRequest(BaseModel):
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    note: str | None = Field(default=None, max_length=500)


class BarrierConfirmResponse(BaseModel):
    action: str
    message: str
    barrier: BarrierOut
    promoted_to_verified: bool = False
    ticket: dict[str, Any] | None = None


class BarrierListOut(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[BarrierOut]


class BarrierTimelineOut(BaseModel):
    barrier_id: int
    events: list[dict[str, Any]]
    confirmations: list[dict[str, Any]]


class CategoryInfo(BaseModel):
    category: str
    label: str
    color: str
    severity: int
    step_free_blocking: bool
    active_count: int = 0


class CategoriesOut(BaseModel):
    categories: list[CategoryInfo]

    @field_validator("categories")
    @classmethod
    def _non_empty(cls, value: list[CategoryInfo]) -> list[CategoryInfo]:
        if not value:
            raise ValueError("category catalogue must not be empty")
        if len(value) != len(BARRIER_CATEGORIES):
            raise ValueError("category catalogue is incomplete")
        return value
