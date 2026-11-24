"""Trace the concave meniscus between the two reference marks on the original pixels."""

import numpy as np

from .scale import LUMA, sample, volume

WALL_FRACTION = 10      # 左右各避开贴筒壁的十分之一宽度
MAX_GAP_FRACTION = 8    # 可跨过的短缺口不超过筒内宽的八分之一


def _dp_path(score, max_step, smooth):
    """Follow the strongest edge across columns, paying a small price per vertical move."""
    rows, cols = score.shape
    big = 1e15
    dist = -score[:, 0].astype(np.float64)
    back = np.zeros((rows, cols), dtype=np.int8)
    for x in range(1, cols):
        best = np.full(rows, big)
        arg = np.zeros(rows, dtype=np.int8)
        for dy in range(-max_step, max_step + 1):
            shifted = np.full(rows, big)
            if dy > 0:
                shifted[dy:] = dist[:rows - dy]
            elif dy < 0:
                shifted[:dy] = dist[-dy:]
            else:
                shifted = dist
            candidate = shifted + smooth * abs(dy)
            better = candidate < best
            best = np.where(better, candidate, best)
            arg = np.where(better, dy, arg)
        dist = best - score[:, x]
        back[:, x] = arg
    y = int(np.argmin(dist))
    path = np.empty(cols, dtype=np.int64)
    for x in range(cols - 1, -1, -1):
        path[x] = y
        if x:
            y -= int(back[y, x])
    return path


def _longest_run(flags):
    best = current = 0
    for flag in flags:
        current = current + 1 if flag else 0
        best = max(best, current)
    return best


