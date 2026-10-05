"""Great-circle geometry helpers shared by routing, dedupe and CV geotagging."""

from __future__ import annotations

import math

EARTH_RADIUS_M = 6_371_008.8


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in metres."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = phi2 - phi1
    d_lambda = math.radians(lng2 - lng1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def bounding_box(lat: float, lng: float, radius_m: float) -> tuple[float, float, float, float]:
    """Return (min_lat, min_lng, max_lat, max_lng) for a radius around a point.

    Used as a cheap, index-friendly pre-filter before exact haversine maths so
    the SQLite path never has to scan the whole barriers table.
    """
    d_lat = radius_m / 111_320.0
    cos_lat = max(0.05, math.cos(math.radians(lat)))
    d_lng = radius_m / (111_320.0 * cos_lat)
    return (lat - d_lat, lng - d_lng, lat + d_lat, lng + d_lng)


def bearing_deg(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Initial compass bearing (0-360, 0 = north) from point 1 to point 2."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_lambda = math.radians(lng2 - lng1)
    x = math.sin(d_lambda) * math.cos(phi2)
    y = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(
        d_lambda
    )
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


def compass_label(bearing: float) -> str:
    """Turn a bearing into a human/voice-friendly cardinal direction."""
    sectors = [
        "north",
        "north-east",
        "east",
        "south-east",
        "south",
        "south-west",
        "west",
        "north-west",
    ]
    return sectors[int((bearing + 22.5) % 360 // 45)]


def turn_delta_deg(start_bearing: float, end_bearing: float) -> float:
    """Signed shortest angular change, negative = left, positive = right."""
    delta = (end_bearing - start_bearing + 540.0) % 360.0 - 180.0
    return delta


def polyline_length_m(coords: list[tuple[float, float]]) -> float:
    """Total length of a (lat, lng) polyline in metres."""
    return sum(
        haversine_m(coords[i][0], coords[i][1], coords[i + 1][0], coords[i + 1][1])
        for i in range(len(coords) - 1)
    )


def path_similarity(a: list[tuple[float, float]], b: list[tuple[float, float]]) -> float:
    """Average symmetric point-to-set distance between two polylines.

    Cheap stand-in for a Hausdorff distance, used to detect duplicate citizen
    reports that describe the *same* stretch of pathway from different angles.
    """
    if not a or not b:
        return float("inf")

    def _directed(src: list[tuple[float, float]], dst: list[tuple[float, float]]) -> float:
        total = 0.0
        for point in src:
            total += min(haversine_m(point[0], point[1], other[0], other[1]) for other in dst)
        return total / len(src)

    return (_directed(a, b) + _directed(b, a)) / 2.0
