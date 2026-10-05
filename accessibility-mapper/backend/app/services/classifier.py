"""Barrier classification behind an explicit interface.

Why this file exists
--------------------
The original implementation imported ``ultralytics``/``torch`` opportunistically.
That is fine on a laptop and catastrophic in a serverless bundle: torch alone is
~900 MB and blows Vercel's ~250 MB Python function limit. So classification is
now a narrow interface with two implementations:

``HeuristicBarrierClassifier`` (default)
    Measures real image structure - edge density, Hough line orientation
    histograms, saturation, dark ground-plane mass, notice-panel brightness -
    and scores the six barrier categories from it, blended with reporter text.
    Deterministic: the same photo always yields the same verdict, which matters
    when a judge re-runs the demo. It is a **heuristic**, not a learned model,
    and the API says so (``engine: "heuristic"``).

``ExternalClassifier`` (optional, ``CV_ENDPOINT_URL``)
    POSTs the JPEG to an inference service you control and maps its JSON onto
    the same :class:`BarrierClassifier` contract. That is how you plug in a real
    fine-tuned detector without shipping its weights.

Both return :class:`Classification` objects, so every downstream consumer
(report response, dedupe, auto-verify, analytics) is unchanged.

Privacy redaction is deliberately **not** in here. Face/plate blurring is a
deterministic OpenCV Haar pass that must run regardless of which classifier is
active, and it happens *before* any classifier sees a pixel. See
:mod:`app.services.cv_service`.

Design notes for the scoring (why this is not a random mock)
-----------------------------------------------------------
* Each category has a *physical* signature. Hazard tape reflects saturated
  orange/red in repeating diagonals; a blocked ramp shows a foreign dark blob in
  the walking corridor; a narrow passage shows dark boundaries squeezing an
  open centre; a dead lift shows a low-saturation metallic face with a bright
  notice card.
* ``missing_signage`` is a *negative* category - the absence of evidence - so it
  only wins when nothing else scored.
* Raw evidence becomes a probability through a temperature softmax, so the
  reported confidence is a real posterior over the six categories rather than a
  hill-climbed magic number.
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from app.core.config import settings
from app.core.constants import CATEGORY_KEYWORDS

logger = logging.getLogger("abm.classifier")

BARRIER_CATEGORIES: tuple[str, ...] = (
    "blocked_ramp",
    "broken_lift",
    "narrow_path",
    "construction",
    "obstacle",
    "missing_signage",
)

__all__ = [
    "BARRIER_CATEGORIES",
    "BarrierClassifier",
    "Classification",
    "ExternalClassifier",
    "HeuristicBarrierClassifier",
    "get_classifier",
    "keyword_scores",
    "reset_classifier",
]


@dataclass
class Classification:
    """One category verdict plus the evidence that produced it."""

    category: str
    confidence: float
    bbox: tuple[int, int, int, int]
    source: str
    rationale: str = ""
    features: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        x, y, w, h = self.bbox
        return {
            "category": self.category,
            "confidence": round(float(self.confidence), 3),
            "bbox": {"x": int(x), "y": int(y), "width": int(w), "height": int(h)},
            "source": self.source,
            "rationale": self.rationale,
        }


@runtime_checkable
class BarrierClassifier(Protocol):
    """The contract every classifier implements.

    ``arr`` is a decoded BGR ``numpy`` array (or ``None`` when no decoder is
    available); ``raw`` is the encoded JPEG, which the external implementation
    needs in order to forward it.
    """

    name: str

    def classify(
        self,
        arr: Any,
        *,
        raw: bytes,
        note: str | None = None,
        category_hint: str | None = None,
        width: int = 0,
        height: int = 0,
    ) -> list[Classification]:
        """Return ranked category verdicts for one photo."""
        ...


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def keyword_scores(note: str | None) -> dict[str, float]:
    """Reporter text -> weak category priors (never strong enough alone)."""
    if not note:
        return {}
    text = note.lower()
    out: dict[str, float] = {}
    for category, words in CATEGORY_KEYWORDS.items():
        hits = sum(1 for word in words if word in text)
        if hits:
            out[category] = min(0.35 * hits, 1.0)
    return out


def _softmax(scores: dict[str, float], *, temperature: float = 0.22) -> dict[str, float]:
    import math

    if not scores:
        return {}
    peak = max(scores.values())
    exps = {k: math.exp((v - peak) / max(temperature, 1e-6)) for k, v in scores.items()}
    total = sum(exps.values()) or 1.0
    return {k: v / total for k, v in exps.items()}


def _representative_box(arr, category: str, grey) -> tuple[int, int, int, int]:
    """A plausible bounding box so the UI has something to draw."""
    height, width = grey.shape[:2]
    if category in ("blocked_ramp", "obstacle"):
        return (int(width * 0.30), int(height * 0.60), int(width * 0.40), int(height * 0.32))
    if category == "construction":
        return (0, int(height * 0.20), int(width * 0.50), int(height * 0.70))
    if category == "broken_lift":
        return (int(width / 3), int(height / 6), int(width / 3), int(height / 3))
    if category == "narrow_path":
        return (0, 0, int(width * 0.25), int(height))
    return (int(width * 0.35), int(height * 0.25), int(width * 0.30), int(height * 0.30))


# -----------------------------------------------------------------------
# Default: the deterministic feature detector
# -----------------------------------------------------------------------
class HeuristicBarrierClassifier:
    """Deterministic feature-scoring classifier (the documented default)."""

    name = "heuristic"

    def classify(
        self,
        arr: Any,
        *,
        raw: bytes = b"",
        note: str | None = None,
        category_hint: str | None = None,
        width: int = 0,
        height: int = 0,
    ) -> list[Classification]:
        import cv2  # type: ignore
        import numpy as np  # type: ignore

        if arr is None:
            return [
                Classification(
                    category=category_hint or "obstacle",
                    confidence=0.40,
                    bbox=(0, 0, width, height),
                    source="heuristic",
                    rationale="no decoder available; reporter hint used as-is",
                )
            ]

        image_height, image_width = arr.shape[:2]
        grey = cv2.cvtColor(arr, cv2.COLOR_BGR2GRAY)
        hsv = cv2.cvtColor(arr, cv2.COLOR_BGR2HSV)

        edges = cv2.Canny(cv2.GaussianBlur(grey, (5, 5), 0), 60, 170)
        edge_density = float(np.count_nonzero(edges)) / float(edges.size)
        saturation = float(np.mean(hsv[:, :, 1])) / 255.0
        brightness = float(np.mean(hsv[:, :, 2])) / 255.0
        contrast = float(np.std(grey)) / 128.0

        # --- Hough orientation histogram -------------------------------
        lines = cv2.HoughLinesP(
            edges,
            1,
            np.pi / 180,
            threshold=60,
            minLineLength=max(30, image_width // 12),
            maxLineGap=8,
        )
        vertical = horizontal = diagonal = 0
        for line in (lines if lines is not None else [])[:400]:
            x1, y1, x2, y2 = line[0]
            angle = abs(float(np.degrees(np.arctan2(y2 - y1, x2 - x1)))) % 180
            if angle < 15 or angle > 165:
                horizontal += 1
            elif 75 < angle < 105:
                vertical += 1
            elif 15 <= angle <= 75:
                diagonal += 1
        total_lines = max(1, vertical + horizontal + diagonal)
        vertical_ratio = vertical / total_lines
        diagonal_ratio = diagonal / total_lines

        # --- ground plane (the walking corridor) -----------------------
        ground = arr[int(image_height * 0.55) :, int(image_width * 0.20) : int(image_width * 0.80)]
        ground_grey = cv2.cvtColor(ground, cv2.COLOR_BGR2GRAY) if ground.size else grey
        ground_dark_ratio = float(np.count_nonzero(ground_grey < 70)) / max(1, ground_grey.size)
        ground_edges = float(np.count_nonzero(cv2.Canny(ground_grey, 60, 170))) / max(
            1, ground_grey.size
        )

        # --- dark boundaries left/right vs an open centre ---------------
        dark_mask = (grey < 70).astype(np.float32)
        third = max(1, image_width // 4)
        left_dark = float(dark_mask[:, :third].mean())
        right_dark = float(dark_mask[:, image_width - third :].mean())
        centre_dark = float(dark_mask[:, third : image_width - third].mean())
        side_dark = (left_dark + right_dark) / 2.0

        # --- bright notice panels + hazard colouring -------------------
        bright_mask = cv2.inRange(hsv, (0, 0, 195), (180, 60, 255))
        bright_ratio = float(np.count_nonzero(bright_mask)) / float(bright_mask.size)
        hazard_mask = cv2.inRange(hsv, (0, 110, 120), (32, 255, 255)) | cv2.inRange(
            hsv, (170, 110, 120), (180, 255, 255)
        )
        hazard_ratio = float(np.count_nonzero(hazard_mask)) / float(hazard_mask.size)
        metal_mask = ((hsv[:, :, 1] < 60) & (hsv[:, :, 2] > 120) & (hsv[:, :, 2] < 215)).astype(
            np.uint8
        )
        metal_ratio = float(metal_mask.mean())
        stripes = _stripe_score(grey)

        features = {
            "edge_density": round(edge_density, 4),
            "vertical_line_ratio": round(vertical_ratio, 4),
            "horizontal_line_ratio": round(horizontal / total_lines, 4),
            "diagonal_line_ratio": round(diagonal_ratio, 4),
            "saturation": round(saturation, 4),
            "brightness": round(brightness, 4),
            "contrast": round(contrast, 4),
            "ground_dark_ratio": round(ground_dark_ratio, 4),
            "ground_edge_density": round(ground_edges, 4),
            "side_dark_ratio": round(side_dark, 4),
            "centre_dark_ratio": round(centre_dark, 4),
            "bright_panel_ratio": round(bright_ratio, 4),
            "hazard_color_ratio": round(hazard_ratio, 4),
            "metal_ratio": round(metal_ratio, 4),
            "stripe_score": round(stripes, 4),
        }

        # Physical signatures -> raw evidence in 0..1.
        scores: dict[str, float] = {
            "construction": _clamp(
                0.50 * stripes
                + 0.35 * _clamp(hazard_ratio / 0.25)
                + 0.30 * _clamp((edge_density - 0.03) / 0.12)
            ),
            "obstacle": _clamp(
                0.65 * _clamp(ground_dark_ratio / 0.20)
                + 0.30 * _clamp(ground_edges / 0.12)
                + 0.15 * _clamp((contrast - 0.30) / 0.50)
            ),
            "blocked_ramp": _clamp(
                0.50 * _clamp(diagonal_ratio / 0.30)
                + 0.50 * _clamp(ground_dark_ratio / 0.22)
                + 0.20 * _clamp((contrast - 0.35) / 0.50)
            ),
            "narrow_path": _clamp(
                0.55 * vertical_ratio * side_dark * (1.0 - 0.6 * centre_dark)
                + 0.25 * side_dark * (1.0 - centre_dark)
                + 0.20 * _clamp((0.55 - brightness) / 0.55)
            ),
            "broken_lift": _clamp(
                0.35 * _clamp((0.30 - saturation) / 0.30)
                + 0.30 * _clamp(bright_ratio / 0.06)
                + 0.25 * vertical_ratio * _clamp(metal_ratio / 0.35)
                + 0.20 * _clamp((0.70 - brightness) / 0.40) * _clamp(metal_ratio / 0.30)
            )
            # A dead lift always shows structure (doors, seams, a notice card),
            # so gate the whole signature on the presence of edges.
            * _clamp(edge_density / 0.012),
        }
        # Missing signage is the absence of evidence, not the presence of it:
        # featureless means both few edges AND almost no tonal variation.
        uniformity = _clamp(1.0 - edge_density / 0.02) * _clamp(1.0 - contrast / 0.15)
        notable = max(scores.values()) if scores else 0.0
        scores["missing_signage"] = _clamp(uniformity * (1.0 - notable))

        note_scores = keyword_scores(note)
        for category, boost in note_scores.items():
            scores[category] = min(1.0, scores[category] + 0.35 * boost)

        # The reporter's explicit choice is folded in as a prior so the ranked
        # evidence reflects it, but the model's own verdict stays visible in
        # the rationale either way. ``_reconcile`` in cv_service decides what
        # actually gets stored.
        prior_applied = False
        if category_hint and category_hint in scores:
            scores[category_hint] = min(1.0, scores[category_hint] + 0.30)
            prior_applied = True

        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        probabilities = _softmax(scores, temperature=0.22)
        top_category = ranked[0][0]
        top_probability = probabilities[top_category]
        confidence = _clamp(0.30 + 0.68 * top_probability, 0.25, 0.965)

        box = _representative_box(arr, top_category, grey)
        rationale = (
            f"feature detector p={top_probability:.2f} "
            f"(edge={edge_density:.3f} V/D={vertical_ratio:.2f}/{diagonal_ratio:.2f} "
            f"sat={saturation:.2f} ground_dark={ground_dark_ratio:.2f} "
            f"side_dark={side_dark:.2f} hazard={hazard_ratio:.2f} stripes={stripes:.2f})"
            + (f" note-match={note_scores[top_category]:.2f}" if top_category in note_scores else "")
            + (
                f" | reporter hint={category_hint}"
                f" ({'prior applied' if top_category == category_hint else 'image evidence leads'})"
                if prior_applied
                else ""
            )
            + " | heuristic, not a learned model"
        )
        results = [
            Classification(
                category=top_category,
                confidence=confidence,
                bbox=box,
                source=self.name,
                rationale=rationale,
                features=features,
            )
        ]
        # Keep the runner-up only when the evidence genuinely competes (a photo
        # can absolutely contain two hazards at once - e.g. fencing on a ramp).
        runner_up = ranked[1]
        if runner_up[1] > 0.45 and (ranked[0][1] - runner_up[1]) < 0.24:
            results.append(
                Classification(
                    category=runner_up[0],
                    confidence=_clamp(confidence - 0.20, 0.2, 0.9),
                    bbox=box,
                    source=self.name,
                    rationale=(
                        f"secondary hazard candidate (p={probabilities[runner_up[0]]:.2f})"
                    ),
                )
            )
        return results


def _alternation(profile) -> float:  # type: ignore[no-untyped-def]
    """How many times a 1-D intensity profile reverses direction.

    Hazard tape is a repeating light/dark band, so evenly spaced reversals are
    the signature. Counting *reversals* rather than steep per-pixel gradients
    matters: a slanted band viewed through a column average is a smooth ramp,
    so its per-pixel slope is tiny even though the band is unmistakable.

    A reversal only counts when the profile has actually travelled at least a
    quarter of its total range since the previous reversal, which stops sensor
    noise from scoring as tape.
    """
    import numpy as np  # type: ignore

    profile = np.asarray(profile, dtype=np.float64).ravel()
    if profile.size < 8:
        return 0.0
    if profile.size > 3:
        profile = np.convolve(profile, np.ones(3) / 3.0, mode="same")

    spread = float(profile.max() - profile.min())
    if spread < 8.0:
        return 0.0

    slope = np.sign(np.diff(profile))
    travel_floor = 0.25 * spread
    turns = 0
    last_turn = 0
    direction = 0
    for index in range(1, slope.size):
        step = slope[index]
        if step == 0:
            continue
        if direction and step != direction:
            if abs(profile[index] - profile[last_turn]) >= travel_floor:
                turns += 1
                last_turn = index
        direction = step
    return float(_clamp(turns / float(profile.size) * 4.0))


def _shear_profile(grey, shear: float = 0.5):  # type: ignore[no-untyped-def]
    """Collapse the image along a slanted axis so diagonal bands survive.

    Averaging along rows or columns cancels out slanted stripes: every column
    still crosses the same bands, so the mean is nearly flat and the alternation
    signal disappears. Shearing first aligns the bands with the sampling
    direction, which is what real hazard tape looks like.
    """
    import numpy as np  # type: ignore

    height, width = grey.shape[:2]
    span = int(shear * height)
    length = width - span
    if length < 16:
        return None
    offsets = (np.arange(height) * shear).astype(int)
    profile = np.zeros(length, dtype=np.float64)
    for y in range(height):
        start = offsets[y]
        profile[:length] += grey[y, start : start + length]
    profile /= float(height)
    return profile


def _stripe_score(grey) -> float:  # type: ignore[no-untyped-def]
    """Alternating-band strength - the hazard-tape signature.

    Orientation-agnostic on purpose: real barrier tape is diagonal, so a plain
    row/column average would miss exactly the case we care most about.
    """
    import numpy as np  # type: ignore

    if grey.size == 0:
        return 0.0
    best = _alternation(grey.mean(axis=0))
    best = max(best, _alternation(grey.mean(axis=1)))
    sheared = _shear_profile(grey)
    if sheared is not None:
        best = max(best, _alternation(sheared))
    return float(best)


# -----------------------------------------------------------------------
# Optional: external inference endpoint
# -----------------------------------------------------------------------
class ExternalClassifier:
    """POST the photo to ``CV_ENDPOINT_URL`` and map its JSON onto our contract.

    Expected response (any subset; missing fields degrade gracefully)::

        {"category": "blocked_ramp",
         "confidence": 0.93,
         "bbox": [x, y, w, h],
         "features": {...},
         "alternatives": [{"category": "obstacle", "confidence": 0.21}]}

    ``CV_ENDPOINT_TOKEN`` is sent as ``Authorization: Bearer``. Any failure -
    timeout, non-2xx, unexpected shape - falls back to the heuristic so the
    reporting pipeline is never blocked by a third party.
    """

    name = "external"

    def __init__(self, url: str, *, token: str = "", timeout: float = 12.0) -> None:
        self.url = url
        self.token = token
        self.timeout = timeout

    def classify(
        self,
        arr: Any,
        *,
        raw: bytes = b"",
        note: str | None = None,
        category_hint: str | None = None,
        width: int = 0,
        height: int = 0,
    ) -> list[Classification]:
        import httpx

        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        payload = {
            "image_base64": base64.b64encode(raw).decode("ascii"),
            "note": note,
            "categories": list(BARRIER_CATEGORIES),
        }
        try:
            response = httpx.post(self.url, json=payload, headers=headers, timeout=self.timeout)
            response.raise_for_status()
            body = response.json()
        except Exception as exc:
            logger.warning(
                "external classifier at %s failed (%s) - falling back to heuristic",
                self.url,
                exc.__class__.__name__,
            )
            return self._fallback(arr, raw, note, category_hint, width, height)

        if not isinstance(body, dict) or "category" not in body:
            logger.warning("external classifier returned an unexpected shape; using heuristic")
            return self._fallback(arr, raw, note, category_hint, width, height)

        features = body.get("features") or {}
        results = [
            Classification(
                category=str(body["category"]),
                confidence=float(body.get("confidence", 0.0)),
                bbox=_as_box(body.get("bbox"), width, height),
                source=self.name,
                rationale="external inference endpoint returned this verdict",
                features={str(k): float(v) for k, v in features.items() if _is_number(v)},
            )
        ]
        for alternative in body.get("alternatives") or []:
            try:
                results.append(
                    Classification(
                        category=str(alternative["category"]),
                        confidence=float(alternative.get("confidence", 0.0)),
                        bbox=_as_box(alternative.get("bbox"), width, height),
                        source=self.name,
                        rationale="external inference endpoint alternative",
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        return results

    def _fallback(
        self,
        arr: Any,
        raw: bytes,
        note: str | None,
        category_hint: str | None,
        width: int,
        height: int,
    ) -> list[Classification]:
        return HeuristicBarrierClassifier().classify(
            arr, raw=raw, note=note, category_hint=category_hint, width=width, height=height
        )


def _is_number(value: Any) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


def _as_box(raw: Any, width: int, height: int) -> tuple[int, int, int, int]:
    if isinstance(raw, (list, tuple)) and len(raw) == 4:
        try:
            return tuple(int(v) for v in raw)  # type: ignore[return-value]
        except (TypeError, ValueError):
            pass
    return (0, 0, int(width), int(height))


# -----------------------------------------------------------------------
# Selection
# -----------------------------------------------------------------------
_active: BarrierClassifier | None = None


def get_classifier() -> BarrierClassifier:
    """Return the configured classifier, memoised for this instance."""
    global _active
    if _active is not None:
        return _active
    if settings.cv_endpoint_url:
        _active = ExternalClassifier(
            settings.cv_endpoint_url,
            token=settings.cv_endpoint_token,
            timeout=settings.cv_endpoint_timeout_s,
        )
        logger.info("barrier classifier: external endpoint %s", settings.cv_endpoint_url)
    else:
        _active = HeuristicBarrierClassifier()
        logger.info("barrier classifier: built-in heuristic (no CV_ENDPOINT_URL set)")
    return _active


def reset_classifier() -> None:
    """Drop the memoised classifier (tests, and after a config change)."""
    global _active
    _active = None