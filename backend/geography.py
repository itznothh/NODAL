"""Pure geographic filtering and public aggregate helpers.

These helpers never access MongoDB directly. Callers provide registry documents
and complaint rows, making coordinate/geometry behavior testable offline.
"""
import math
import numbers
from collections import Counter

import numpy as np
from sklearn.cluster import DBSCAN


PUBLIC_MIN_COUNT = 5
HOTSPOT_RADIUS_KM = 0.4
EARTH_RADIUS_KM = 6371.0088
PUBLIC_CENTER_DECIMAL_PLACES = 3


def valid_longitude_latitude(coordinates):
    """Validate a two-value GeoJSON pair; return numeric (longitude, latitude)."""
    if not isinstance(coordinates, (list, tuple)) or len(coordinates) != 2:
        return None
    longitude, latitude = coordinates
    if (isinstance(longitude, bool) or isinstance(latitude, bool) or
            not isinstance(longitude, numbers.Real) or not isinstance(latitude, numbers.Real)):
        return None
    try:
        longitude, latitude = float(longitude), float(latitude)
    except (OverflowError, TypeError, ValueError):
        return None
    if (not math.isfinite(longitude) or not math.isfinite(latitude) or
            not -180 <= longitude <= 180 or not -90 <= latitude <= 90):
        return None
    return longitude, latitude


def valid_geojson_point(location):
    """Return valid (longitude, latitude), retaining legacy type-less Points."""
    if not isinstance(location, dict) or location.get("type", "Point") != "Point":
        return None
    return valid_longitude_latitude(location.get("coordinates"))


def _point_on_segment(point, start, end, epsilon=1e-10):
    x, y = point
    x1, y1 = start
    x2, y2 = end
    cross = (x - x1) * (y2 - y1) - (y - y1) * (x2 - x1)
    if abs(cross) > epsilon:
        return False
    return (min(x1, x2) - epsilon <= x <= max(x1, x2) + epsilon and
            min(y1, y2) - epsilon <= y <= max(y1, y2) + epsilon)


def _ring_location(point, ring):
    """Return (inside, boundary) using ray casting, including explicit edges."""
    if not isinstance(ring, (list, tuple)) or len(ring) < 4:
        return False, False
    inside = False
    x, y = point
    try:
        for index in range(len(ring) - 1):
            start, end = ring[index], ring[index + 1]
            if _point_on_segment(point, start, end):
                return True, True
            x1, y1 = start[:2]
            x2, y2 = end[:2]
            if (y1 > y) != (y2 > y):
                crossing_x = (x2 - x1) * (y - y1) / (y2 - y1) + x1
                if x < crossing_x:
                    inside = not inside
    except (TypeError, ValueError, IndexError, ZeroDivisionError):
        return False, False
    return inside, False


def point_in_polygon(longitude_latitude, polygon_coordinates):
    """Point-in-Polygon with boundary included and hole interiors excluded."""
    if not isinstance(polygon_coordinates, (list, tuple)) or not polygon_coordinates:
        return False
    point = longitude_latitude
    exterior_inside, exterior_edge = _ring_location(point, polygon_coordinates[0])
    if not exterior_inside:
        return False
    if exterior_edge:
        return True
    for hole in polygon_coordinates[1:]:
        hole_inside, hole_edge = _ring_location(point, hole)
        if hole_inside and not hole_edge:
            return False
        # The ring itself is a polygon boundary; edge points are included.
    return True


def point_in_geometry(longitude_latitude, geometry):
    """Test a point against GeoJSON Polygon or MultiPolygon coordinates."""
    if not isinstance(geometry, dict):
        return False
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if geometry_type == "Polygon":
        return point_in_polygon(longitude_latitude, coordinates)
    if geometry_type == "MultiPolygon" and isinstance(coordinates, (list, tuple)):
        return any(point_in_polygon(longitude_latitude, polygon) for polygon in coordinates)
    return False


def filter_complaints_to_region(documents, boundary):
    """Return rows with valid points inside geometry; invalid/unlocated rows drop out."""
    included = []
    for document in documents:
        if not isinstance(document, dict):
            continue
        point = valid_geojson_point(document.get("location"))
        if point is not None and point_in_geometry(point, boundary):
            included.append(document)
    return included


def _public_center(items, all_points):
    latitude = round(float(np.mean([point[0] for _, point in items])), PUBLIC_CENTER_DECIMAL_PLACES)
    longitude = round(float(np.mean([point[1] for _, point in items])), PUBLIC_CENTER_DECIMAL_PLACES)
    exact_points = set(all_points)
    if (longitude, latitude) in exact_points:
        direction = 1 if longitude <= 0 else -1
        for offset in range(1, len(exact_points) + 2):
            candidate = round(longitude + direction * offset / 1000, PUBLIC_CENTER_DECIMAL_PLACES)
            if -180 <= candidate <= 180 and (candidate, latitude) not in exact_points:
                longitude = candidate
                break
    return latitude, longitude


def hotspots_for_documents(documents):
    """Build existing-style DBSCAN hotspot aggregates from supplied rows."""
    eligible = []
    for document in documents:
        if not isinstance(document, dict) or document.get("status") in {"resolved", "disputed"}:
            continue
        point = valid_geojson_point(document.get("location"))
        if point is not None:
            eligible.append((document, point))
    if len(eligible) < PUBLIC_MIN_COUNT:
        return []

    # Stored GeoJSON is [longitude, latitude]; haversine DBSCAN needs
    # [latitude, longitude] radians.
    points = [[latitude, longitude] for _, (longitude, latitude) in eligible]
    labels = DBSCAN(eps=HOTSPOT_RADIUS_KM / EARTH_RADIUS_KM,
                    min_samples=PUBLIC_MIN_COUNT, metric="haversine",
                    algorithm="ball_tree").fit_predict(np.radians(points))
    clusters = {}
    for item, point, label in zip(eligible, points, labels):
        if label != -1:
            clusters.setdefault(int(label), []).append((item[0], point))

    all_points = [(longitude, latitude) for _, (longitude, latitude) in eligible]
    results = []
    for label, items in clusters.items():
        lat, lng = _public_center(items, all_points)
        categories = [doc.get("category") if isinstance(doc.get("category"), str) and doc.get("category").strip()
                      else "unclassified" for doc, _ in items]
        results.append({"cluster_id": label, "count": len(items),
                        "center": {"lat": lat, "lng": lng},
                        "top_category": Counter(categories).most_common(1)[0][0],
                        "high_priority": sum(doc.get("priority") == "high" for doc, _ in items)})
    return sorted(results, key=lambda cluster: cluster["count"], reverse=True)


def _suppress_small_count(value):
    return value if value >= PUBLIC_MIN_COUNT else None


def region_overview_metrics(documents):
    total = len(documents)
    open_documents = [doc for doc in documents if doc.get("status") not in {"resolved", "disputed"}]
    raw = {
        "total_complaints": total,
        "open_complaints": len(open_documents),
        "high_priority_open": sum(doc.get("priority") == "high" for doc in open_documents),
        "hotspot_count": len(hotspots_for_documents(open_documents)),
    }
    suppressed = [key for key, value in raw.items() if value < PUBLIC_MIN_COUNT]
    # If the entire region is sparse, suppress every count to prevent simple
    # differencing from revealing a small total.
    if total < PUBLIC_MIN_COUNT:
        suppressed = list(raw)
    metrics = {key: (None if key in suppressed else value) for key, value in raw.items()}
    return metrics, suppressed
