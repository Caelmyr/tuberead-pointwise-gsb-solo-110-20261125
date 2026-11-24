"""Keep an immutable photo with independently editable cylinder reading settings."""

import json
from pathlib import Path
from threading import RLock
from uuid import uuid4

from image_lab.validation import Conflict, Invalid, identifier, integer, object_value, text

from . import scale


class Cards:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = RLock()

    def folder(self, key):
        folder = self.root / identifier(key)
        if not (folder / "card.json").is_file():
            raise Invalid("没有找到这份读数卡")
        return folder

    def read(self, key, revision=None):
        with self.lock:
            card = json.loads((self.folder(key) / "card.json").read_text())
            if revision is not None and integer(revision, "工作版本", 1) != card["revision"]:
                raise Conflict("读数卡已经改动，请重新打开")
            return card

    @staticmethod
    def commit(folder, card):
        stage = folder / (uuid4().hex + ".tmp")
        stage.write_text(json.dumps(card, ensure_ascii=False, allow_nan=False))
        stage.replace(folder / "card.json")

    def list(self):
        with self.lock:
            rows = []
            for path in self.root.glob("*/card.json"):
                card = json.loads(path.read_text())
                rows.append({**{key: card[key] for key in ("id", "name", "synthetic", "revision")},
                             "modified_ns": path.stat().st_mtime_ns})
            return sorted(rows, key=lambda row: (-row["modified_ns"], row["id"]))

    def create(self, name, title, size, data, config, synthetic=False):
        name = text(name, "读数卡名称", 80, False)
        title = text(title, "原片名称", 140, False)
        with self.lock:
            if len(self.list()) >= 150:
                raise Invalid("读数卡库已达150份")
            key = uuid4().hex
            folder = self.root / key
            folder.mkdir()
            (folder / "capture.png").write_bytes(data)
            card = {"id": key, "revision": 1, "name": name, "photo_name": title, "synthetic": synthetic,
                    "width": size[0], "height": size[1], "settings": config}
            self.commit(folder, card)
            return card

    def demo(self):
        size, image, config = scale.practice()
        return self.create("练习 · 量筒体积", "合成量筒.png", size, image, config, synthetic=True)

    def update(self, key, value):
        with self.lock:
            card = self.read(key, integer(value.get("revision"), "工作版本", 1))
            incoming = object_value(value.get("settings", {}), "量筒设置")
            config = scale.settings({**card["settings"], **incoming}, (card["width"], card["height"]))
            card.update(name=text(value.get("name", card["name"]), "读数卡名称", 80, False),
                        settings=config, revision=card["revision"] + 1)
            self.commit(self.folder(key), card)
            return card

    def photo(self, key):
        return self.folder(key) / "capture.png"
