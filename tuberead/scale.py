"""Read actual cylinder pixels against two manual volume references."""

from io import BytesIO
import math

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError

from image_lab.validation import Invalid, integer, number


LUMA = np.array([0.2126, 0.7152, 0.0722])
MAX_IMAGE_BYTES = 18 * 1024 * 1024


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


def settings(value, size):
    w, h = size
    left = integer(value.get("left"), "左壁 X", 0, w - 13)
    upper = integer(value.get("upper"), "上参考刻线 Y", 0, h - 3)
    low_ml = number(value.get("low_ml"), "下参考体积", 0, 99990)
    high_ml = number(value.get("high_ml"), "上参考体积", 0, 100000)
    if high_ml <= low_ml:
        raise Invalid("上参考体积须大于下参考体积")
    return {
        "left": left, "right": integer(value.get("right"), "右壁 X", left + 12, w - 1),
        "upper": upper, "lower": integer(value.get("lower"), "下参考刻线 Y", upper + 2, h - 1),
        "high_ml": high_ml, "low_ml": low_ml,
        "level": integer(value.get("level"), "液面 Y", 0, h - 1),
    }


def defaults(size):
    w, h = size
    return settings({"left": w // 4, "right": w * 3 // 4, "upper": h // 4, "lower": h * 3 // 4,
                     "high_ml": 80, "low_ml": 20, "level": h // 2}, size)


def volume(y, config):
    if not config["upper"] <= y <= config["lower"]:
        return None
    ratio = (y - config["upper"]) / (config["lower"] - config["upper"])
    return config["high_ml"] + ratio * (config["low_ml"] - config["high_ml"])


def sample(image, x, y, config):
    rgb = image[y, x]
    in_tube = config["left"] <= x <= config["right"]
    return {"x": x, "y": y, "rgb": [int(value) for value in rgb], "brightness": float(rgb @ LUMA),
            "volume_ml": volume(y, config) if in_tube else None}


def report(image, config):
    y = config["level"]
    x = (config["left"] + config["right"]) // 2
    profile = [sample(image, column, y, config) for column in range(config["left"], config["right"] + 1)]
    return {"reading": sample(image, x, y, config), "profile": profile,
            "ml_per_px": (config["high_ml"] - config["low_ml"]) / (config["lower"] - config["upper"])}


def practice():
    w, h = 740, 456
    cfg = settings({"left": 216, "right": 490, "upper": 112, "lower": 328,
                    "high_ml": 80, "low_ml": 20, "level": 220}, (w, h))
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
