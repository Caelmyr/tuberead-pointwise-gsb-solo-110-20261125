"use strict";

const get = (id) => document.getElementById(id);
const state = {card: null, result: null, photo: null, probe: null, mode: "probe", busy: false};
const settings = [...document.querySelectorAll("[data-setting]")];

async function api(path, options) {
  const response = await fetch("/tuberead" + path, options);
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || "请求失败，请检查输入后重试。");
  return body;
}

function route(tail) {
  return "/cards/" + state.card.id + tail;
}

function savedQuery() {
  return "?revision=" + state.card.revision;
}

function notice(message, target = "notice") {
  const element = get(target);
  element.textContent = message;
  element.hidden = !message;
}

async function action(work, target = "notice") {
  if (state.busy) return;
  state.busy = true;
  document.querySelectorAll("button, select").forEach((node) => { node.disabled = true; });
  notice("", target);
  try {
    await work();
  } catch (error) {
    notice(error.message, target);
  } finally {
    state.busy = false;
    document.querySelectorAll("button, select").forEach((node) => { node.disabled = false; });
  }
}

async function library() {
  const {cards} = await api("/cards");
  const select = get("library");
  select.replaceChildren(new Option("选取已存卡片", ""));
  for (const card of cards) select.append(new Option(card.name, card.id));
  select.value = state.card?.id || "";
}

function paintSource() {
  const canvas = get("capture");
  const ctx = canvas.getContext("2d");
  const {photo, card, probe, result} = state;
  if (!photo) return;
  canvas.width = card.width;
  canvas.height = card.height;
  ctx.drawImage(photo, 0, 0);
  const cfg = card.settings;
  ctx.lineWidth = Math.max(1, card.width / 550);
  ctx.strokeStyle = "#28727c";
  ctx.setLineDash([6, 4]);
  ctx.strokeRect(cfg.left, cfg.upper, cfg.right - cfg.left, cfg.lower - cfg.upper);
  ctx.setLineDash([]);
  const drawn = result.reading;
  const meniscus = result.meniscus;
  if (meniscus) {
    const region = meniscus.region;
    ctx.strokeStyle = "rgba(40, 114, 124, .55)";
    ctx.setLineDash([3, 4]);
    ctx.beginPath();
    ctx.moveTo(region.xa + 0.5, region.upper);
    ctx.lineTo(region.xa + 0.5, region.lower);
    ctx.moveTo(region.xb + 0.5, region.upper);
    ctx.lineTo(region.xb + 0.5, region.lower);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.lineWidth = 2;
    for (let i = 1; i < meniscus.path.length; i++) {
      const [x0, y0, seen0] = meniscus.path[i - 1];
      const [x1, y1, seen1] = meniscus.path[i];
      ctx.strokeStyle = seen0 && seen1 ? "#1d7a4f" : "#c07a1a";
      ctx.beginPath();
      ctx.moveTo(x0, y0);
      ctx.lineTo(x1, y1);
      ctx.stroke();
    }
    ctx.fillStyle = meniscus.seen ? "#1d7a4f" : "#c07a1a";
    ctx.beginPath();
    ctx.arc(drawn.x, drawn.y, 4, 0, 2 * Math.PI);
    ctx.fill();
  } else if (result.method !== "meniscus") {
    ctx.strokeStyle = "#ac5317";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(cfg.left, drawn.y);
    ctx.lineTo(cfg.right, drawn.y);
    ctx.stroke();
    ctx.fillStyle = "#ac5317";
    ctx.beginPath();
    ctx.arc(drawn.x, drawn.y, 4, 0, 2 * Math.PI);
    ctx.fill();
  }
  if (probe) {
    ctx.strokeStyle = "#132637";
    ctx.strokeRect(probe.x - 5, probe.y - 5, 10, 10);
  }
}

