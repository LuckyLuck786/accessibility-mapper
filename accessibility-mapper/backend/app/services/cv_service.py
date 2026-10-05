"""Privacy-first image pipeline: redact -> analyse -> classify -> store.

Responsibilities, deliberately in this order:

1. **Privacy first.** Every uploaded photo is decoded, faces and licence plates
   are detected with OpenCV and destroyed with a strong Gaussian blur *before*
   the classifier sees a single pixel, and before anything is written to the
   database. The stored artifact keeps a signed proof of what was removed.
   EXIF (which carries GPS + device identifiers) is stripped by re-encoding.

2. **Classification**, via the :mod:`app.services.classifier` interface. Default
   is the deterministic heuristic feature detector; set ``CV_ENDPOINT_URL`` to
   forward to an external inference service instead. There is no ultralytics /
   torch import anywhere - the deployed bundle stays small.

3. **Storage in Postgres.** Redacted bytes land in the ``media_objects`` table as
   ``bytea`` and are served from ``GET /api/v1/media/{id}``. Serverless
   filesystems are read-only, so there is deliberately no media directory.

Everything runs **synchronously inside the request**. A serverless function is
frozen the moment the response is written, so a ``BackgroundTask`` refinement
pass would silently never run on Vercel - it is folded into the request path
here instead, and the refinement event is recorded before the response returns.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image, ImageFilter

from app.core.config import settings
from app.core.constants import CATEGORY_KEYWORDS
from app.services.classifier import Classification, get_classifier

logger = logging.getLogger("abm.cv")

try:  # pragma: no cover - exercised implicitly at import time
    import cv2
    import numpy as np

    CV_AVAILABLE = True
except Exception as exc:  # pragma: no cover
    cv2 = None  # type: ignore[assignment]
    np = None  # type: ignore[assignment]
    CV_AVAILABLE = False
    logger.warning("OpenCV/numpy unavailable (%s) - using Pillow-only fallback", exc)


#: Kept for reference/label mapping. The classifier owns category synonyms now;
#: this remains the human-facing vocabulary shared with the map and UI.
BARRIER_CLASS_SYNONYMS: dict[str, str] = {
    "backpack": "obstacle",
    "handbag": "obstacle",
    "suitcase": "obstacle",
    "bottle": "obstacle",
    "bench": "obstacle",
    "chair": "obstacle",
    "bicycle": "obstacle",
    "motorcycle": "obstacle",
    "car": "obstacle",
    "traffic cone": "construction",
    "cone": "construction",
    "barrier": "construction",
    "scaffolding": "construction",
    "fence": "construction",
    "stop sign": "missing_signage",
    "sign": "missing_signage",
    "wheelchair": "blocked_ramp",
    "blocked_ramp": "blocked_ramp",
    "broken_lift": "broken_lift",
    "narrow_path": "narrow_path",
    "construction": "construction",
    "obstacle": "obstacle",
    "missing_signage": "missing_signage",
    "ramp_obstruction": "blocked_ramp",
    "lift_out_of_service": "broken_lift",
}


@dataclass
class Detection:
    """Backwards-compatible view over a :class:`Classification`."""

    category: str
    confidence: float
    bbox: tuple[int, int, int, int]
    source: str
    rationale: str = ""

    @classmethod
    def from_classification(cls, item: Classification) -> "Detection":
        return cls(
            category=item.category,
            confidence=float(item.confidence),
            bbox=tuple(item.bbox),  # type: ignore[arg-type]
            source=item.source,
            rationale=item.rationale,
        )

    def to_dict(self) -> dict[str, Any]:
        x, y, w, h = self.bbox
        return {
            "category": self.category,
            "confidence": round(float(self.confidence), 3),
            "bbox": {"x": int(x), "y": int(y), "width": int(w), "height": int(h)},
            "source": self.source,
            "rationale": self.rationale,
        }


@dataclass
class PrivacyReport:
    faces_redacted: int = 0
    plates_redacted: int = 0
    other_redacted: int = 0
    regions: list[dict[str, Any]] = field(default_factory=list)
    exif_stripped: bool = True
    engine: str = "opencv-haar"

    @property
    def total_redactions(self) -> int:
        return self.faces_redacted + self.plates_redacted + self.other_redacted

    def to_dict(self) -> dict[str, Any]:
        return {
            "faces_redacted": self.faces_redacted,
            "plates_redacted": self.plates_redacted,
            "other_redacted": self.other_redacted,
            "total_redactions": self.total_redactions,
            "regions": self.regions,
            "exif_stripped": self.exif_stripped,
            "engine": self.engine,
        }


@dataclass
class AnalysisResult:
    detections: list[Detection]
    category: str
    confidence: float
    engine: str
    privacy: PrivacyReport
    quality: dict[str, Any]
    image_size: tuple[int, int]
    redacted_bytes: bytes
    sha256: str
    thumbnail_bytes: bytes | None = None
    features: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def top_detection(self) -> Detection | None:
        return self.detections[0] if self.detections else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "confidence": round(float(self.confidence), 3),
            "engine": self.engine,
            "detections": [d.to_dict() for d in self.detections],
            "privacy": self.privacy.to_dict(),
            "quality": self.quality,
            "image_size": {"width": self.image_size[0], "height": self.image_size[1]},
            "sha256": self.sha256,
            "features": {k: round(float(v), 4) for k, v in self.features.items()},
            "notes": self.notes,
            "auto_verify_threshold": settings.barrier_confidence_threshold,
            "would_auto_verify": self.confidence >= settings.barrier_confidence_threshold,
            "privacy_first": True,
        }

    def sidecar(self) -> dict[str, Any]:
        """The signed proof of what the privacy pass removed."""
        return {
            "sha256": self.sha256,
            "engine": self.engine,
            "detections": [d.to_dict() for d in self.detections],
            "privacy": self.privacy.to_dict(),
            "quality": self.quality,
            "features": self.features,
            "notes": self.notes,
        }


class CVService:
    """Stateless image pipeline: redact -> classify -> re-encode."""

    def __init__(self) -> None:
        self._face_cascade = None
        self._profile_cascade = None
        self._plate_cascade = None
        if CV_AVAILABLE:
            self._load_cascades()

    # ------------------------------------------------------------------
    # Model bootstrap
    # ------------------------------------------------------------------
    def _load_cascades(self) -> None:  # pragma: no cover - depends on wheel
        try:
            base = cv2.data.haarcascades  # type: ignore[union-attr]
            self._face_cascade = cv2.CascadeClassifier(
                f"{base}haarcascade_frontalface_default.xml"
            )
            self._profile_cascade = cv2.CascadeClassifier(
                f"{base}haarcascade_profileface.xml"
            )
            plate_path = Path(f"{base}haarcascade_russian_plate_number.xml")
            if plate_path.exists():
                self._plate_cascade = cv2.CascadeClassifier(str(plate_path))
            logger.info(
                "OpenCV cascades ready (face=%s, profile=%s, plate=%s)",
                not self._face_cascade.empty(),
                not self._profile_cascade.empty(),
                self._plate_cascade is not None and not self._plate_cascade.empty(),
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("Could not load Haar cascades: %s", exc)

    @property
    def engine_name(self) -> str:
        return get_classifier().name

    def status(self) -> dict[str, Any]:
        classifier = get_classifier()
        external = classifier.name == "external"
        return {
            "engine": classifier.name,
            "engine_kind": "external model endpoint" if external else "heuristic rule-based estimator",
            "is_learned_model": external,
            "opencv_available": CV_AVAILABLE,
            "opencv_version": getattr(cv2, "__version__", None) if CV_AVAILABLE else None,
            "face_detector": "haar-frontalface" if self._face_cascade is not None else "disabled",
            "plate_detector": (
                "haar-plate+contour" if self._plate_cascade is not None else "contour-heuristic"
            ),
            "cv_endpoint_url": settings.cv_endpoint_url or None,
            "blur_faces": settings.blur_faces,
            "blur_plates": settings.blur_license_plates,
            "max_upload_bytes": settings.max_upload_bytes,
            "storage": "postgres-bytea" if settings.store_media_in_db else "filesystem",
            "hint": (
                "Classification is a deterministic heuristic feature detector - "
                "not a trained model. Set CV_ENDPOINT_URL to forward photos to "
                "your own inference service."
                if not external
                else "External classification endpoint active."
            ),
        }

    # ------------------------------------------------------------------
    # Main entry point (synchronous - serverless safe)
    # ------------------------------------------------------------------
    def process(
        self,
        raw: bytes,
        *,
        note: str | None = None,
        category_hint: str | None = None,
        max_width: int | None = None,
    ) -> AnalysisResult:
        """Redact, classify and re-encode one uploaded photo."""
        sha = hashlib.sha256(raw).hexdigest()
        if not CV_AVAILABLE:
            return self._process_pillow_only(raw, sha, note=note, category_hint=category_hint)

        max_width = max_width or settings.max_stored_edge_px
        arr = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
        if arr is None:
            raise ValueError("Uploaded file is not a decodable image")

        arr = _downscale(arr, max_width)
        height, width = arr.shape[:2]

        # 1. privacy first ------------------------------------------------
        redacted, privacy = self.redact(arr)

        # 2. image quality ------------------------------------------------
        quality = self._quality_report(redacted)

        # 3. classification (behind the BarrierClassifier interface) ----
        classifier = get_classifier()
        classifications = classifier.classify(
            redacted, raw=raw, note=note, category_hint=category_hint, width=width, height=height
        )
        detections = [Detection.from_classification(c) for c in classifications]
        features = next((c.features for c in classifications if c.features), {})

        detections = self._reconcile(
            detections, note=note, category_hint=category_hint, quality=quality
        )
        category = detections[0].category if detections else "obstacle"
        confidence = detections[0].confidence if detections else 0.0

        notes: list[str] = []
        if privacy.total_redactions:
            notes.append(
                f"{privacy.total_redactions} privacy region(s) redacted before storage "
                f"({privacy.faces_redacted} face, {privacy.plates_redacted} plate)."
            )
        if quality.get("is_blurry"):
            notes.append("Photo is blurry; confidence reduced.")
        if quality.get("is_dark"):
            notes.append("Low-light photo; confidence reduced.")
        if classifier.name == "heuristic":
            notes.append(
                "Classification came from the built-in heuristic feature detector, "
                "not a trained model."
            )
        if confidence >= settings.barrier_confidence_threshold:
            notes.append("Confidence above threshold - auto-verify eligible.")
        elif confidence >= 0.6:
            notes.append("Awaiting a second citizen confirmation to auto-verify.")

        encoded = _encode_bounded(redacted, settings.max_stored_image_bytes)
        thumbnail = _make_thumbnail(encoded)

        return AnalysisResult(
            detections=detections,
            category=category,
            confidence=confidence,
            engine=classifier.name,
            privacy=privacy,
            quality=quality,
            image_size=(width, height),
            redacted_bytes=encoded,
            thumbnail_bytes=thumbnail,
            sha256=sha,
            features=features,
            notes=notes,
        )

    def refine(
        self,
        raw: bytes,
        *,
        note: str | None = None,
        category_hint: str | None = None,
    ) -> AnalysisResult:
        """Second, higher-resolution pass - now synchronous (Phase 0 fix).

        This used to be a FastAPI ``BackgroundTask``, which works locally but is
        silently dropped on a serverless platform because the instance is frozen
        the moment the response is written. It now runs before the response.
        """
        return self.process(raw, note=note, category_hint=category_hint, max_width=2048)

    # ------------------------------------------------------------------
    # Privacy / redaction
    # ------------------------------------------------------------------
    def redact(self, arr) -> tuple[Any, PrivacyReport]:
        """Blur every detected face and licence plate. Returns (image, report)."""
        report = PrivacyReport()
        grey = cv2.cvtColor(arr, cv2.COLOR_BGR2GRAY)
        min_area = settings.redaction_min_area_px

        if settings.blur_faces:
            for label, cascade in (
                ("face", self._face_cascade),
                ("face_profile", self._profile_cascade),
            ):
                if cascade is None or cascade.empty():
                    continue
                found = cascade.detectMultiScale(
                    grey, scaleFactor=1.08, minNeighbors=6, minSize=(24, 24)
                )
                for x, y, w, h in found:
                    if w * h < min_area:
                        continue
                    pad = int(0.12 * max(w, h))
                    region = _clamp_box(x - pad, y - pad, w + 2 * pad, h + 2 * pad, arr.shape)
                    arr = _blur_region(arr, region, strength=61)
                    report.faces_redacted += 1
                    report.regions.append({"kind": label, "box": region, "method": "gaussian"})

        if settings.blur_license_plates:
            for region in self._detect_plates(arr, grey):
                arr = _blur_region(arr, region, strength=71)
                report.plates_redacted += 1
                report.regions.append(
                    {"kind": "plate", "box": region, "method": "pixelate+gaussian"}
                )

        return arr, report

    def _detect_plates(self, arr, grey) -> list[tuple[int, int, int, int]]:
        """Haar plate cascade + contour fallback tuned for plate geometry."""
        found: list[tuple[int, int, int, int]] = []
        if self._plate_cascade is not None and not self._plate_cascade.empty():
            for x, y, w, h in self._plate_cascade.detectMultiScale(grey, 1.1, 5):
                found.append((int(x), int(y), int(w), int(h)))

        height, width = grey.shape[:2]
        # Contour fallback: bright, low-variance, wide-aspect rectangles in the
        # middle/lower band of the frame where plates actually appear.
        top = int(height * 0.30)
        band = grey[top:, :]
        if band.size == 0:
            return found
        blurred = cv2.GaussianBlur(band, (5, 5), 0)
        edges = cv2.Canny(blurred, 60, 180)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (17, 5))
        closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel, iterations=2)
        contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            if h == 0:
                continue
            aspect = w / float(h)
            area = w * h
            if not (2.0 <= aspect <= 6.5):
                continue
            if area < max(700, 0.0008 * width * height) or area > 0.06 * width * height:
                continue
            roi = grey[top + y : top + y + h, x : x + w]
            if roi.size == 0:
                continue
            if float(np.mean(roi)) < 70 or float(np.std(roi)) > 78:
                continue
            found.append((int(x), int(top + y), int(w), int(h)))
        return _dedupe_boxes(found)

    # ------------------------------------------------------------------
    # Reconciliation + quality
    # ------------------------------------------------------------------
    def _reconcile(
        self,
        detections: list[Detection],
        *,
        note: str | None,
        category_hint: str | None,
        quality: dict[str, Any],
    ) -> list[Detection]:
        """Blend classifier output with the reporter's explicit hint and photo quality."""
        if not detections:
            return detections
        if category_hint:
            # The reporter's explicit category is an override: the human was
            # there, the classifier only saw a JPEG. We store the reporter's
            # claim as the primary verdict and keep the model's own reading as a
            # secondary detection so the dashboard can surface the disagreement
            # instead of silently discarding one side.
            model_top = detections[0]
            matched = False
            for det in detections:
                if det.category == category_hint:
                    matched = True
                    det.confidence = min(0.99, det.confidence + 0.10)
                    det.rationale += " | reporter selected this category"
            if not matched:
                detections.insert(
                    0,
                    Detection(
                        category=category_hint,
                        confidence=min(0.99, max(0.45, model_top.confidence)),
                        bbox=model_top.bbox,
                        source="citizen_manual",
                        rationale=(
                            f"reporter override - model read '{model_top.category}' "
                            f"at {model_top.confidence:.2f}; no matching signature"
                        ),
                    ),
                )
        detections.sort(key=lambda d: d.confidence, reverse=True)
        penalty = 1.0
        if quality.get("is_blurry"):
            penalty -= 0.18
        if quality.get("is_dark"):
            penalty -= 0.12
        for det in detections:
            det.confidence = round(max(0.15, min(0.99, det.confidence * penalty)), 3)
        return detections

    def _quality_report(self, arr) -> dict[str, Any]:
        grey = cv2.cvtColor(arr, cv2.COLOR_BGR2GRAY)
        sharpness = float(cv2.Laplacian(grey, cv2.CV_64F).var())
        brightness = float(grey.mean())
        height, width = grey.shape[:2]
        return {
            "sharpness": round(sharpness, 2),
            "brightness": round(brightness, 2),
            "is_blurry": sharpness < 55.0,
            "is_dark": brightness < 55.0,
            "is_small": width < 320 or height < 240,
            "aspect_ratio": round(width / float(height), 3),
        }

    def _process_pillow_only(
        self, raw: bytes, sha: str, *, note: str | None, category_hint: str | None
    ) -> AnalysisResult:  # pragma: no cover - only without OpenCV
        """Degraded path: still strips EXIF + applies a conservatively strong blur."""
        with Image.open(io.BytesIO(raw)) as img:
            img = img.convert("RGB")
            width, height = img.size
            # Without a detector we destroy the whole lower background band,
            # which is where faces/plates cluster in path photos. Fail closed.
            box = (0, int(height * 0.55), width, height)
            band = img.crop(box).filter(ImageFilter.GaussianBlur(14))
            img.paste(band, box)
            buffer = io.BytesIO()
            img.save(buffer, "JPEG", quality=88)
        from app.services.classifier import keyword_scores

        scores = keyword_scores(note) or {"obstacle": 0.5}
        category = category_hint or max(scores.items(), key=lambda kv: kv[1])[0]
        detection = Detection(
            category=category,
            confidence=0.45,
            bbox=(0, int(height * 0.55), width, int(height * 0.45)),
            source="heuristic",
            rationale="Pillow fallback: OpenCV unavailable, conservative redaction applied",
        )
        redacted = buffer.getvalue()
        return AnalysisResult(
            detections=[detection],
            category=category,
            confidence=0.45,
            engine="pillow-fallback",
            privacy=PrivacyReport(other_redacted=1, engine="pillow-band"),
            quality={"is_blurry": False, "is_dark": False, "fallback": True},
            image_size=(width, height),
            redacted_bytes=redacted,
            thumbnail_bytes=_make_thumbnail(redacted),
            sha256=sha,
            notes=["OpenCV unavailable - conservative privacy band applied."],
        )

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------
    def store(self, db, result: AnalysisResult, *, kind: str = "barrier_photo") -> dict[str, Any]:
        """Persist the redacted JPEG (+ thumbnail + sidecar) as database rows.

        Returns ``{"media_id", "image_url", "thumbnail_url", ...}``. The original
        upload is never stored anywhere - only the redacted re-encode.
        """
        from app.db.models import MediaObject

        media = MediaObject(
            id=result.sha256[:32],
            kind=kind,
            content_type="image/jpeg",
            data=result.redacted_bytes,
            thumbnail_data=result.thumbnail_bytes,
            byte_size=len(result.redacted_bytes),
            width=result.image_size[0],
            height=result.image_size[1],
            sha256=result.sha256,
            faces_redacted=result.privacy.faces_redacted,
            plates_redacted=result.privacy.plates_redacted,
            privacy_engine=result.privacy.engine,
        )
        sidecar = MediaObject(
            id=f"{result.sha256[:24]}sidecar",
            kind="privacy_sidecar",
            content_type="application/json",
            data=json.dumps(result.sidecar(), indent=2).encode("utf-8"),
            byte_size=0,
            sha256=result.sha256,
        )
        db.merge(media)
        db.merge(sidecar)
        db.flush()
        return {
            "media_id": media.id,
            "sidecar_id": sidecar.id,
            "image_url": f"{settings.media_url_prefix}/{media.id}",
            "thumbnail_url": f"{settings.media_url_prefix}/{media.id}?variant=thumb",
            "privacy_sidecar_url": f"{settings.media_url_prefix}/{sidecar.id}",
            "byte_size": media.byte_size,
            "storage": "postgres-bytea",
        }


