"""Connect the waterline reading desk to the photo preparation workspace."""

from io import BytesIO
import os
from pathlib import Path

from flask import Blueprint, jsonify, render_template, request, send_file, url_for

from image_lab import create_app as preparation_app
from image_lab.validation import Invalid, integer, object_value

from . import exports, scale
from .store import Cards


def download(data, mime, filename):
    return send_file(BytesIO(data), mimetype=mime, max_age=0, download_name=filename, as_attachment=True)


def create_app(directory=None):
    root = Path(directory or os.environ.get("TUBEREAD_DATA", ".tuberead-data")).resolve()
    desk = preparation_app(root / "prepare")
    cards = Cards(root / "cards")
    api = Blueprint("tuberead", __name__, url_prefix="/tuberead")

    @desk.get("/")
    def home():
        return render_template("tuberead.html")

    @api.get("/health")
    def health():
        return jsonify(status="ok", app="tuberead")

    @api.get("/cards")
    def listing():
        return jsonify(cards=cards.list())

    @api.post("/cards")
    def create():
        request.max_content_length = 20 * 1024 * 1024
        upload = request.files.get("photo")
        if not upload or not upload.filename:
            raise Invalid("请选择量筒原片")
        size, image = scale.decode(upload.stream.read(scale.MAX_IMAGE_BYTES + 1))
        return jsonify(cards.create(request.form.get("name", ""), Path(upload.filename).name[:140],
                                    size, image, scale.defaults(size))), 201

    @api.post("/practice")
    def practice():
        return jsonify(cards.demo()), 201

    @api.route("/cards/<key>", methods=["GET", "PATCH"])
    def card(key):
        if request.method == "GET":
            return jsonify(cards.read(key))

        body = object_value(request.get_json(silent=True), "读数卡设置")
        revision = integer(body.get("revision"), "工作版本", 1)
        current = cards.read(key, revision)
        incoming = body.get("settings")
        if not isinstance(incoming, dict) and any(key in body for key in
                                                  ("left", "right", "upper", "lower", "level",
                                                   "high_ml", "low_ml", "step_ml", "scale_mode")):
            incoming = body
        incoming = {} if incoming is None else incoming
        incoming = object_value(incoming, "量筒设置")
        merged = {**current["settings"], **incoming}
        config = scale.settings(merged, (current["width"], current["height"]))

        wants_scan = any(bool(body.get(flag)) for flag in scale._DETECT_FLAGS)
        wants_scan = wants_scan or any(bool(incoming.get(flag)) for flag in scale._DETECT_FLAGS)
        requested_lines = scale._mode(merged) == scale.MODE_LINES
        requested_lines = requested_lines or any(bool(merged.get(flag)) for flag in scale._LINE_MODE_FLAGS)
        has_saved_lines = sum(1 for item in config["graduations"] if item["y"] is not None) >= 2

        # A PATCH that switches to photographed ticks without supplying frozen
        # rows adopts a fresh scan only when the two-line rule is satisfied.
        if wants_scan:
            detection = scale.detect_graduations(scale.pixels(cards.photo(key)), config)
            if detection["adoptable"]:
                config["graduations"] = detection["lines"]
                config["scale_mode"] = scale.MODE_LINES
            else:
                config["scale_mode"] = scale.MODE_TWO
        elif requested_lines and not has_saved_lines:
            try:
                detection = scale.detect_graduations(scale.pixels(cards.photo(key)), config)
            except Invalid:
                # Saving a level/name while local calibration is not yet
                # configured must remain possible; endpoint reading stays live.
                config["scale_mode"] = scale.MODE_TWO
            else:
                if detection["adoptable"]:
                    config["graduations"] = detection["lines"]
                    config["scale_mode"] = scale.MODE_LINES
                else:
                    config["scale_mode"] = scale.MODE_TWO
        elif requested_lines and has_saved_lines:
            config["scale_mode"] = scale.MODE_LINES

        update_body = {**body, "settings": config}
        return jsonify(cards.update(key, update_body))

    def detection_payload(key):
        query_revision = request.args.get("revision")
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            body = {}
        revision = query_revision if query_revision is not None else body.get("revision")
        card = cards.read(key, revision)
        incoming = body.get("settings")
        if not isinstance(incoming, dict) and any(field in body for field in
                                                  ("left", "right", "upper", "lower", "level",
                                                   "high_ml", "low_ml", "step_ml", "scale_mode")):
            incoming = body
        if not isinstance(incoming, dict):
            incoming = {key: value for key, value in request.args.items() if key != "revision"}
        merged = {**card["settings"], **incoming}
        config = scale.settings(merged, (card["width"], card["height"]))
        result = scale.detect_graduations(scale.pixels(cards.photo(key)), config)
        return jsonify(revision=card["revision"], config=config, **result)

    for detection_index, detection_path in enumerate((
            "/cards/<key>/detect", "/cards/<key>/detect-lines",
            "/cards/<key>/detect-ticks", "/cards/<key>/detect-graduations",
            "/cards/<key>/detected-ticks", "/cards/<key>/graduations/detect",
            "/cards/<key>/recognize", "/cards/<key>/scan-ticks",
            "/cards/<key>/ticks/detect", "/cards/<key>/scale/detect")):
        api.add_url_rule(detection_path, endpoint=f"graduation_detection_{detection_index}",
                         view_func=detection_payload, methods=["GET", "POST"])

    @api.get("/cards/<key>/capture.png")
    def capture(key):
        return send_file(cards.photo(key), mimetype="image/png", conditional=True)

    def measurement(key):
        card = cards.read(key, request.args.get("revision"))
        image = scale.pixels(cards.photo(key))
        return card, image, scale.report(image, card["settings"])

    @api.get("/cards/<key>/measurement")
    def measurement_json(key):
        card, _, result = measurement(key)
        return jsonify(revision=card["revision"], **result)

    @api.get("/cards/<key>/probe")
    def probe(key):
        card = cards.read(key, request.args.get("revision"))
        x = integer(request.args.get("x"), "X", 0, card["width"] - 1)
        y = integer(request.args.get("y"), "Y", 0, card["height"] - 1)
        config = card["settings"]
        point = scale.sample(scale.pixels(cards.photo(key)), x, y, config)
        info = scale.scale_summary(config, y)
        used_lines = None if info["used"] is None else [info["used"]["top"], info["used"]["bottom"]]
        return jsonify({**point, "scale": info, "used_pair": info["used"],
                        "used_lines": used_lines})

    @api.get("/cards/<key>/export/profile.csv")
    def profile(key):
        _, _, result = measurement(key)
        return download(exports.trace_table(result), "text/csv", "waterline-profile.csv")

    @api.get("/cards/<key>/export/proof.png")
    def proof(key):
        card, image, result = measurement(key)
        return download(exports.proof(image, card, result), "image/png", "volume-proof.png")

    @api.get("/cards/<key>/export/observation.zip")
    def bundle(key):
        card, image, result = measurement(key)
        package = exports.package(card, cards.photo(key).read_bytes(), image, result)
        return download(package, "application/zip", f"tuberead-r{card['revision']}.zip")

    @api.post("/cards/<key>/prepare")
    def prepare(key):
        card = cards.read(key, request.args.get("revision"))
        image = scale.pixels(cards.photo(key)).astype("float32") / 255
        services = desk.extensions
        asset = services["assets"].put(image, card["photo_name"])
        project = services["store"].create(f'{card["name"]} · 原片准备')
        services["frames"].add(project["id"], project["revision"], [asset["id"]])
        return jsonify(url=url_for("index", project=project["id"])), 201

    desk.register_blueprint(api)
    return desk
