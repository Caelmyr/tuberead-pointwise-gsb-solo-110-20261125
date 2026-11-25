"""Export the volume proof, real source row, and complete measurement packet."""

from io import BytesIO, StringIO
from zipfile import ZIP_DEFLATED, ZipFile
import csv
import json

from PIL import Image, ImageDraw

from .scale import png, scale_summary


def trace_table(result):
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(("x_px", "y_px", "r", "g", "b", "luma", "volume_ml"))
    for p in result["profile"]:
        value = "" if p["volume_ml"] is None else f'{p["volume_ml"]:.4f}'
        writer.writerow((p["x"], p["y"], *p["rgb"], f'{p["brightness"]:.3f}', value))
    return buffer.getvalue().encode()


def _anchor_key(anchor):
    return int(anchor["y"])


def proof(image, card, result):
    height, width = image.shape[:2]
    extra_height = 86
    output = Image.new("RGBA", (max(405, width), height + extra_height), "#182938")
    output.alpha_composite(Image.fromarray(image).convert("RGBA"), (0, 0))

    cfg = card["settings"]
    info = result.get("scale") or scale_summary(cfg, cfg["level"])
    anchors = info.get("anchors") or scale_summary(cfg, cfg["level"])["anchors"]
    used = info.get("used")
    used_ys = set() if not used else {int(used["top"]["y"]), int(used["bottom"]["y"])}

    overlay = Image.new("RGBA", output.size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    if used:
        top_y, bottom_y = int(used["top"]["y"]), int(used["bottom"]["y"])
        overlay_draw.rectangle((cfg["left"], top_y, cfg["right"], bottom_y),
                               fill=(37, 169, 178, 34))
    output = Image.alpha_composite(output, overlay).convert("RGB")
    draw = ImageDraw.Draw(output)

    left, right = cfg["left"], cfg["right"]
    # Every adopted photographed line and both manual references is drawn from
    # the same persisted source Y used by point reading and volume estimation.
    for anchor in anchors:
        y = int(anchor["y"])
        is_used = y in used_ys
        is_reference = anchor.get("kind") == "reference"
        fill = "#0b7285" if is_used else ("#25686d" if is_reference else "#3d8b7d")
        width_px = 4 if is_used else 2
        draw.line((left, y, right, y), fill=fill, width=width_px)
        # A short right-wall tick makes the source row visible on busy photos.
        draw.line((min(right + 3, output.width - 1), y, min(right + 13, output.width - 1), y),
                  fill=fill, width=width_px)
        if is_used:
            label = f'{float(anchor["ml"]):g} mL  y={y}'
            text_x = min(left + 5, output.width - 150)
            text_y = max(2, y - 18)
            box = draw.textbbox((text_x, text_y), label)
            draw.rectangle((box[0] - 3, box[1] - 1, box[2] + 3, box[3] + 1), fill=(235, 245, 243))
            draw.text((text_x, text_y), label, fill="#0b5563")

    draw.line((left, cfg["level"], right, cfg["level"]), fill="#ac5317", width=2)
    point = result["reading"]
    x, y, reading = point["x"], point["y"], point["volume_ml"]
    draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill="#ac5317")
    label = "Outside the two known references; no extrapolation" if reading is None else \
        f'Cylinder reading {reading:.2f} mL'
    draw.text((14, height + 12), label, fill="#ebf5f3")
    draw.text((14, height + 34),
              f'Source ({x}, {y})  segment {info.get("ml_per_px", result["ml_per_px"]):.3f} mL/px',
              fill="#e7bf90")
    if used:
        skipped = int(used["bottom"]["slot"]) - int(used["top"]["slot"]) - 1
        gap_text = f", {skipped} blank slot(s)" if skipped > 0 else ""
        pair_text = (f'Used Y{used["top"]["y"]}='
                     f'{float(used["top"]["ml"]):g}mL to Y{used["bottom"]["y"]}='
                     f'{float(used["bottom"]["ml"]):g}mL{gap_text}')
    else:
        pair_text = "No bracketing line; no extrapolation"
    mode_text = "graduation lines" if info.get("mode") == "graduations" and info.get("adopted") \
        else "two-point endpoints"
    draw.text((14, height + 57), f'{mode_text} · {pair_text}', fill="#b9d7dc")
    return png(output)


def package(card, capture, image, result):
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as output:
        output.writestr("cylinder.png", capture)
        output.writestr("reading.json", json.dumps(
            {"card": card, "reading": result["reading"],
             "ml_per_px": result["ml_per_px"],
             "segment_ml_per_px": result.get("segment_ml_per_px"),
             "scale": result.get("scale"),
             "graduations": result.get("graduations", [])},
            ensure_ascii=False, indent=2))
        output.writestr("profile.csv", trace_table(result))
        output.writestr("volume-proof.png", proof(image, card, result))
    return buffer.getvalue()
