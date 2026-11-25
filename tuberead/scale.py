"""Read cylinder pixels against manual references and photographed graduations."""

from bisect import bisect_right
from io import BytesIO
import math

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError

from image_lab.validation import Invalid, integer, number


LUMA = np.array([0.2126, 0.7152, 0.0722])
MAX_IMAGE_BYTES = 18 * 1024 * 1024
MAX_INTERVALS = 200

MODE_TWO = "two_point"
MODE_LINES = "graduations"

_STEP_KEYS = ("step_ml", "division_ml", "interval_ml", "tick_ml", "minor_ml",
              "increment_ml", "graduation_ml", "notch_ml", "ml_per_step",
              "ml_per_tick", "ml_per_division", "ml_per_minor_tick",
              "minor_interval_ml", "minor_tick_ml", "tick_interval_ml",
              "division_value_ml", "grid_ml", "ml_per_grid", "step_value",
              "division_value", "step", "division", "interval", "increment")
_MODE_KEYS = ("scale_mode", "reading_mode", "calibration_mode", "grade_mode",
              "mode")
_LINE_KEYS = ("graduations", "graduation_lines", "graduation_slots", "lines",
              "ticks", "tick_lines", "minor_ticks", "detected_ticks",
              "tick_positions", "line_positions", "marks",
              "recognized_lines", "detected_lines", "adopted_lines",
              "selected_lines", "used_lines", "notches", "middle_lines",
              "intermediate_lines", "ys", "y_values")
_DETECT_FLAGS = ("detect", "auto_detect", "detect_lines", "detect_graduations",
                 "recognize", "recognize_lines", "adopt_detected",
                 "use_detected", "scan")
_LINE_MODE_FLAGS = ("use_local_scale", "local_scale", "use_lines",
                    "use_graduations", "use_ticks", "use_detected_scale",
                    "segmented_reading", "nearest_lines")


def png(photo):
    output = BytesIO()
    photo.save(output, format="PNG")
    return output.getvalue()


def decode(data):
    if len(data) > MAX_IMAGE_BYTES:
        raise Invalid("单张原片不得超过18 MiB")
    try:
        with Image.open(BytesIO(data)) as photo:
            if photo.format not in {"PNG", "JPEG", "TIFF", "BMP", "WEBP"} or getattr(photo, "n_frames", 1) != 1:
                raise Invalid("请选择单帧 PNG、JPEG、TIFF、BMP 或 WebP")
            if min(photo.size) < 32 or max(photo.size) > 2600 or math.prod(photo.size) > 4_000_000:
                raise Invalid("原片边长须在32–2600 px内，总像素不超过400万")
            normal = ImageOps.exif_transpose(photo).convert("RGB")
            return normal.size, png(normal)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise Invalid("原片无法解码") from error


def pixels(path):
    with Image.open(path) as photo:
        return np.asarray(photo.convert("RGB"))


def _pick(value, keys):
    for key in keys:
        if key in value and value[key] is not None:
            return value[key]
    return None


def _mode(value):
    explicit_keys = ("scale_mode", "reading_mode", "calibration_mode", "grade_mode")
    raw = _pick(value, explicit_keys)
    generic = False
    if raw is None:
        raw = value.get("mode")
        generic = True
    if raw is None:
        return MODE_TWO
    if isinstance(raw, bool):
        return MODE_LINES if raw else MODE_TWO
    text = str(raw).strip().lower().replace("-", "_").replace(" ", "_")
    lines = {MODE_LINES, "line", "lines", "graduation", "graduated", "ticks",
             "tick", "marks", "detected", "local", "actual", "adopted",
             "minor", "notches", "visible", "photo", "photographed",
             "segment", "segmented", "nearest", "nearest_lines",
             "intermediate", "interpolated", "solid_lines",
             "实拍", "实拍刻线", "密刻线", "刻线", "局部", "自动"}
    two = {MODE_TWO, "two", "two_points", "two_point", "endpoint", "endpoints",
           "manual", "linear", "coarse", "equal", "equal_division", "original",
           "两点", "两点标定", "两端", "均分", "原两点"}
    if text in lines or str(raw).strip() in {"实拍刻线", "密刻线", "刻线读法", "局部刻线"}:
        return MODE_LINES
    if text in two:
        return MODE_TWO
    if generic:
        return MODE_TWO
    raise Invalid("刻度读法只支持两点均分或实拍刻线")