def trace(image, config):
    """Return the traced meniscus edge, or the reason the trace was refused."""
    left, right = config["left"], config["right"]
    upper, lower = config["upper"], config["lower"]
    inner = right - left
    margin = max(1, round(inner / WALL_FRACTION))
    xa, xb = left + margin, right - margin
    cols = xb - xa + 1
    rows = lower - upper + 1                       # 只用两条参考刻度之间的原片
    if cols < 24 or rows < 12:
        return {"issue": "两条参考刻度之间可跟边的区域太小，请重选筒壁或刻度"}
    band = image[upper:lower + 1, xa:xb + 1].astype(np.float32) @ LUMA.astype(np.float32)
    pad = np.pad(band, ((0, 0), (1, 1)), mode="edge")
    band = (pad[:, :-2] + pad[:, 1:-1] + pad[:, 2:]) / 3.0
    k = max(2, min(6, rows // 48))
    total = np.vstack((np.zeros((1, cols), np.float32), np.cumsum(band, axis=0)))
    row = np.arange(rows)
    a0 = np.maximum(0, row - k)
    b1 = np.minimum(rows, row + 1 + k)
    above = (total[row] - total[a0]) / np.maximum(1, row - a0)[:, None]
    below = (total[b1] - total[row + 1]) / np.maximum(1, b1 - row - 1)[:, None]
    step = above - below                           # >0：下方更暗，像凹液面边
    step[0] = 0.0
    step[-1] = 0.0
    sign = 1.0 if np.clip(step, 0, None).sum() >= np.clip(-step, 0, None).sum() else -1.0
    darkline = np.clip(np.minimum(above, below) - band, 0, None)   # 液面暗带本身
    darkline[0] = 0.0
    darkline[-1] = 0.0
    score = darkline + 0.5 * np.clip(sign * step, 0, None)
    median = float(np.median(step))
    noise = 1.4826 * float(np.median(np.abs(step - median)))
    floor = max(2.0, 5.0 * noise)
    flat = (score >= floor).mean(axis=1) >= 0.8    # 刻线或通长水平反光：整行通长强响应，不算液面
    score[flat] = 0.0
    path = _dp_path(score, 3, max(1.5, 0.6 * floor))   # 兼顾清楚的中央弧与两侧连续性
    along = score[path, np.arange(cols)]
    observed = along >= max(floor, 0.25 * float(np.percentile(along, 90)))
    if int(observed.sum()) < max(8, cols // 6):
        return {"issue": "两条参考刻度之间找不到可用的凹液面边，请重选"}
    gaps = []
    x = 0
    while x < cols:
        if observed[x]:
            x += 1
            continue
        start = x
        while x < cols and not observed[x]:
            x += 1
        gaps.append((start, x - 1))
    limit = inner / MAX_GAP_FRACTION
    for g0, g1 in gaps:
        width = g1 - g0 + 1
        if width > limit:
            return {"issue": f"遮挡缺口横向约 {width} px，超过筒内宽八分之一（{limit:.0f} px），请重选"}
        if g0 == 0 or g1 == cols - 1:
            return {"issue": "遮挡缺口延伸到跟边范围边缘，左右接不上，请重选"}
        if abs(int(path[g0 - 1]) - int(path[g1 + 1])) > max(3.0, 0.75 * width):
            return {"issue": "遮挡两侧的液面边高度接不上，请重选"}
    need = max(4, cols // 20)
    half = cols // 2
    if _longest_run(observed[:half]) < need or _longest_run(observed[half:]) < need:
        return {"issue": "凹液面两侧缺少实拍弧段支持，请重选"}
    fifth = max(1, cols // 5)
    center_y = float(np.median(path[2 * fifth:3 * fifth]))
    dip = max(1.5, 0.01 * inner)
    if (center_y < float(np.median(path[:fifth])) + dip
            or center_y < float(np.median(path[-fifth:])) + dip):
        return {"issue": "跟出的边中央不低于两侧，疑似刻线或通长水平反光，请重选"}
    c0, c1 = cols // 4, cols - cols // 4           # 读数取中央一半范围内最低处
    segment = path[c0:c1]
    y_low = int(segment.max())                     # 源 Y 越大越低
    x_low = int(np.median(np.nonzero(segment == y_low)[0])) + c0
    outcome = {"issue": None,
               "region": {"xa": xa, "xb": xb, "upper": upper, "lower": lower},
               "path": [[xa + i, upper + int(path[i]), bool(observed[i])] for i in range(cols)],
               "gaps": [{"x0": xa + g0, "x1": xa + g1, "width": g1 - g0 + 1} for g0, g1 in gaps],
               "x": xa + x_low, "y": upper + y_low, "seen": bool(observed[x_low])}
    if not outcome["seen"]:
        seen_segment = segment[observed[c0:c1]]
        if not len(seen_segment):
            return {"issue": "中央一半范围内没有实见的液面边，请重选"}
        outcome["y_seen"] = upper + int(seen_segment.max())
    return outcome


def report(image, config):
    """Measure by the traced meniscus, or explain why the trace was refused."""
    outcome = trace(image, config)
    if outcome.get("issue"):
        reading = sample(image, (config["left"] + config["right"]) // 2, config["level"], config)
        reading["volume_ml"] = None
        row = config["level"]
        return {"method": "meniscus", "issue": outcome["issue"], "reading": reading,
                "interval": None, "meniscus": None,
                "profile": [sample(image, x, row, config) for x in range(config["left"], config["right"] + 1)]}
    x, y = outcome["x"], outcome["y"]
    reading = sample(image, x, y, config)
    interval = None
    if not outcome["seen"]:
        # 最低处落在补过的短缺口：按可支持的最低位置范围给体积区间，不把推出来的点当实见
        reading["volume_ml"] = None
        interval = {"low_ml": volume(y, config), "high_ml": volume(outcome["y_seen"], config),
                    "y_deep": y, "y_shallow": outcome["y_seen"]}
    meniscus = {"region": outcome["region"], "path": outcome["path"], "gaps": outcome["gaps"],
                "seen": outcome["seen"]}
    return {"method": "meniscus", "issue": None, "reading": reading, "interval": interval,
            "meniscus": meniscus,
            "profile": [sample(image, column, y, config) for column in range(config["left"], config["right"] + 1)]}