function paintChart() {
  const canvas = get("chart");
  const ctx = canvas.getContext("2d");
  const {width, height} = canvas;
  const values = state.result.profile;
  const {card} = state;
  const xAt = (x) => 38 + (width - 61) * x / (card.width - 1);
  const yAt = (y) => height - 24 - (height - 38) * y / 255;
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#fcfeff";
  ctx.fillRect(0, 0, width, height);
  ctx.font = "12px monospace";
  ctx.fillStyle = "#466272";
  ctx.strokeStyle = "#bfcfda";
  for (const level of [0, 128, 255]) {
    ctx.fillText(level, 5, yAt(level) + 3);
    ctx.beginPath();
    ctx.moveTo(xAt(0), yAt(level));
    ctx.lineTo(xAt(card.width - 1), yAt(level));
    ctx.stroke();
  }
  ctx.fillText("0", xAt(0), height - 6);
  ctx.fillText(String(card.width - 1), width - 36, height - 6);
  ctx.fillStyle = "#dcecef";
  ctx.fillRect(xAt(card.settings.left), yAt(255), xAt(card.settings.right)-xAt(card.settings.left), yAt(0)-yAt(255));
  ctx.strokeStyle = "#25686d";
  ctx.lineWidth = 2;
  ctx.beginPath();
  for (const [index, row] of values.entries()) {
    if (index === 0) ctx.moveTo(xAt(row.x), yAt(row.brightness));
    else ctx.lineTo(xAt(row.x), yAt(row.brightness));
  }
  ctx.stroke();
  const read = state.result.reading;
  if (values.length) {
    ctx.fillStyle = "#ac5317";
    ctx.beginPath();
    ctx.arc(xAt(read.x), yAt(read.brightness), 4, 0, 2 * Math.PI);
    ctx.fill();
  }
}

function pointLabel(point) {
  const value = point.volume_ml === null ? "参考外" : point.volume_ml.toFixed(2) + " mL";
  return "(" + point.x + ", " + point.y + ") · " + point.brightness.toFixed(1) + " · " + value;
}

function show() {
  const {card, result} = state;
  get("workspace").hidden = false;
  get("empty").hidden = true;
  get("origin").textContent = (card.synthetic ? "合成练习图" : "导入原片") + " · 修订 " + card.revision;
  get("card-title").textContent = card.name;
  get("dimensions").textContent = card.width + " × " + card.height + " px · " + card.photo_name;
  get("name").value = card.name;
  for (const field of settings) {
    const value = card.settings[field.dataset.setting];
    field.value = value ?? (field.dataset.setting === "method" ? "manual" : "");
  }
  get("probe-x").max = card.width - 1;
  get("probe-y").max = card.height - 1;
  get("probe-x").value = state.probe?.x ?? result.reading.x;
  get("probe-y").value = state.probe?.y ?? result.reading.y;
  get("probe-result").textContent = state.probe ? pointLabel(state.probe) : "选择原片像素";
  const volume = result.reading.volume_ml;
  const interval = result.interval;
  const scale = result.ml_per_px.toFixed(3) + " mL/px";
  if (result.issue) {
    get("volume").textContent = "—";
    get("volume-detail").textContent = "需要重选";
    get("measurement-state").textContent = "凹液面跟边 · 未采用";
    get("selected-level").textContent = result.issue;
    notice(result.issue);
  } else if (interval) {
    get("volume").textContent = interval.low_ml.toFixed(2) + "–" + interval.high_ml.toFixed(2);
    get("volume-detail").textContent = "mL · 区间";
    get("measurement-state").textContent = "凹液面跟边 · 最低处补缺口";
    get("selected-level").textContent = "凹液面最低落在补过的短缺口 · 可支持最低 Y " +
      interval.y_shallow + "–" + interval.y_deep + " · " + scale;
  } else if (result.meniscus) {
    get("volume").textContent = volume.toFixed(2);
    get("volume-detail").textContent = "mL";
    get("measurement-state").textContent = "凹液面跟边 · 实见最低";
    get("selected-level").textContent = "凹液面最低 (" + result.reading.x + ", " + result.reading.y +
      ") · 实见 · " + scale;
  } else {
    get("volume").textContent = volume === null ? "—" : volume.toFixed(2);
    get("volume-detail").textContent = volume === null ? "参考刻度外" : "mL";
    get("measurement-state").textContent = volume === null ? "超出范围" : "两点标定";
    get("selected-level").textContent = "原片液面 Y " + result.reading.y + " · " + scale;
  }
  for (const [id, filename] of Object.entries({proof: "proof.png", csv: "profile.csv", zip: "observation.zip"})) {
    get(id).href = "/tuberead" + route("/export/" + filename) + savedQuery();
  }
  paintSource();
  paintChart();
}

