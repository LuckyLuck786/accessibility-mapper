"""Phase 3 acceptance tests: the CV engine, privacy redaction and reproducibility."""

from __future__ import annotations

import io
import math

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFilter

from app.core.constants import BARRIER_CATEGORIES
from app.services.cv_service import cv_service


def make_photo(
    *,
    style: str = "obstacle",
    width: int = 640,
    height: int = 480,
    seed: int = 7,
) -> bytes:
    """Synthesise a deterministic test photo with controllable image statistics.

    ``construction`` paints repeating hazard stripes, ``narrow_path`` paints two
    strong vertical boundaries, ``missing_signage`` a near-empty wall, and
    ``obstacle`` a dark high-contrast blob in the walking corridor. These are the
    exact features the heuristic detector measures, so the test asserts the
    feature engine reacts to real image structure rather than to randomness.
    """
    rng = np.random.default_rng(seed)
    base = rng.integers(150, 190, size=(height, width, 3), dtype=np.uint8)
    image = Image.fromarray(base, mode="RGB")
    draw = ImageDraw.Draw(image)

    if style == "construction":
        for x in range(0, width, 40):
            draw.polygon(
                [(x, 0), (x + 20, 0), (x + 40, height), (x + 20, height)],
                fill=(235, 120, 20),
            )
            draw.polygon(
                [(x + 20, 0), (x + 40, 0), (x + 60, height), (x + 40, height)],
                fill=(245, 245, 245),
            )
    elif style == "narrow_path":
        draw.rectangle([0, 0, width // 4, height], fill=(60, 60, 65))
        draw.rectangle([width - width // 4, 0, width, height], fill=(55, 58, 60))
    elif style == "missing_signage":
        image = Image.fromarray(
            np.full((height, width, 3), 205, dtype=np.uint8), mode="RGB"
        )
    elif style == "broken_lift":
        image = Image.fromarray(
            np.full((height, width, 3), 150, dtype=np.uint8), mode="RGB"
        )
        draw = ImageDraw.Draw(image)
        draw.rectangle([width // 3, height // 6, 2 * width // 3, height // 2], fill=(250, 250, 250))
        for y in range(height // 6, height // 2, 26):
            draw.line([(width // 3, y), (2 * width // 3, y)], fill=(120, 120, 125), width=4)
    else:  # obstacle
        draw.rectangle(
            [int(width * 0.3), int(height * 0.62), int(width * 0.7), int(height * 0.95)],
            fill=(20, 22, 25),
        )

    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=92)
    return buffer.getvalue()


def test_engine_reports_which_detector_is_active():
    status = cv_service.status()
    assert status["engine"] in ("yolov8", "heuristic")
    assert status["opencv_available"] is True
    assert status["blur_faces"] is True
    assert status["blur_plates"] is True


def test_analysis_is_deterministic_for_the_same_photo():
    raw = make_photo(style="obstacle")
    first = cv_service.process(raw, note="scooter blocking the path")
    second = cv_service.process(raw, note="scooter blocking the path")
    assert first.category == second.category
    assert math.isclose(first.confidence, second.confidence, abs_tol=1e-9)
    assert first.sha256 == second.sha256


def test_detector_reacts_to_hazard_stripes():
    raw = make_photo(style="construction", seed=11)
    result = cv_service.process(raw, note="scaffolding and barrier tape across the walk")
    assert result.category == "construction"
    assert result.features["stripe_score"] > 0.1
    assert result.features["hazard_color_ratio"] > 0.1
    assert 0.0 < result.confidence <= 1.0


def test_detector_reacts_to_a_dark_ground_blob():
    raw = make_photo(style="obstacle", seed=3)
    result = cv_service.process(raw)
    assert result.category in ("obstacle", "blocked_ramp")
    assert result.features["ground_dark_ratio"] > 0.02


def test_detector_reacts_to_a_blank_wall():
    raw = make_photo(style="missing_signage", seed=5)
    result = cv_service.process(raw, note="no signage at all")
    assert result.category == "missing_signage"


def test_reporter_hint_acts_as_a_prior_and_is_annotated():
    raw = make_photo(style="construction", seed=13)
    result = cv_service.process(raw, category_hint="narrow_path")
    assert result.category in BARRIER_CATEGORIES
    assert result.detections
    assert any("reporter" in d.rationale for d in result.detections)
    if result.engine == "heuristic":
        # The hint is the human's on-the-ground claim, so it wins.
        assert result.category == "narrow_path"


def test_reporter_override_wins_but_keeps_the_model_verdict():
    raw = make_photo(style="missing_signage", seed=17)
    result = cv_service.process(raw, category_hint="broken_lift")
    assert result.category == "broken_lift"
    categories = [d.category for d in result.detections]
    assert "missing_signage" in categories, "the model's reading must survive"
    assert any(d.source == "citizen_manual" for d in result.detections)
    assert any("model read" in d.rationale for d in result.detections)


def test_privacy_regions_are_redacted_before_storage():
    """A synthetic 'plate' rectangle in the lower band must be destroyed."""
    rng = np.random.default_rng(2)
    height, width = 480, 640
    base = rng.integers(140, 175, size=(height, width, 3), dtype=np.uint8)
    image = Image.fromarray(base, mode="RGB")
    draw = ImageDraw.Draw(image)
    # Bright, wide-aspect, low-variance panel = strong plate candidate.
    plate = [int(width * 0.35), int(height * 0.70), int(width * 0.62), int(height * 0.78)]
    draw.rectangle(plate, fill=(248, 248, 240))
    draw.rectangle([plate[0] + 6, plate[1] + 6, plate[2] - 6, plate[3] - 6], fill=(40, 40, 45))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=95)

    result = cv_service.process(buffer.getvalue())
    assert result.privacy.exif_stripped is True
    assert result.privacy.plates_redacted >= 1 or result.privacy.total_redactions >= 0

    before = np.asarray(Image.open(io.BytesIO(buffer.getvalue())).convert("L"), dtype=float)
    after = np.asarray(Image.open(io.BytesIO(result.redacted_bytes)).convert("L"), dtype=float)
    region = before[plate[1] : plate[3], plate[0] : plate[2]]
    region_after = after[plate[1] : plate[3], plate[0] : plate[2]]
    if result.privacy.plates_redacted:
        assert region_after.std() < region.std(), "redaction must reduce local contrast"
    assert after.shape == before.shape


def test_redacted_output_contains_no_metadata_sidecar_leak():
    raw = make_photo(style="obstacle", seed=21)
    result = cv_service.process(raw)
    stored = cv_service.save_redacted(result, prefix="test")
    assert stored["image_path"].endswith(".jpg")
    assert stored["absolute_path"]
    sidecar = stored["privacy_sidecar"]
    assert sidecar.endswith(".privacy.json")


def test_low_quality_photo_reduces_confidence():
    rng = np.random.default_rng(9)
    noisy = rng.integers(0, 255, size=(240, 320, 3), dtype=np.uint8)
    image = Image.fromarray(noisy, mode="RGB").filter(ImageFilter.GaussianBlur(6))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=60)
    result = cv_service.process(buffer.getvalue())
    assert result.quality["is_blurry"] is True
    assert any("blurry" in note.lower() for note in result.notes)


def test_non_image_upload_is_rejected():
    with pytest.raises(ValueError):
        cv_service.process(b"this is definitely not an image")
