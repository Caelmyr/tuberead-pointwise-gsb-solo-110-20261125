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


def proof(image, card, result):
    height, width = image.shape[:2]
    output = Image.new("RGB", (max(405, width), height + 65), "#182938")
    output.paste(Image.fromarray(image), (0, 0))
    draw = ImageDraw.Draw(output)
    cfg = card["settings"]
    left, right = cfg["left"], cfg["right"]
    draw.line((left, cfg["upper"], right, cfg["upper"]), fill="#25686d", width=2)
    draw.line((left, cfg["lower"], right, cfg["lower"]), fill="#25686d", width=2)
    draw.line((left, cfg["level"], right, cfg["level"]), fill="#ac5317", width=2)
    point = result["reading"]
    x, y, reading = point["x"], point["y"], point["volume_ml"]
    draw.ellipse((x-4, y-4, x+4, y+4), fill="#ac5317")
    label = "Outside the reference range" if reading is None else f'Cylinder reading {reading:.2f} mL'
    draw.text((14, height + 14), label, fill="#ebf5f3")
    draw.text((14, height + 35), f'Source ({x}, {y})  {result["ml_per_px"]:.3f} mL/px', fill="#e7bf90")
    return png(output)


def package(card, capture, image, result):
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as output:
        output.writestr("cylinder.png", capture)
        output.writestr("reading.json", json.dumps({"card": card, "reading": result["reading"],
                                                    "ml_per_px": result["ml_per_px"]}, ensure_ascii=False, indent=2))
        output.writestr("profile.csv", trace_table(result))
        output.writestr("volume-proof.png", proof(image, card, result))
    return buffer.getvalue()