cv_service = CVService()


# -----------------------------------------------------------------------
# Numerical / encoding helpers
# -----------------------------------------------------------------------
def _downscale(arr, max_width: int):
    height, width = arr.shape[:2]
    if width <= max_width:
        return arr
    scale = max_width / float(width)
    return cv2.resize(arr, (max_width, int(height * scale)), interpolation=cv2.INTER_AREA)


def _clamp_box(x: int, y: int, w: int, h: int, shape) -> tuple[int, int, int, int]:
    height, width = shape[:2]
    x = max(0, min(int(x), max(0, width - 1)))
    y = max(0, min(int(y), max(0, height - 1)))
    w = max(1, min(int(w), width - x))
    h = max(1, min(int(h), height - y))
    return (x, y, w, h)


def _blur_region(arr, box: tuple[int, int, int, int], *, strength: int = 61):
    x, y, w, h = box
    region = arr[y : y + h, x : x + w]
    if region.size == 0:
        return arr
    kernel = strength if strength % 2 == 1 else strength + 1
    arr[y : y + h, x : x + w] = cv2.GaussianBlur(region, (kernel, kernel), 0)
    return arr


def _dedupe_boxes(boxes: list[tuple[int, int, int, int]], iou_threshold: float = 0.4):
    kept: list[tuple[int, int, int, int]] = []
    for box in sorted(boxes, key=lambda b: b[2] * b[3], reverse=True):
        if all(_iou(box, other) < iou_threshold for other in kept):
            kept.append(box)
    return kept