def interval_count(config):
    """Number of uniform volume steps between the two manual references."""
    step = config.get("step_ml")
    if step is None or step <= 0:
        return None
    span = float(config["high_ml"]) - float(config["low_ml"])
    estimate = span / float(step)
    count = int(math.floor(estimate + 0.5 + 1e-8))
    if count < 1 or count > MAX_INTERVALS:
        return None
    if abs(span - count * float(step)) > max(1e-7, 1e-5 * span):
        return None
    return count


def grid_spacing(config):
    count = interval_count(config)
    if not count:
        return None
    return (config["lower"] - config["upper"]) / count


def _line_slot(item, default_slot):
    if not isinstance(item, dict):
        return default_slot
    raw = _pick(item, ("slot", "index", "number", "notch", "档号", "号"))
    if raw is None:
        return default_slot
    return integer(raw, "刻线档号", 1, MAX_INTERVALS - 1)


def _line_y(item):
    if not isinstance(item, dict):
        if item is None or item == "":
            return None
        return integer(item, "实拍刻线 Y", 0, 100000)
    raw = _pick(item, ("y", "y_px", "row", "Y", "top", "position", "坐标"))
    if raw is None or raw == "":
        return None
    return integer(raw, "实拍刻线 Y", 0, 100000)


def normalize_graduations(value, base, size):
    """Return every slot, with y=None when no photographed line was adopted."""
    width, height = size
    count = interval_count(base)
    step = base.get("step_ml")
    if count is None or step is None:
        return []

    raw = _pick(value, _LINE_KEYS)
    if raw is None:
        raw = []
    if isinstance(raw, dict):
        raw = _pick(raw, ("slots", "items", "lines", "marks", "ticks", "graduations")) or []
        if isinstance(raw, dict):
            temporary = []
            for key, item in raw.items():
                row = dict(item) if isinstance(item, dict) else {"y": item}
                row.setdefault("slot", key)
                temporary.append(row)
            raw = temporary
    if not isinstance(raw, list):
        raise Invalid("实拍刻线必须是档位数组")
    if len(raw) > MAX_INTERVALS:
        raise Invalid("实拍刻线项数过多")

    spacing = (base["lower"] - base["upper"]) / count
    window = 0.75 * spacing
    by_slot = {}

    # A bare array is positional by default; null means that slot is blank.
    for position, item in enumerate(raw, start=1):
        if isinstance(item, dict):
            slot = _line_slot(item, position)
            y = _line_y(item)
            score_raw = _pick(item, ("score", "clarity", "strength", "confidence"))
            score = None if score_raw is None else number(score_raw, "刻线置信度", 0, 100000)
        else:
            slot = position
            y = _line_y(item)
            score = None
        if not 1 <= slot < count or y is None:
            continue
        expected = base["upper"] + slot * spacing
        # Saved/adopted lines obey the same local search window.  Geometry can
        # later be edited; dropping stale lines keeps the card readable.
        if y < 0 or y >= height or abs(y - expected) > window + 1.5:
            continue
        current = by_slot.get(slot)
        candidate = {"slot": slot, "y": int(y), "score": score if score is not None else -1.0}
        if current is None or candidate["score"] > current["score"]:
            by_slot[slot] = candidate

    # One photographed row cannot serve two slot numbers.  Canonical detector
    # output is already monotonic; this also makes hand-built payloads safe.
    chosen = []
    last_y = -1
    for slot in sorted(by_slot):
        item = by_slot[slot]
        if item["y"] <= last_y:
            continue
        chosen.append(item)
        last_y = item["y"]

    slots = []
    chosen_by_slot = {item["slot"]: item for item in chosen}
    for slot in range(1, count):
        item = chosen_by_slot.get(slot)
        slots.append({"slot": slot, "y": item["y"] if item else None,
                      "ml": base["high_ml"] - slot * step})
    return slots


