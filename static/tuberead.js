"use strict";

const get = (id) => document.getElementById(id);
const state = {card: null, result: null, photo: null, probe: null, mode: "probe", busy: false,
  detection: null, pendingGraduations: null};
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
  const {photo, card, probe} = state;
  if (!photo) return;
  canvas.width = card.width;
  canvas.height = card.height;
  ctx.drawImage(photo, 0, 0);
  const cfg = card.settings;
  const scaleInfo = state.result.scale || {};
  const anchors = scaleInfo.anchors || [
    {y: cfg.upper, ml: cfg.high_ml, kind: "reference"},
    {y: cfg.lower, ml: cfg.low_ml, kind: "reference"},
  ];
  const used = scaleInfo.used || null;
  const usedYs = new Set(used ? [used.top.y, used.bottom.y] : []);
  ctx.lineWidth = Math.max(1, card.width / 550);
  ctx.strokeStyle = "#28727c";
  ctx.setLineDash([6, 4]);
  ctx.strokeRect(cfg.left, cfg.upper, cfg.right - cfg.left, cfg.lower - cfg.upper);
  ctx.setLineDash([]);
  if (used) {
    ctx.fillStyle = "rgba(37, 169, 178, 0.13)";
    ctx.fillRect(cfg.left, used.top.y, cfg.right - cfg.left, used.bottom.y - used.top.y);
  }
  for (const anchor of anchors) {
    const isUsed = usedYs.has(anchor.y);
    ctx.strokeStyle = isUsed ? "#0b7285" : (anchor.kind === "reference" ? "#25686d" : "#3d8b7d");
    ctx.lineWidth = isUsed ? Math.max(3, card.width / 190) : Math.max(1.5, card.width / 420);
    ctx.beginPath();
    ctx.moveTo(cfg.left, anchor.y + 0.5);
    ctx.lineTo(cfg.right, anchor.y + 0.5);
    ctx.stroke();
  }
  const drawn = state.result.reading;
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
  const used = point.scale?.used;
  const pair = used ? ` · 实线 Y${used.top.y}/${used.bottom.y}` : "";
  return "(" + point.x + ", " + point.y + ") · " + point.brightness.toFixed(1) + " · " + value + pair;
}

function readFormSettings() {
  return Object.fromEntries(settings.map((field) => {
    if (field.dataset.setting === "scale_mode") return [field.dataset.setting, field.value || "two_point"];
    if (field.dataset.setting === "step_ml" && field.value.trim() === "") {
      return [field.dataset.setting, null];
    }
    return [field.dataset.setting, Number(field.value)];
  }));
}

function syncScaleModeButtons() {
  const input = settings.find((field) => field.dataset.setting === "scale_mode");
  const mode = input?.value || "two_point";
  document.querySelectorAll("[data-scale-mode]").forEach((button) => {
    button.setAttribute("aria-pressed", String(button.dataset.scaleMode === mode));
  });
}

function renderGraduationSlots(slots, info = null) {
  const host = get("graduation-slots");
  const summary = get("graduation-summary");
  host.replaceChildren();
  if (!Array.isArray(slots) || !slots.length) {
    summary.textContent = info?.warning || "填好每档毫升数后识别；未采用时仍按两端均分。";
    const empty = document.createElement("span");
    empty.className = "slot-empty";
    empty.textContent = "暂无中间档";
    host.append(empty);
    return;
  }
  const found = slots.filter((slot) => slot.y !== null && slot.y !== undefined).length;
  if (info?.adoptable === false) {
    summary.textContent = info.warning || `只找到 ${found} 条，至少两条才采用。`;
  } else if (info?.adoptable || (info?.mode === "graduations" && info?.adopted)) {
    summary.textContent = `已一对一保留 ${found} 条实拍实线；空档显示“留空”。`;
  } else {
    summary.textContent = `已保存 ${found} 条实线；至少两条后启用局部估读。`;
  }
  for (const slot of slots) {
    const chip = document.createElement("span");
    const adopted = slot.y !== null && slot.y !== undefined;
    chip.className = "graduation-slot " + (adopted ? "found" : "blank");
    chip.dataset.slot = slot.slot;
    chip.dataset.adopted = String(adopted);
    if (adopted) chip.dataset.y = slot.y;
    chip.title = `第 ${slot.slot} 档 · ${slot.ml} mL` +
      (slot.expected_y ? ` · 粗分 Y${slot.expected_y}` : "") +
      (adopted ? ` · 实拍 Y${slot.y}` : " · 留空");
    const head = document.createElement("b");
    head.textContent = `${slot.slot}档 ${Number(slot.ml).toFixed(Number(slot.ml) % 1 ? 1 : 0)}mL`;
    const row = document.createElement("i");
    row.textContent = adopted ? `Y${slot.y}` : "留空";
    chip.append(head, row);
    host.append(chip);
  }
}

