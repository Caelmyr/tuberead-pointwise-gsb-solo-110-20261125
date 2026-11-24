"""Export the volume proof, real source row, and complete measurement packet."""

from io import BytesIO, StringIO
from zipfile import ZIP_DEFLATED, ZipFile
import csv
import json

from PIL import Image, ImageDraw

from .scale import png


def trace_table(result):
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(("x_px", "y_px", "r", "g", "b", "luma", "volume_ml"))
    for p in result["profile"]:
        value = "" if p["volume_ml"] is None else f'{p["volume_ml"]:.4f}'
        writer.writerow((p["x"], p["y"], *p["rgb"], f'{p["brightness"]:.3f}', value))
    return buffer.getvalue().encode()


def transmittance_table(result):
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(("x_px", "ratio_r", "ratio_g", "ratio_b", "above_px", "below_px",
                     "adopted_x0", "adopted_x1", "above_y0", "above_y1", "below_y0", "below_y1"))
    info = result.get("transmittance")
    if info:
        for column in info["columns"]:
            writer.writerow((column["x"], *column["ratio_rgb"], column["above_px"], column["below_px"],
                             info["x0"], info["x1"], *info["above_band"], *info["below_band"]))
    return buffer.getvalue().encode()


def _transmittance_tint(overlay, info):
    x0, x1 = info["x0"], info["x1"]
    tint = Image.new("RGBA", overlay.size, (37, 104, 109, 0))
    tint_draw = ImageDraw.Draw(tint)
    for y0, y1 in (info["above_band"], info["below_band"]):
        tint_draw.rectangle((x0, y0, x1, y1), fill=(37, 104, 109, 42))
    overlay.alpha_composite(tint)


def _draw_transmittance(draw, info, height):
    x0, x1 = info["x0"], info["x1"]
    ay0, ay1 = info["above_band"]
    by0, by1 = info["below_band"]
    for y0, y1 in ((ay0, ay1), (by0, by1)):
        draw.rectangle((x0, y0, x1, y1), outline="#25686d", width=2)
    ratio = info["representative_rgb"]
    draw.text((14, height + 41),
              f'Adopted X {x0}-{x1}  above Y {ay0}-{ay1}  below Y {by0}-{by1}',
              fill="#9bc5cf")
    draw.text((14, height + 56),
              f'Relative transmission R/G/B {ratio[0]:.4f} / {ratio[1]:.4f} / {ratio[2]:.4f}  '
              f'stability CV {info["stability_cv"]:.4f}',
              fill="#9bc5cf")


def proof(image, card, result):
    info = result.get("transmittance")
    footer = 86 if info else 65
    height, width = image.shape[:2]
    output = Image.new("RGB", (max(405, width), height + footer), "#182938")
    output.paste(Image.fromarray(image), (0, 0))
    if info:
        overlay = Image.new("RGBA", output.size, (0, 0, 0, 0))
        _transmittance_tint(overlay, info)
        output = Image.alpha_composite(output.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(output)
    if info:
        _draw_transmittance(draw, info, height)
    cfg = card["settings"]
    left, right = cfg["left"], cfg["right"]
    draw.line((left, cfg["upper"], right, cfg["upper"]), fill="#25686d", width=2)
    draw.line((left, cfg["lower"], right, cfg["lower"]), fill="#25686d", width=2)
    draw.line((left, cfg["level"], right, cfg["level"]), fill="#ac5317", width=2)
    point = result["reading"]
    x, y, reading = point["x"], point["y"], point["volume_ml"]
    draw.ellipse((x-4, y-4, x+4, y+4), fill="#ac5317")
    label = "Outside the reference range" if reading is None else f'Cylinder reading {reading:.2f} mL'
    draw.text((14, height + 12), label, fill="#ebf5f3")
    draw.text((14, height + 27), f'Source ({x}, {y})  {result["ml_per_px"]:.3f} mL/px', fill="#e7bf90")
    return png(output)


def package(card, capture, image, result):
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as output:
        output.writestr("cylinder.png", capture)
        output.writestr("reading.json", json.dumps({"card": card, "reading": result["reading"],
                                                    "ml_per_px": result["ml_per_px"],
                                                    "transmittance": result.get("transmittance")},
                                                   ensure_ascii=False, indent=2))
        output.writestr("profile.csv", trace_table(result))
        output.writestr("transmittance.csv", transmittance_table(result))
        output.writestr("volume-proof.png", proof(image, card, result))
    return buffer.getvalue()