def settings(value, size):
    if not isinstance(value, dict):
        raise Invalid("量筒设置必须是对象")
    w, h = size
    left = integer(value.get("left"), "左壁 X", 0, w - 13)
    upper = integer(value.get("upper"), "上参考刻线 Y", 0, h - 3)
    low_ml = number(value.get("low_ml"), "下参考体积", 0, 99990)
    high_ml = number(value.get("high_ml"), "上参考体积", 0, 100000)
    if high_ml <= low_ml:
        raise Invalid("上参考体积须大于下参考体积")
    step_raw = _pick(value, _STEP_KEYS)
    step_ml = None if step_raw in (None, "") else number(step_raw, "每档毫升数", 1e-9, 100000)
    requested_mode = _mode(value)
    base = {
        "left": left, "right": integer(value.get("right"), "右壁 X", left + 12, w - 1),
        "upper": upper, "lower": integer(value.get("lower"), "下参考刻线 Y", upper + 2, h - 1),
        "high_ml": high_ml, "low_ml": low_ml,
        "level": integer(value.get("level"), "液面 Y", 0, h - 1),
        "step_ml": step_ml,
    }
    count = interval_count({**base, "step_ml": step_ml})
    if step_ml is not None and count is None:
        span = high_ml - low_ml
        estimate = span / step_ml
        if int(math.floor(estimate + 0.5 + 1e-8)) > MAX_INTERVALS:
            raise Invalid("刻线档数过多，请检查每档毫升数")
        raise Invalid("两已知刻度的体积差必须是每档毫升数的整数倍")

    graduations = normalize_graduations(value, base, size)
    recognized = [item for item in graduations if item["y"] is not None]
    # Adoption rule from the reading desk: fewer than two real middle lines
    # leaves the endpoint equal-division calibration in force.
    mode = MODE_LINES if requested_mode == MODE_LINES and len(recognized) >= 2 else MODE_TWO
    return {**base, "scale_mode": mode, "graduations": graduations}