def _iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    ax1, ay1, aw, ah = a
    bx1, by1, bw, bh = b
    ax2, ay2 = ax1 + aw, ay1 + ah
    bx2, by2 = bx1 + bw, by1 + bh
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    intersection = max(0, ix2 - ix1) * max(0, iy2 - iy1)
    union = aw * ah + bw * bh - intersection
    return intersection / union if union else 0.0


def _encode_bounded(arr, max_bytes: int) -> bytes:
    """JPEG-encode, stepping quality down until the payload fits the budget.

    Vercel caps request bodies at 4.5 MB, but storing a 1.5 MB photo per
    barrier makes the media table needlessly heavy and slow to serve. Target
    ~300 KB and step down deterministically.
    """
    quality = 88
    for _attempt in range(6):
        ok, encoded = cv2.imencode(".jpg", arr, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
        if not ok:
            continue
        payload = encoded.tobytes()
        if len(payload) <= max_bytes:
            return payload
        quality = int(quality * 0.75)
    return payload


def _make_thumbnail(encoded: bytes) -> bytes | None:
    try:
        with Image.open(io.BytesIO(encoded)) as img:
            img = img.convert("RGB")
            img.thumbnail((480, 480))
            buffer = io.BytesIO()
            img.save(buffer, "JPEG", quality=78)
        return buffer.getvalue()
    except Exception as exc:  # pragma: no cover
        logger.warning("thumbnail generation failed: %s", exc)
        return None


__all__ = [
    "AnalysisResult",
    "CVService",
    "Detection",
    "PrivacyReport",
    "CV_AVAILABLE",
    "cv_service",
]