async function open(card) {
  const base = "/cards/" + card.id;
  const photo = new Image();
  photo.src = "/tuberead" + base + "/capture.png";
  const [result] = await Promise.all([api(base + "/measurement?revision=" + card.revision), photo.decode()]);
  Object.assign(state, {card, result, photo, probe: null});
  get("library").value = card.id;
  show();
}

async function probe(x, y) {
  state.probe = await api(route("/probe") + savedQuery() + "&x=" + x + "&y=" + y);
  get("probe-x").value = x;
  get("probe-y").value = y;
  get("probe-result").textContent = pointLabel(state.probe);
  paintSource();
}

get("practice").addEventListener("click", () => action(async () => {
  await open(await api("/practice", {method: "POST"}));
  await library();
}));

get("library").addEventListener("change", () => {
  if (get("library").value) action(async () => open(await api("/cards/" + get("library").value)));
});
get("open-import").addEventListener("click", () => {
  notice("", "import-notice");
  get("import").showModal();
});
get("cancel-import").addEventListener("click", () => get("import").close());
get("upload").addEventListener("submit", (event) => {
  event.preventDefault();
  action(async () => {
    const card = await api("/cards", {method: "POST", body: new FormData(event.target)});
    await open(card);
    await library();
    get("import").close();
    event.target.reset();
  }, "import-notice");
});
document.querySelectorAll("[data-mode]").forEach((button) => button.addEventListener("click", () => {
  state.mode = button.dataset.mode;
  document.querySelectorAll("[data-mode]").forEach((item) =>
    item.setAttribute("aria-pressed", String(item === button)));
}));
get("capture").addEventListener("click", (event) => {
  if (!state.card) return;
  const canvas = event.currentTarget;
  const rect = canvas.getBoundingClientRect();
  const x = Math.max(0, Math.min(canvas.width - 1, Math.floor((event.clientX - rect.left) * canvas.width / rect.width)));
  const y = Math.max(0, Math.min(canvas.height - 1, Math.floor((event.clientY - rect.top) * canvas.height / rect.height)));
  action(async () => {
    await probe(x, y);
    if (state.mode === "mark") {
      settings.find((field) => field.dataset.setting === "level").value = y;
      notice("已填入液面 Y，保存后更新体积和校样。");
    }
  });
});
get("probe-form").addEventListener("submit", (event) => {
  event.preventDefault();
  action(() => probe(get("probe-x").value, get("probe-y").value));
});
get("calibration").addEventListener("submit", (event) => {
  event.preventDefault();
  action(async () => {
    const fields = {};
    for (const field of settings) {
      fields[field.dataset.setting] = field.dataset.setting === "method" ? field.value : Number(field.value);
    }
    const card = await api(route(""), {
      method: "PATCH", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({revision: state.card.revision, name: get("name").value, settings: fields}),
    });
    await open(card);
    await library();
  });
});
get("prepare").addEventListener("click", () => action(async () => {
  const {url} = await api(route("/prepare") + savedQuery(), {method: "POST"});
  location.assign(url);
}));
action(library);