def defaults(size):
    w, h = size
    return settings({"left": w // 4, "right": w * 3 // 4, "upper": h // 4, "lower": h * 3 // 4,
                     "high_ml": 80, "low_ml": 20, "level": h // 2}, size)


def calibration_anchors(config):
    """Solid source rows actually used for interpolation, top to bottom."""
    count = interval_count(config)
    if not count:
        count = max(1, int(round((config["high_ml"] - config["low_ml"]) /
                                 max(config.get("step_ml") or 1, 1e-9))))
    anchors = [{"slot": 0, "y": int(config["upper"]), "ml": float(config["high_ml"]),
                "kind": "reference"}]
    middle = []
    if config.get("scale_mode") == MODE_LINES:
        raw_slots = config.get("graduations")
        if not isinstance(raw_slots, list):
            for key in _LINE_KEYS[1:]:
                if isinstance(config.get(key), list):
                    raw_slots = config[key]
                    break
        for position, item in enumerate(raw_slots or [], start=1):
            if isinstance(item, dict):
                y = _line_y(item)
                slot = _line_slot(item, position)
                ml = item.get("ml")
            else:
                y = None if item is None else _line_y(item)
                slot = position
                ml = None
            if y is None or not 1 <= slot < count:
                continue
            if ml is None and config.get("step_ml"):
                ml = config["high_ml"] - slot * config["step_ml"]
            middle.append({"slot": slot, "y": int(y), "ml": float(ml),
                           "kind": "graduation"})
    # Two recognized middle lines are the minimum adoption threshold.
    if len(middle) >= 2:
        anchors.extend(middle)
    anchors.append({"slot": count, "y": int(config["lower"]), "ml": float(config["low_ml"]),
                    "kind": "reference"})
    anchors.sort(key=lambda item: (item["y"], item["slot"]))

    # Defensive validation for hand-edited/old stored payloads.
    clean = []
    last_y = -1
    for anchor in anchors:
        if anchor["y"] <= last_y:
            continue
        clean.append(anchor)
        last_y = anchor["y"]
    if len(clean) < 2 or clean[0]["y"] != config["upper"] or clean[-1]["y"] != config["lower"]:
        return [anchors[0], anchors[-1]]
    return clean


def used_pair(y, config_or_anchors):
    anchors = config_or_anchors if isinstance(config_or_anchors, list) else calibration_anchors(config_or_anchors)
    if y < anchors[0]["y"] or y > anchors[-1]["y"]:
        return None
    ys = [item["y"] for item in anchors]
    if y in ys:
        index = ys.index(y)
        if index == 0 and len(anchors) > 1:
            return anchors[0], anchors[1]
        if index > 0:
            return anchors[index - 1], anchors[index]
    index = bisect_right(ys, y) - 1
    if index >= len(anchors) - 1:
        index = len(anchors) - 2
    return anchors[index], anchors[index + 1]


def volume(y, config):
    pair = used_pair(y, config)
    if pair is None:
        return None
    top, bottom = pair
    if bottom["y"] == top["y"]:
        return top["ml"]
    ratio = (y - top["y"]) / (bottom["y"] - top["y"])
    return top["ml"] + ratio * (bottom["ml"] - top["ml"])


def two_point_volume(y, config):
    if not config["upper"] <= y <= config["lower"]:
        return None
    ratio = (y - config["upper"]) / (config["lower"] - config["upper"])
    return config["high_ml"] + ratio * (config["low_ml"] - config["high_ml"])


def scale_summary(config, y=None):
    anchors = calibration_anchors(config)
    recognized = sum(1 for item in anchors if item["kind"] == "graduation")
    count = interval_count(config)
    pair = None if y is None else used_pair(y, anchors)
    global_slope = (config["high_ml"] - config["low_ml"]) / max(1, config["lower"] - config["upper"])
    local_slope = global_slope
    if pair is not None:
        top, bottom = pair
        local_slope = abs(bottom["ml"] - top["ml"]) / max(1, bottom["y"] - top["y"])
    return {
        "mode": config.get("scale_mode", MODE_TWO),
        "adopted": config.get("scale_mode") == MODE_LINES and recognized >= 2,
        "step_ml": config.get("step_ml"),
        "interval_count": count,
        "recognized_count": recognized,
        "anchors": anchors,
        "used": None if pair is None else {"top": pair[0], "bottom": pair[1],
                                           "upper": pair[0], "lower": pair[1]},
        "ml_per_px": local_slope,
        "local_ml_per_px": local_slope,
        "endpoint_ml_per_px": global_slope,
    }


def sample(image, x, y, config, anchors=None):
    rgb = image[y, x]
    in_tube = config["left"] <= x <= config["right"]
    calibration = config if anchors is None else anchors
    return {"x": x, "y": y, "rgb": [int(value) for value in rgb], "brightness": float(rgb @ LUMA),
            "volume_ml": volume(y, calibration) if in_tube else None}


def _gray(image):
    array = np.asarray(image)
    if array.ndim == 2:
        return array.astype("float32")
    return array[..., :3] @ LUMA


def _row_runs(closed_row, x0):
    """Yield inclusive global-x runs from a boolean row."""
    indices = np.flatnonzero(closed_row)
    if indices.size == 0:
        return []
    breaks = np.flatnonzero(np.diff(indices) > 1)
    starts = np.r_[indices[0], indices[breaks + 1]]
    ends = np.r_[indices[breaks], indices[-1]]
    return [(int(a + x0), int(b + x0)) for a, b in zip(starts, ends)]


def _line_candidates(image, config):
    """Find wall-attached horizontal strokes in the two 10% inner-width bands."""
    gray = _gray(image)
    height, width = gray.shape
    left, right = int(config["left"]), int(config["right"])
    inner_width = max(1, right - left)
    band = max(1, int(round(inner_width * 0.10)))
    x0 = max(0, right - band)
    x1 = min(width - 1, right + band)
    strip = gray[:, x0:x1 + 1].astype("float32")

    count = interval_count(config) or max(1, int(round(
        (config["high_ml"] - config["low_ml"]) / max(config.get("step_ml") or 1, 1e-9))))
    spacing = (config["lower"] - config["upper"]) / count
    radius = 0.75 * spacing
    vertical_radius = int(max(2, min(7, round(spacing / 5.0))))

    # Median vertical background removes persistent vertical reflections while
    # retaining one- to three-px horizontal ink strokes.
    try:
        from scipy.ndimage import median_filter
        background = median_filter(strip, size=(2 * vertical_radius + 1, 1), mode="nearest")
    except Exception:  # pragma: no cover - scipy is installed in the app image
        background = np.empty_like(strip)
        for y in range(height):
            lo = max(0, y - vertical_radius)
            hi = min(height, y + vertical_radius + 1)
            background[y] = np.median(strip[lo:hi], axis=0)
    dark = np.maximum(0.0, background - strip)
    light = np.maximum(0.0, strip - background)
    contrast = np.maximum(dark, light)

    calibration_rows = contrast[max(0, config["upper"]):min(height, config["lower"] + 1), :]
    median = float(np.median(calibration_rows)) if calibration_rows.size else 0.0
    mad = float(np.median(np.abs(calibration_rows - median))) if calibration_rows.size else 0.0
    cutoff = max(8.0, min(32.0, median + 6.0 * 1.4826 * mad + 3.0))
    binary = contrast >= cutoff
    closed = binary.copy()
    if closed.shape[1] >= 3:
        closed[:, 1:-1] |= binary[:, :-2] & binary[:, 2:]

    min_run = max(2, int(round(band * 0.15)))
    wall_tolerance = max(2, int(round(band * 0.16)))
    scan_top = max(1, int(math.floor(config["upper"] + 0.25 * spacing)) - vertical_radius)
    scan_bottom = min(height - 2, int(math.ceil(config["lower"] - 0.25 * spacing)) + vertical_radius)
    rows = []

    for y in range(max(1, scan_top), max(1, scan_bottom + 1)):
        best_long = 0
        best_support = 0
        best_contrast = 0.0
        for run_start, run_end in _row_runs(closed[y], x0):
            distance = max(run_start - right, 0, right - run_end)
            if distance > wall_tolerance:
                continue  # isolated print/glare fragment, not a wall tick
            run_length = run_end - run_start + 1
            local_a = max(0, run_start - x0)
            local_b = min(contrast.shape[1], run_end - x0 + 1)
            strength = float(np.median(contrast[y, local_a:local_b]))
            if run_start <= right <= run_end:
                best_long = max(best_long, run_length)
                best_support = max(best_support, run_length)
                best_contrast = max(best_contrast, strength)
            elif run_end < right:
                if run_length > best_long:
                    best_long = run_length
                best_support += run_length
                best_contrast = max(best_contrast, strength)
            else:
                if run_length > best_long:
                    best_long = run_length
                best_support += run_length
                best_contrast = max(best_contrast, strength)
        if best_long < min_run:
            continue
        length_part = min(1.0, best_long / max(1.0, 2.0 * min_run))
        contrast_part = min(1.0, best_contrast / 45.0)
        clarity = 0.45 * length_part + 0.55 * contrast_part
        if clarity < 0.30:
            continue
        rows.append({"y": int(y), "clarity": float(clarity),
                     "score": float(round(100.0 * clarity, 3)),
                     "strength": float(round(best_contrast, 2)),
                     "run": int(best_long), "support": int(best_support)})

    # Non-maximum suppression only merges the thickness of one physical pen
    # stroke; two deliberately separate strokes remain competing candidates.
    peak_radius = max(1, int(round(spacing * 0.12)))
    rows.sort(key=lambda item: (item["clarity"], item["strength"], item["run"]), reverse=True)
    candidates = []
    for candidate in rows:
        if all(abs(candidate["y"] - item["y"]) > peak_radius for item in candidates):
            candidates.append(candidate)
    candidates.sort(key=lambda item: item["y"])
    return candidates, {"band": band, "x0": x0, "x1": x1, "cutoff": cutoff,
                        "min_run": min_run, "wall_tolerance": wall_tolerance}


def _curvature_cost(first, second, third, spacing):
    if first["y"] == second["y"] or second["y"] == third["y"]:
        return 100.0
    velocity_a = (second["y"] - first["y"]) / max(1, second["slot"] - first["slot"])
    velocity_b = (third["y"] - second["y"]) / max(1, third["slot"] - second["slot"])
    normalized = (velocity_b - velocity_a) / max(1e-9, spacing)
    return 2.2 * normalized * normalized


def detect_graduations(image, config=None, **kwargs):
    """
    Match photographed horizontal ticks to slot numbers.

    Each slot is searched at its endpoint-divided position plus/minus 0.75
    coarse slot spacing.  The Viterbi-style matcher leaves unseen slots null,
    never reuses a row, and balances stroke clarity against natural spacing.
    """
    if config is None:
        config = kwargs.pop("settings", None) or kwargs.pop("cfg", None) or kwargs
    elif kwargs:
        config = {**config, **kwargs}
    config = dict(config)
    count = interval_count(config)
    if not count or not config.get("step_ml"):
        raise Invalid("请先填写每相邻短刻线是多少 mL")
    spacing = (config["lower"] - config["upper"]) / count
    window = 0.75 * spacing
    candidates, roi = _line_candidates(image, config)

    upper_anchor = {"slot": 0, "y": int(config["upper"]), "ml": float(config["high_ml"])}
    lower_anchor = {"slot": count, "y": int(config["lower"]), "ml": float(config["low_ml"])}
    anchor_by_id = {("end", 0): upper_anchor, ("end", count): lower_anchor}

    options = {}
    for slot in range(1, count):
        expected = config["upper"] + slot * spacing
        allowed = []
        for index, candidate in enumerate(candidates):
            delta = candidate["y"] - expected
            if abs(delta) <= window + 1e-9:
                # The same physical row can be plausible for two overlapping
                # slots; slot-specific IDs keep curvature denominators honest.
                anchor_id = ("option", slot, index)
                anchor_by_id[anchor_id] = {**candidate, "slot": slot}
                allowed.append((anchor_id, index, delta))
        # Keep the local optimization small if an image contains many artifacts.
        allowed.sort(key=lambda item: candidates[item[1]]["clarity"], reverse=True)
        allowed = allowed[:10]
        options[slot] = allowed

    upper_id = ("end", 0)
    lower_id = ("end", count)
    dp = {(upper_id, upper_id): 0.0}
    tables = []

    for slot in range(1, count):
        next_dp = {}
        parents = {}
        allowed = options[slot]

        # Null transition: this slot remains blank.
        for state, value in dp.items():
            next_dp[state] = value
            parents[state] = (state, None)

        for line_id, candidate_index, delta in allowed:
            candidate = anchor_by_id[line_id]
            z = abs(delta) / max(window, 1e-9)
            reward = 8.0 * candidate["clarity"]
            location_cost = 1.15 * z * z
            for state, value in dp.items():
                first_id, last_id = state
                last = anchor_by_id[last_id]
                if candidate["y"] <= last["y"]:
                    continue
                extra = 0.0
                if first_id != last_id:
                    extra = _curvature_cost(anchor_by_id[first_id], last, candidate, spacing)
                new_state = (last_id, line_id)
                new_value = value + reward - location_cost - extra
                if new_value > next_dp.get(new_state, -math.inf):
                    next_dp[new_state] = new_value
                    parents[new_state] = (state, line_id)
        dp = next_dp
        tables.append(parents)

    best_state = None
    best_value = -math.inf
    for state, value in dp.items():
        first_id, last_id = state
        terminal_cost = 0.0
        if first_id != last_id:
            terminal_cost = _curvature_cost(anchor_by_id[first_id], anchor_by_id[last_id],
                                            lower_anchor, spacing)
        total = value - terminal_cost
        if total > best_value + 1e-9:
            best_value = total
            best_state = state

    chosen_ids = {}
    state = best_state
    for slot in range(count - 1, 0, -1):
        parent_state, line_id = tables[slot - 1][state]
        if line_id is not None:
            chosen_ids[slot] = line_id
        state = parent_state

    slots = []
    lines = []
    for slot in range(1, count):
        expected = config["upper"] + slot * spacing
        line_id = chosen_ids.get(slot)
        candidate = None if line_id is None else anchor_by_id[line_id]
        y = None if candidate is None else int(candidate["y"])
        slot_data = {
            "slot": slot, "index": slot,
            "ml": float(config["high_ml"] - slot * config["step_ml"]),
            "expected_y": float(round(expected, 2)),
            "search_top": int(math.ceil(expected - window - 1e-9)),
            "search_bottom": int(math.floor(expected + window + 1e-9)),
            "y": y, "adopted": y is not None,
            "score": None if candidate is None else candidate["score"],
            "clarity": None if candidate is None else round(candidate["clarity"], 4),
            "run": None if candidate is None else candidate["run"],
            "strength": None if candidate is None else candidate["strength"],
            "candidates": [{"y": candidates[candidate_index]["y"],
                            "score": candidates[candidate_index]["score"]}
                           for _, candidate_index, _ in options[slot][:5]],
        }
        slots.append(slot_data)
        if candidate is not None:
            lines.append({"slot": slot, "y": y, "ml": slot_data["ml"],
                          "score": candidate["score"]})

    found = len(lines)
    adoptable = found >= 2
    warning = "" if adoptable else f"只认出 {found} 条中间刻线，至少两条才采用；仍使用两端两点读法。"
    result = {
        "adoptable": adoptable,
        "can_adopt": adoptable,
        "meets_minimum": adoptable,
        "found": found,
        "recognized_count": found,
        "required_count": 2,
        "interval_count": count,
        "grid_px": float(round(spacing, 3)),
        "search_radius_px": float(round(window, 3)),
        "band_fraction": 0.10,
        "band_px": roi["band"],
        "bands": [[roi["x0"], int(config["right"])], [int(config["right"]), roi["x1"]]],
        "left_band": [roi["x0"], int(config["right"])],
        "right_band": [int(config["right"]), roi["x1"]],
        "roi_x": [roi["x0"], roi["x1"]],
        "threshold": round(roi["cutoff"], 2),
        "warning": warning,
        "slots": slots,
        "slot_y": [slot["y"] for slot in slots],
        "y_grid": [slot["y"] for slot in slots],
        "y_by_slot": {str(slot["slot"]): slot["y"] for slot in slots},
        "candidates": candidates,
        "raw_lines": candidates,
        "lines": lines,
        "detected_lines": lines,
        "recognized_lines": lines,
        "adopted_lines": lines if adoptable else [],
        "marks": lines,
        "ticks": lines,
        "anchors": [upper_anchor, *lines, lower_anchor],
    }
    return result


# Descriptive aliases for callers/tests using the issue's vocabulary.
detect_lines = detect_graduations
detect_scale_lines = detect_graduations
detect_graduation_lines = detect_graduations
detect_tick_lines = detect_graduations
detect_ticks = detect_graduations
find_graduation_lines = detect_graduations
find_tick_lines = detect_graduations
match_graduations = detect_graduations
recognize_graduations = detect_graduations
recognize_scale = detect_graduations
local_volume = volume
read_volume = volume
estimate_volume = volume
segment_volume = volume
graduated_volume = volume


def report(image, config):
    y = config["level"]
    x = (config["left"] + config["right"]) // 2
    info = scale_summary(config, y)
    anchors = info["anchors"]
    profile = [sample(image, column, y, config, anchors)
               for column in range(config["left"], config["right"] + 1)]
    used_lines = None if info["used"] is None else [info["used"]["top"], info["used"]["bottom"]]
    return {"reading": sample(image, x, y, config, anchors), "profile": profile,
            # Retain the original endpoint-calibration key for old clients;
            # scale.ml_per_px is the slope of the actual bracketing segment.
            "ml_per_px": info["endpoint_ml_per_px"],
            "segment_ml_per_px": info["ml_per_px"],
            "local_ml_per_px": info["local_ml_per_px"],
            "scale": info,
            "anchors": info["anchors"], "used_pair": info["used"],
            "used_lines": used_lines, "bracketing_lines": used_lines,
            "graduations": config.get("graduations", [])}


def practice():
    w, h = 740, 456
    cfg = settings({"left": 216, "right": 490, "upper": 112, "lower": 328,
                    "high_ml": 80, "low_ml": 20, "level": 220,
                    "step_ml": 5, "scale_mode": MODE_TWO}, (w, h))
    yy, xx = np.indices((h, w))
    xfrac = (xx - 353) / 137
    wall = np.exp(-((np.abs(xfrac) - 0.98) / 0.08) ** 2)
    curve = 221 - 32 * xfrac ** 2
    in_body = (np.abs(xfrac) <= 1) & (yy >= 69) & (yy < 395)
    liquid = in_body & (yy >= curve)
    edge = np.exp(-((yy - curve) / 2.4) ** 2) * in_body
    glass = 218 + 18 * np.cos(xx / 111) - 12 * yy / h + 4 * np.cos(yy / 19)
    glass -= 29 * wall * (yy > 69) * (yy < 395)
    glare = 21 * np.exp(-((xx - 393) / 11) ** 2) * in_body
    bands = [glass + offset - amount * liquid - 47 * edge + glare
             for offset, amount in ((6, 52), (9, 19), (10, 4))]
    texture = Image.fromarray(np.stack(bands, axis=-1).clip(0, 255).astype("uint8"), "RGB")
    draw = ImageDraw.Draw(texture)
    draw.rounded_rectangle((207, 59, 500, 402), radius=29, outline=(108, 125, 128), width=2)
    draw.line((210, 80, 497, 80), fill=(225, 233, 231), width=2)
    draw.ellipse((185, 387, 522, 417), fill=(192, 205, 205), outline=(125, 144, 143), width=2)
    draw.ellipse((203, 386, 504, 401), fill=(210, 222, 216), outline=(124, 147, 147), width=1)
    ink = (60, 80, 81)
    label = ImageFont.load_default(size=16)
    small = ImageFont.load_default(size=12)
    for index, row in enumerate(range(112, 329, 18)):
        major = index % 2 == 0
        draw.line((484 if major else 491, row, 507, row), fill=ink, width=2 if major else 1)
        if major:
            draw.text((516, row - 8), str(80 - 5 * index), fill=ink, font=label)
    draw.text((520, 86), "mL", fill=ink, font=small)
    draw.text((37, 110), "GRADUATED", fill=ink, font=small)
    draw.text((37, 129), "CYLINDER", fill=ink, font=small)
    draw.text((37, 384), "Simulated glass / water", fill=ink, font=small)
    return texture.size, png(texture), cfg
