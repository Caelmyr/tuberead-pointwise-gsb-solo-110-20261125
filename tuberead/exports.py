"""Export the volume proof, real source row, and complete measurement packet."""

from io import BytesIO, StringIO
from zipfile import ZIP_DEFLATED, ZipFile
import csv
import json

from PIL import Image, ImageDraw

from .scale import png, sample


def trace_table(result, image=None, config=None):
    buffer = StringIO()
    writer = csv.writer(buffer)
    meniscus = result.get("meniscus")
    if meniscus and image is not None and config is not None:
        writer.writerow(("x_px", "y_px", "seen", "r", "g", "b", "luma", "volume_ml"))
        for x, y, seen in meniscus["path"]:
            p = sample(image, x, y, config)
            writer.writerow((x, y, int(seen), *p["rgb"], f'{p["brightness"]:.3f}',
                             f'{p["volume_ml"]:.4f}'))
        return buffer.getvalue().encode()
    writer.writerow(("x_px", "y_px", "r", "g", "b", "luma", "volume_ml"))
    for p in result["profile"]:
        value = "" if p["volume_ml"] is None else f'{p["volume_ml"]:.4f}'
        writer.writerow((p["x"], p["y"], *p["rgb"], f'{p["brightness"]:.3f}', value))
    return buffer.getvalue().encode()


def proof(image, card, result):
    height, width = image.shape[:2]
    output = Image.new("RGB", (max(430, width), height + 65), "#182938")
    output.paste(Image.fromarray(image), (0, 0))
    draw = ImageDraw.Draw(output)
    cfg = card["settings"]
    left, right = cfg["left"], cfg["right"]
    draw.line((left, cfg["upper"], right, cfg["upper"]), fill="#25686d", width=2)
    draw.line((left, cfg["lower"], right, cfg["lower"]), fill="#25686d", width=2)
    point = result["reading"]
    x, y = point["x"], point["y"]
    meniscus = result.get("meniscus")
    if meniscus:
        region = meniscus["region"]
        for edge_x in (region["xa"], region["xb"]):
            draw.line((edge_x, region["upper"], edge_x, region["lower"]), fill="#47717b", width=1)
        path = meniscus["path"]
        for index in range(1, len(path)):
            x0, y0, seen0 = path[index - 1]
            x1, y1, seen1 = path[index]
            draw.line((x0, y0, x1, y1), fill="#2f8f5b" if seen0 and seen1 else "#d08a2d", width=2)
        interval = result["interval"]
        if interval:
            label = f'Meniscus trace · reading {interval["low_ml"]:.2f}-{interval["high_ml"]:.2f} mL (lowest bridged)'
            detail = f'Supported lowest Y {interval["y_shallow"]}-{interval["y_deep"]} · source ({x}, {y})'
        else:
            label = f'Meniscus trace · reading {point["volume_ml"]:.2f} mL'
            detail = f'Lowest seen source ({x}, {y})'
        draw.ellipse((x - 4, y - 4, x + 4, y + 4),
                     fill="#2f8f5b" if meniscus["seen"] else "#d08a2d")
        draw.text((14, height + 14), label, fill="#ebf5f3")
        draw.text((14, height + 35), f'{detail} · {result["ml_per_px"]:.3f} mL/px', fill="#e7bf90")
        return png(output)
    if result.get("method") == "meniscus" and result.get("issue"):
        draw.text((14, height + 14), "Meniscus trace not adopted", fill="#ebf5f3")
        draw.text((14, height + 35), "Re-select walls or marks; reason shown on the reading desk",
                  fill="#e7bf90")
        return png(output)
    draw.line((left, y, right, y), fill="#ac5317", width=2)
    draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill="#ac5317")
    reading = point["volume_ml"]
    label = "Outside the reference range" if reading is None else f'Cylinder reading {reading:.2f} mL'
    draw.text((14, height + 14), label, fill="#ebf5f3")
    draw.text((14, height + 35), f'Source ({x}, {y})  {result["ml_per_px"]:.3f} mL/px', fill="#e7bf90")
    return png(output)


def package(card, capture, image, result):
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as output:
        output.writestr("cylinder.png", capture)
        output.writestr("reading.json", json.dumps({"card": card, "method": result.get("method"),
                                                    "reading": result["reading"],
                                                    "interval": result.get("interval"),
                                                    "issue": result.get("issue"),
                                                    "meniscus": result.get("meniscus"),
                                                    "ml_per_px": result["ml_per_px"]},
                                                   ensure_ascii=False, indent=2))
        output.writestr("profile.csv", trace_table(result, image, card["settings"]))
        output.writestr("volume-proof.png", proof(image, card, result))
    return buffer.getvalue()