function usedPairText(result) {
  const used = result.scale?.used;
  if (!used) return result.reading.volume_ml === null ? "两端已知刻度之外，不外推" : "两端两点标定";
  const gap = used.bottom.slot - used.top.slot - 1;
  const skipped = gap > 0 ? ` · 跨过 ${gap} 个未认档` : "";
  return `依据实线 Y${used.top.y}（${used.top.ml} mL）→ Y${used.bottom.y}（${used.bottom.ml} mL）${skipped}`;
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
    field.value = value === null || value === undefined ? "" : value;
  }
  const modeInput = settings.find((field) => field.dataset.setting === "scale_mode");
  if (!modeInput.value) modeInput.value = "two_point";
  syncScaleModeButtons();
  get("probe-x").max = card.width - 1;
  get("probe-y").max = card.height - 1;
  get("probe-x").value = state.probe?.x ?? result.reading.x;
  get("probe-y").value = state.probe?.y ?? result.reading.y;
  get("probe-result").textContent = state.probe ? pointLabel(state.probe) : "选择原片像素";
  const volume = result.reading.volume_ml;
  const usingLines = result.scale?.mode === "graduations" && result.scale?.adopted;
  get("volume").textContent = volume === null ? "—" : volume.toFixed(2);
  get("volume-detail").textContent = volume === null ? "参考刻度外" : (usingLines ? "mL · 局部实线" : "mL");
  get("measurement-state").textContent = volume === null ? "超出范围" : (usingLines ? "实拍刻线夹读" : "两点标定");
  const slope = result.scale?.ml_per_px ?? result.ml_per_px;
  get("selected-level").textContent = "原片液面 Y " + result.reading.y + " · " +
    slope.toFixed(3) + " mL/px · " + usedPairText(result);
  renderGraduationSlots(card.settings.graduations || [], result.scale);
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
  Object.assign(state, {card, result, photo, probe: null, detection: null, pendingGraduations: null});
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
document.querySelectorAll("[data-scale-mode]").forEach((button) => button.addEventListener("click", () => {
  const input = settings.find((field) => field.dataset.setting === "scale_mode");
  input.value = button.dataset.scaleMode;
  syncScaleModeButtons();
  if (input.value === "two_point") {
    notice("已切回原两点读法；点击“保存并重读”后点读和校样使用两端实线。");
  } else {
    notice("将使用已保存的实拍实线；若改过坐标或每档毫升数，请重新识别。");
  }
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
async function saveCalibration(extraSettings = {}) {
  const settingsPayload = {...readFormSettings(), ...extraSettings};
  if (!Object.prototype.hasOwnProperty.call(extraSettings, "graduations")) {
    settingsPayload.graduations = state.pendingGraduations || state.card.settings.graduations || [];
  }
  const card = await api(route(""), {
    method: "PATCH", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({revision: state.card.revision, name: get("name").value,
      settings: settingsPayload}),
  });
  state.pendingGraduations = null;
  await open(card);
  await library();
}

get("detect-lines").addEventListener("click", () => action(async () => {
  const formSettings = readFormSettings();
  if (!formSettings.step_ml || formSettings.step_ml <= 0) {
    notice("请先填写相邻短刻线一档是多少 mL。");
    return;
  }
  const detection = await api(route("/detect") + savedQuery(), {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({revision: state.card.revision, settings: formSettings}),
  });
  state.detection = detection;
  state.pendingGraduations = detection.lines;
  renderGraduationSlots(detection.slots, detection);
  if (!detection.adoptable) {
    notice(detection.warning || "至少找到两条中间刻线才可采用。");
    return;
  }
  settings.find((field) => field.dataset.setting === "scale_mode").value = "graduations";
  syncScaleModeButtons();
  await saveCalibration({graduations: detection.lines, scale_mode: "graduations"});
  notice(`已识别并保存 ${detection.found} 条中间实线；点读、重开和校样使用同一 Y 坐标。`);
}));
get("calibration").addEventListener("submit", (event) => {
  event.preventDefault();
  action(() => saveCalibration());
});
get("prepare").addEventListener("click", () => action(async () => {
  const {url} = await api(route("/prepare") + savedQuery(), {method: "POST"});
  location.assign(url);
}));
action(library);
