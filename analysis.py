"""Pure selection, exploration and statistics for finite, parsed records.

No files are opened here and nothing is logged. Keep each room/sensor/metric
separate: taking a mean across temperatures, humidities and pressures is invalid.
"""
from collections.abc import Iterable
from datetime import datetime
from statistics import fmean, median, stdev


def select_series(readings: Iterable[dict], room: str, sensor_id: str,
                  metric: str) -> list[dict]:
    """Select exactly one series, consuming the input iterable once."""
    # The list is new; its dictionaries are shared and must be treated as read-only.
    return [r for r in readings
            if (r["room"], r["sensor_id"], r["metric"]) == (room, sensor_id, metric)]


def basic_summary(values: list[float]) -> dict:
    """Count, mean, minimum and maximum for one finite numerical series."""
    if not values:
        # None means unavailable, not a measurement whose numerical value is zero.
        return {"count": 0, "mean": None, "minimum": None, "maximum": None}
    return {"count": len(values), "mean": fmean(values),
            "minimum": min(values), "maximum": max(values)}


def _group_by_series(readings: list[dict]) -> dict:
    """Share the small grouping step used by exploration and per-series summaries."""
    groups = {}
    for reading in readings:
        key = (reading["room"], reading["sensor_id"], reading["metric"])
        if key not in groups:
            groups[key] = []
        # Parsed input already obeys this; the guard also protects direct callers.
        if groups[key] and groups[key][0]["unit"] != reading["unit"]:
            raise ValueError(f"Inconsistent units within series {key!r}.")
        groups[key].append(reading)
    return groups


def explore_data(readings: list[dict]) -> dict:
    """SOLUTION E1: describe identity, coverage and counts without mixing quantities."""
    groups = _group_by_series(readings)
    series = []
    for room, sensor_id, metric in sorted(groups):
        group = groups[(room, sensor_id, metric)]
        series.append({"room": room, "sensor_id": sensor_id, "metric": metric,
                       "unit": group[0]["unit"], "count": len(group)})

    # Compare actual instants, not the input order or the alphabetical order of text.
    time_start = None
    time_end = None
    if readings:
        earliest = min(readings, key=lambda r: datetime.fromisoformat(r["time"]))
        latest = max(readings, key=lambda r: datetime.fromisoformat(r["time"]))
        time_start = earliest["time"]
        time_end = latest["time"]

    return {"record_count": len(readings),
            "rooms": sorted({r["room"] for r in readings}),
            "sensor_ids": sorted({r["sensor_id"] for r in readings}),
            "metrics": sorted({r["metric"] for r in readings}),
            "time_start": time_start, "time_end": time_end, "series": series}


def extended_summary(values: list[float]) -> dict:
    """SOLUTION S1: add median and sample (not population) standard deviation."""
    result = basic_summary(values)  # Reuse the original example, do not duplicate it.
    result["median"] = median(values) if values else None
    # A sample standard deviation has n-1 in its variance denominator.
    result["sample_sd"] = stdev(values) if len(values) >= 2 else None
    return result


def summarise_by_series(readings: list[dict]) -> list[dict]:
    """SOLUTION S2: return sorted, independent summaries with identity and unit."""
    groups = _group_by_series(readings)
    results = []
    for room, sensor_id, metric in sorted(groups):
        group = groups[(room, sensor_id, metric)]
        values = [reading["value"] for reading in group]
        results.append({"room": room, "sensor_id": sensor_id, "metric": metric,
                        "unit": group[0]["unit"], "summary": extended_summary(values)})
    # With empty input the loop never runs and the answer is an empty list.
    return results
