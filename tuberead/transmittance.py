"""Relative transmission comparison of dyed water against the empty glass above it.

The card already stores two reference graduations and a hand-filled liquid level.
For one continuous vertical run of source columns we pair, at the same X, original
pixels taken from the empty cylinder above the liquid with pixels taken from the
water below it. A column is only usable when each of the two sample bands contains
at least five unclipped source pixels (every RGB channel in 1..254). Columns that
fail on either side break the run; neighbouring columns can never substitute.
"""

import numpy as np

WALL_INSET = 0.1
SURFACE_GAP = 8
MIN_QUALIFIED = 5
CHANNELS = ("r", "g", "b")


def wall_domain(config):
    """Column span after retreating one tenth of the inner width from each wall."""
    inset = int(round((config["right"] - config["left"]) * WALL_INSET))
    return config["left"] + inset, config["right"] - inset


def sample_bands(config):
    """Actual Y extents of the two bands, or None when the geometry cannot work.

    Eight source rows are cleared on each side of the level and the level row itself
    is never sampled. In the remaining reference range, the above-water band takes
    the half nearest the upper graduation and the underwater band the half nearest
    the lower graduation (integer halves, rows inclusive).
    """
    level = config["level"]
    above_last = level - (SURFACE_GAP + 1)
    below_first = level + (SURFACE_GAP + 1)
    if above_last < config["upper"] or below_first > config["lower"]:
        return None
    above_rows = above_last - config["upper"] + 1
    below_rows = config["lower"] - below_first + 1
    above_n = above_rows // 2
    below_n = below_rows // 2
    if above_n < MIN_QUALIFIED or below_n < MIN_QUALIFIED:
        return None
    above_band = (config["upper"], config["upper"] + above_n - 1)
    below_band = (config["lower"] - below_n + 1, config["lower"])
    return above_band, below_band


def _band_stats(image, band, x0, x1):
    """Qualified pixel counts and per-channel means for every column in a band."""
    y0, y1 = band
    block = image[y0:y1 + 1, x0:x1 + 1, :].astype(np.float64)
    qualified = np.all((block >= 1) & (block <= 254), axis=2)
    counts = qualified.sum(axis=0)
    sums = np.where(qualified[:, :, np.newaxis], block, 0.0).sum(axis=0)
    means = sums / np.maximum(counts, 1)[:, np.newaxis]
    return counts, means


def _runs(valid):
    starts = []
    run = None
    for index, ok in enumerate(valid):
        if ok and run is None:
            run = index
        elif not ok and run is not None:
            starts.append((run, index - 1))
            run = None
    if run is not None:
        starts.append((run, len(valid) - 1))
    return starts


def _stability(ratios):
    """Mean per-channel coefficient of variation of the column ratios in a run."""
    if ratios.shape[0] <= 1:
        return 0.0
    channel_means = ratios.mean(axis=0)
    return float(np.mean(ratios.std(axis=0) / channel_means))


def analyze(image, config):
    """Build the adopted transmission run with the actual ranges used on both sides."""
    bands = sample_bands(config)
    x0, x1 = wall_domain(config)
    if bands is None or x1 < x0:
        return None
    above_band, below_band = bands
    above_counts, above_means = _band_stats(image, above_band, x0, x1)
    below_counts, below_means = _band_stats(image, below_band, x0, x1)
    valid = (above_counts >= MIN_QUALIFIED) & (below_counts >= MIN_QUALIFIED)
    if not valid.any():
        return None
    safe_above = np.where(valid[:, np.newaxis], above_means, 1.0)
    ratios = below_means / safe_above
    candidates = _runs(valid.tolist())

    def score(run):
        lo, hi = run
        return hi - lo + 1, -_stability(ratios[lo:hi + 1])

    lo, hi = max(candidates, key=score)
    columns = [
        {
            "x": int(x0 + index),
            "ratio_rgb": [round(float(value), 6) for value in ratios[index]],
            "above_px": int(above_counts[index]),
            "below_px": int(below_counts[index]),
        }
        for index in range(lo, hi + 1)
    ]
    representative = ratios[lo:hi + 1].mean(axis=0)
    return {
        "x0": int(x0 + lo),
        "x1": int(x0 + hi),
        "above_band": [int(above_band[0]), int(above_band[1])],
        "below_band": [int(below_band[0]), int(below_band[1])],
        "columns": columns,
        "representative_rgb": [round(float(value), 6) for value in representative],
        "stability_cv": round(_stability(ratios[lo:hi + 1]), 6),
    }


def at_column(info, x):
    """Transmission reading exposed by the point probe only for adopted columns."""
    if not info or not info["x0"] <= x <= info["x1"]:
        return None
    column = info["columns"][x - info["x0"]]
    return {
        "x0": info["x0"],
        "x1": info["x1"],
        "above_band": info["above_band"],
        "below_band": info["below_band"],
        "ratio_rgb": column["ratio_rgb"],
        "above_px": column["above_px"],
        "below_px": column["below_px"],
    }
