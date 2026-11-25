"""Compatibility module for graduation detection helpers."""

from .scale import (
    calibration_anchors,
    detect_graduation_lines,
    detect_graduations,
    detect_lines,
    detect_tick_lines,
    detect_ticks,
    grid_spacing,
    interval_count,
    local_volume,
    match_graduations,
    scale_summary,
    used_pair,
    volume,
)

__all__ = [
    "calibration_anchors",
    "detect_graduation_lines",
    "detect_graduations",
    "detect_lines",
    "detect_tick_lines",
    "detect_ticks",
    "grid_spacing",
    "interval_count",
    "local_volume",
    "match_graduations",
    "scale_summary",
    "used_pair",
    "volume",
]
