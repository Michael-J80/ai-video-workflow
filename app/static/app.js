"use strict";

(function () {
  const state = {
    csrf: null,
    health: null,
    tasks: [],
    activeTaskId: null,
    activeTask: null,
    eventSource: null,
    materialFiles: [],
    pending: new Set(),
    detailDirty: false
  };

  const el = {};

  function cache() {
    const ids = [
      "btn-refresh", "btn-health", "btn-browser-login",
      "help-panel", "btn-help-dismiss",
      "health-list", "create-form", "create-error",
      "f-requirements", "f-duration", "f-ratio", "f-require-audio",
      "f-device", "f-skip-speech", "f-override", "override-fields",
      "f-model", "f-mode", "f-resolution", "f-count", "f-override-source",
      "task-list", "list-error",
      "detail-empty", "detail-panel", "detail-meta", "detail-status",
      "f-materials", "material-queue", "btn-upload-materials",
      "materials-error", "materials-success",
      "btn-start", "btn-prepare", "btn-pause", "btn-resume", "action-error",
      "f-design-prompt", "f-design-design", "f-design-shots", "btn-save-design",
      "design-error", "design-success",
      "quote-empty", "quote-meta", "btn-approve", "quote-error",
      "artifact-list", "detail-error"
    ];
    for (const id of ids) {
      el[id] = document.getElementById(id);
    }
  }

  function setText(node, text) {
    if (node) node.textContent = text == null ? "" : String(text);
  }

  function showError(node, msg) {
    setText(node, msg || "");
  }

  function showSuccess(node, msg) {
    setText(node, msg || "");
  }

  function clearMessages() {
    for (const key of ["create-error", "list-error", "materials-error", "materials-success", "action-error", "design-error", "design-success", "quote-error", "detail-error"]) {
      setText(el[key], "");
    }
  }

  function withPending(btn, fn) {
    if (!btn) return fn();
    if (state.pending.has(btn)) return Promise.resolve();
    state.pending.add(btn);
    btn.disabled = true;
    return Promise.resolve()
      .then(fn)
      .finally(() => {
        state.pending.delete(btn);
        btn.disabled = false;
        refreshActionButtons();
      });
  }

  async function api(path, options) {
    const opts = Object.assign({ headers: {} }, options || {});
    opts.headers = Object.assign({ "Accept": "application/json" }, opts.headers || {});
    if (opts.body && typeof opts.body === "string") {
      opts.headers["Content-Type"] = opts.headers["Content-Type"] || "application/json";
    }
    if (opts.method && opts.method !== "GET" && state.csrf) {
      opts.headers["X-CSRF-Token"] = state.csrf;
    }
    const res = await fetch(path, opts);
    let data = null;
    const ct = res.headers.get("content-type") || "";
    if (ct.indexOf("application/json") >= 0) {
      try { data = await res.json(); } catch (e) { data = null; }
    } else {
      try { data = await res.text(); } catch (e) { data = null; }
    }
    if (!res.ok) {
      let msg = "请求失败（" + res.status + "）";
      if (data && typeof data === "object") {
        if (typeof data.message === "string" && data.message) msg = data.message;
        else if (typeof data.error === "string" && data.error) msg = data.error;
        else if (typeof data.detail === "string" && data.detail) msg = data.detail;
      } else if (typeof data === "string" && data.trim()) {
        msg = data.trim();
      }
      throw new Error(msg);
    }
    return data;
  }

  async function loadSession() {
    const data = await api("/api/session");
    if (data && typeof data.csrf_token === "string") {
      state.csrf = data.csrf_token;
    }
  }

  function healthClass(value) {
    const v = String(value || "").toLowerCase();
    if (v === "ok" || v === "ready" || v === "available" || v === "true") return "health-ok";
    if (v === "missing" || v === "error" || v === "unavailable" || v === "false") return "health-bad";
    return "";
  }

  function renderHealth() {
    const list = el["health-list"];
    list.textContent = "";
    const h = state.health || {};
    const keys = ["codex", "hermes", "ffmpeg", "ffprobe", "browser", "live_verified"];
    for (const k of keys) {
      const li = document.createElement("li");
      li.className = "health-item " + healthClass(h[k]);
      const dot = document.createElement("span");
      dot.className = "health-dot";
      li.appendChild(dot);
      const label = document.createElement("span");
      label.textContent = k === "live_verified" ? "官网实测：" + (h[k] ? "已验证" : "未验证") : k + ": " + (h[k] == null ? "未知" : String(h[k]));
      li.appendChild(label);
      list.appendChild(li);
    }
  }

  async function loadHealth() {
    try {
      state.health = await api("/api/health");
      renderHealth();
    } catch (e) {
      state.health = { codex: "error", hermes: "error", ffmpeg: "error", ffprobe: "error", browser: "error", live_verified: "false" };
      renderHealth();
    }
  }

  function taskStateLabel(s) {
    const map = {
      NEW: "新建",
      BLOCKED: "受阻",
      DESIGNED: "已设计",
      QUOTED: "已报价",
      RUNNING: "运行中",
      PAUSED: "已暂停",
      DONE: "完成",
      FAILED: "失败",
      SUBMISSION_UNCERTAIN: "提交状态未知",
      DESIGNING: "设计中", PREPARING: "准备报价", APPROVED: "报价已批准",
      SUBMITTING: "正在提交", MONITORING: "等待官网完成", DOWNLOADING: "下载中", ANALYZING: "本地分析中", DELIVERED: "已交付"
    };
    return map[s] || String(s || "未知");
  }

  function renderTaskList() {
    const ul = el["task-list"];
    ul.textContent = "";
    if (!state.tasks.length) {
      const li = document.createElement("li");
      li.className = "empty-hint";
      li.textContent = "暂无任务。";
      ul.appendChild(li);
      return;
    }
    for (const t of state.tasks) {
      const li = document.createElement("li");
      li.className = "task-item" + (t.id === state.activeTaskId ? " active" : "");
      li.setAttribute("role", "button");
      li.setAttribute("tabindex", "0");
      li.setAttribute("aria-label", "选择任务 " + t.id);

      const top = document.createElement("div");
      top.className = "task-item-top";
      const idSpan = document.createElement("span");
      idSpan.className = "task-item-id";
      idSpan.textContent = t.id;
      const badge = document.createElement("span");
      badge.className = "state-badge";
      badge.textContent = taskStateLabel(t.state);
      top.appendChild(idSpan);
      top.appendChild(badge);

      const req = document.createElement("div");
      req.className = "task-item-req";
      req.textContent = t.requirements || "（无需求描述）";

      li.appendChild(top);
      li.appendChild(req);

      const activate = function () { selectTask(t.id); };
      li.addEventListener("click", activate);
      li.addEventListener("keydown", function (ev) {
        if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); activate(); }
      });
      ul.appendChild(li);
    }
  }

  async function loadTasks() {
    try {
      showError(el["list-error"], "");
      const data = await api("/api/tasks");
      state.tasks = Array.isArray(data) ? data : [];
      renderTaskList();
    } catch (e) {
      showError(el["list-error"], e.message);
    }
  }

  function closeEventSource() {
    if (state.eventSource) {
      try { state.eventSource.close(); } catch (e) { /* noop */ }
      state.eventSource = null;
    }
  }

  function openEventSource(id) {
    closeEventSource();
    const es = new EventSource("/api/tasks/" + encodeURIComponent(id) + "/events");
    es.onmessage = function (ev) {
      try {
        const task = JSON.parse(ev.data);
        if (task && task.id === state.activeTaskId) {
          state.activeTask = task;
          renderDetail(state.detailDirty);
        }
      } catch (e) { /* ignore malformed */ }
    };
    es.onerror = function () { /* EventSource 自动重连 */ };
    state.eventSource = es;
  }

  async function selectTask(id) {
    if (state.activeTaskId === id) return;
    state.activeTaskId = id;
    state.activeTask = null;
    state.detailDirty = false;
    state.materialFiles = [];
    renderTaskList();
    closeEventSource();
    clearMessages();
    try {
      const task = await api("/api/tasks/" + encodeURIComponent(id));
      state.activeTask = task;
      renderDetail(false);
      openEventSource(id);
    } catch (e) {
      showError(el["detail-error"], e.message);
    }
  }

  function renderDetail(preserveEdits) {
    const t = state.activeTask;
    if (!t) {
      el["detail-empty"].hidden = false;
      el["detail-panel"].hidden = true;
      return;
    }
    el["detail-empty"].hidden = true;
    el["detail-panel"].hidden = false;

    const meta = el["detail-meta"];
    meta.textContent = "";
    const addMeta = function (k, v) {
      const dt = document.createElement("dt");
      dt.textContent = k;
      const dd = document.createElement("dd");
      dd.textContent = v == null || v === "" ? "—" : String(v);
      meta.appendChild(dt);
      meta.appendChild(dd);
    };
    addMeta("任务 ID", t.id);
    addMeta("需求", t.requirements);
    addMeta("时长（秒）", t.duration_seconds);
    addMeta("比例", t.ratio);
    addMeta("需要音频", t.require_audio ? "是" : "否");
    addMeta("设备", t.device);
    addMeta("跳过语音", t.skip_speech ? "是" : "否");
    if (t.generation && typeof t.generation === "object") {
      addMeta("生成模型", t.generation.model);
      addMeta("生成模式", t.generation.mode);
      addMeta("分辨率", t.generation.resolution);
      addMeta("数量", t.generation.count);
    }

    const status = el["detail-status"];
    status.textContent = "";
    const addStatus = function (k, v) {
      const dt = document.createElement("dt");
      dt.textContent = k;
      const dd = document.createElement("dd");
      dd.textContent = v == null || v === "" ? "—" : String(v);
      status.appendChild(dt);
      status.appendChild(dd);
    };
    addStatus("状态", taskStateLabel(t.state));
    addStatus("技术状态", t.technical_status);
    addStatus("内容状态", t.content_status);
    addStatus("错误", t.error);

    const art = el["artifact-list"];
    art.textContent = "";
    if (Array.isArray(t.artifacts)) {
      for (const p of t.artifacts) {
        const li = document.createElement("li");
        const a = document.createElement("a");
        const segs = String(p).split("/").map(encodeURIComponent).join("/");
        a.href = "/api/tasks/" + encodeURIComponent(t.id) + "/files/" + segs;
        a.textContent = p;
        a.target = "_blank";
        a.rel = "noopener";
        li.appendChild(a);
        art.appendChild(li);
      }
    }
    if (!art.children.length) {
      const li = document.createElement("li");
      li.className = "empty-hint";
      li.textContent = "暂无产物。";
      art.appendChild(li);
    }

    if (!preserveEdits) {
      const design = t.design;
      if (design && typeof design === "object") {
        el["f-design-prompt"].value = design.prompt == null ? "" : String(design.prompt);
        el["f-design-design"].value = design.design == null ? "" : String(design.design);
        el["f-design-shots"].value = design.shots == null ? "" : (typeof design.shots === "string" ? design.shots : JSON.stringify(design.shots, null, 2));
      } else {
        el["f-design-prompt"].value = "";
        el["f-design-design"].value = "";
        el["f-design-shots"].value = "";
      }
    }

    const quote = t.quote;
    if (quote && typeof quote === "object") {
      el["quote-empty"].hidden = true;
      el["quote-meta"].hidden = false;
      el["quote-meta"].textContent = "";
      const addQuote = function (k, v) {
        const dt = document.createElement("dt");
        dt.textContent = k;
        const dd = document.createElement("dd");
        dd.textContent = v == null || v === "" ? "—" : String(v);
        el["quote-meta"].appendChild(dt);
        el["quote-meta"].appendChild(dd);
      };
      addQuote("本次积分", quote.credits);
      addQuote("当前余额", quote.balance);
      addQuote("绑定设计版本", t.design_version);
      if (typeof quote.evidence === "string" && quote.evidence) {
        const dt = document.createElement("dt"); dt.textContent = "报价证据";
        const dd = document.createElement("dd");
        const link = document.createElement("a"); link.textContent = "查看报价截图";
        link.href = "/api/tasks/" + encodeURIComponent(t.id) + "/files/" + quote.evidence.split("/").map(encodeURIComponent).join("/");
        link.target = "_blank"; link.rel = "noopener"; dd.appendChild(link);
        el["quote-meta"].appendChild(dt); el["quote-meta"].appendChild(dd);
      }
      const canApprove = t.state === "QUOTED" && quote.fingerprint;
      el["btn-approve"].hidden = !canApprove;
    } else {
      el["quote-empty"].hidden = false;
      el["quote-meta"].hidden = true;
      el["quote-meta"].textContent = "";
      el["btn-approve"].hidden = true;
    }

    refreshActionButtons();
  }

  function refreshActionButtons() {
    const t = state.activeTask;
    const s = t ? t.state : null;
    const busy = function (btn) { return state.pending.has(btn); };

    if (el["btn-start"]) {
      el["btn-start"].disabled = busy(el["btn-start"]) || !(s === "NEW" || s === "BLOCKED") || !!(t && t.design);
    }
    if (el["btn-prepare"]) {
      el["btn-prepare"].disabled = busy(el["btn-prepare"]) || s !== "DESIGNED";
    }
    if (el["btn-pause"]) {
      const active = ["DESIGNING", "PREPARING", "APPROVED", "SUBMITTING", "MONITORING", "DOWNLOADING", "ANALYZING", "DESIGNED", "QUOTED"].includes(s) && !t.paused;
      el["btn-pause"].disabled = busy(el["btn-pause"]) || !active;
    }
    if (el["btn-resume"]) {
      const resumable = s === "PAUSED" || s === "BLOCKED" || s === "SUBMISSION_UNCERTAIN";
      el["btn-resume"].disabled = busy(el["btn-resume"]) || !resumable;
    }
    if (el["btn-approve"]) {
      const hasFp = t && t.quote && t.quote.fingerprint;
      const can = s === "QUOTED" && !!hasFp;
      el["btn-approve"].hidden = !can;
    }
    if (el["btn-upload-materials"]) {
      el["btn-upload-materials"].disabled = busy(el["btn-upload-materials"]) || !state.materialFiles.length || s !== "NEW";
    }
    if (el["btn-save-design"]) {
      el["btn-save-design"].disabled = busy(el["btn-save-design"]) || !t || t.attempted || !["NEW", "DESIGNED", "QUOTED", "BLOCKED", "PAUSED"].includes(s);
    }
  }

  function renderMaterialQueue() {
    const ul = el["material-queue"];
    ul.textContent = "";
    state.materialFiles.forEach(function (file, idx) {
      const li = document.createElement("li");
      li.className = "material-item";

      const name = document.createElement("span");
      name.className = "material-name";
      name.textContent = (idx + 1) + ". " + file.name;
      li.appendChild(name);

      const up = document.createElement("button");
      up.type = "button";
      up.className = "material-btn";
      up.textContent = "上移";
      up.setAttribute("aria-label", "上移 " + file.name);
      up.disabled = idx === 0;
      up.addEventListener("click", function () { moveMaterial(idx, -1); });
      li.appendChild(up);

      const down = document.createElement("button");
      down.type = "button";
      down.className = "material-btn";
      down.textContent = "下移";
      down.setAttribute("aria-label", "下移 " + file.name);
      down.disabled = idx === state.materialFiles.length - 1;
      down.addEventListener("click", function () { moveMaterial(idx, 1); });
      li.appendChild(down);

      const del = document.createElement("button");
      del.type = "button";
      del.className = "material-btn";
      del.textContent = "移除";
      del.setAttribute("aria-label", "移除 " + file.name);
      del.addEventListener("click", function () { removeMaterial(idx); });
      li.appendChild(del);

      ul.appendChild(li);
    });
    refreshActionButtons();
  }

  function moveMaterial(idx, delta) {
    const next = idx + delta;
    if (next < 0 || next >= state.materialFiles.length) return;
    const arr = state.materialFiles;
    const tmp = arr[idx];
    arr[idx] = arr[next];
    arr[next] = tmp;
    renderMaterialQueue();
  }

  function removeMaterial(idx) {
    state.materialFiles.splice(idx, 1);
    renderMaterialQueue();
  }

  async function createTask(ev) {
    ev.preventDefault();
    clearMessages();
    const form = el["create-form"];
    const requirements = el["f-requirements"].value.trim();
    const duration = parseFloat(el["f-duration"].value);
    const ratio = el["f-ratio"].value;
    const requireAudio = el["f-require-audio"].checked;
    const device = el["f-device"].value;
    const skipSpeech = el["f-skip-speech"].checked;
    const override = el["f-override"].checked;

    if (!requirements) { showError(el["create-error"], "请输入需求描述。"); return; }
    if (!isFinite(duration) || duration <= 0) { showError(el["create-error"], "时长必须为正数。"); return; }

    const body = {
      requirements: requirements,
      duration_seconds: duration,
      ratio: ratio,
      require_audio: requireAudio,
      device: device,
      skip_speech: skipSpeech
    };

    if (override) {
      const model = el["f-model"].value.trim();
      const mode = el["f-mode"].value.trim();
      const resolution = el["f-resolution"].value.trim();
      const overrideSource = el["f-override-source"].value.trim();
      if (!model || !mode || !resolution || !overrideSource) {
        showError(el["create-error"], "自定义生成参数需填写 model、mode、resolution 与 override_source。");
        return;
      }
      body.generation = {
        model: model,
        mode: mode,
        resolution: resolution,
        count: 1,
        override_source: overrideSource
      };
    }

    const submitBtn = form.querySelector('button[type="submit"]');
    await withPending(submitBtn, async function () {
      try {
        const task = await api("/api/tasks", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body)
        });
        form.reset();
        el["f-duration"].value = "30";
        el["f-require-audio"].checked = true;
        el["f-device"].value = "cuda";
        el["f-skip-speech"].checked = false;
        el["f-override"].checked = false;
        el["override-fields"].hidden = true;
        await loadTasks();
        if (task && task.id) {
          await selectTask(task.id);
        }
      } catch (e) {
        showError(el["create-error"], e.message);
      }
    });
  }

  async function uploadMaterials() {
    if (!state.activeTaskId) return;
    if (!state.materialFiles.length) {
      showError(el["materials-error"], "请先选择文件。");
      return;
    }
    showError(el["materials-error"], "");
    showSuccess(el["materials-success"], "");
    const fd = new FormData();
    for (const f of state.materialFiles) {
      fd.append("files", f, f.name);
    }
    await withPending(el["btn-upload-materials"], async function () {
      try {
        await api("/api/tasks/" + encodeURIComponent(state.activeTaskId) + "/materials", {
          method: "POST",
          body: fd
        });
        state.materialFiles = [];
        renderMaterialQueue();
        el["f-materials"].value = "";
        showSuccess(el["materials-success"], "材料上传成功。");
        const task = await api("/api/tasks/" + encodeURIComponent(state.activeTaskId));
        state.activeTask = task;
        renderDetail(state.detailDirty);
      } catch (e) {
        showError(el["materials-error"], e.message);
      }
    });
  }

  function materialSignature(materials) {
    if (!Array.isArray(materials)) return "";
    return materials.map(function (m) { return String(m && m.id); }).join("|");
  }

  function updateDetailFromTask(task) {
    const prev = state.activeTask;
    const changed = !prev ||
      prev.state !== task.state ||
      prev.error !== task.error ||
      prev.technical_status !== task.technical_status ||
      prev.content_status !== task.content_status ||
      materialSignature(prev.materials) !== materialSignature(task.materials) ||
      JSON.stringify(prev.quote) !== JSON.stringify(task.quote) ||
      JSON.stringify(prev.artifacts) !== JSON.stringify(task.artifacts);
    state.activeTask = task;
    if (changed) {
      renderDetail(state.detailDirty);
    }
  }

  async function actionPost(suffix, btn, errNode, body) {
    if (!state.activeTaskId) return;
    showError(errNode, "");
    await withPending(btn, async function () {
      try {
        const opts = { method: "POST" };
        if (body !== undefined) {
          opts.headers = { "Content-Type": "application/json" };
          opts.body = JSON.stringify(body);
        }
        const task = await api("/api/tasks/" + encodeURIComponent(state.activeTaskId) + "/" + suffix, opts);
        if (task && task.id) {
          updateDetailFromTask(task);
        } else {
          const fresh = await api("/api/tasks/" + encodeURIComponent(state.activeTaskId));
          updateDetailFromTask(fresh);
        }
        loadTasks();
      } catch (e) {
        showError(errNode, e.message);
      }
    });
  }

  function doStart() { actionPost("start", el["btn-start"], el["action-error"]); }
  function doPrepare() { actionPost("prepare", el["btn-prepare"], el["action-error"]); }
  function doPause() { actionPost("pause", el["btn-pause"], el["action-error"]); }
  function doResume() { actionPost("resume", el["btn-resume"], el["action-error"]); }

  async function saveDesign() {
    if (!state.activeTaskId) return;
    showError(el["design-error"], "");
    showSuccess(el["design-success"], "");
    const shotsRaw = el["f-design-shots"].value.trim();
    let shots = shotsRaw;
    if (shotsRaw) {
      try {
        shots = JSON.parse(shotsRaw);
      } catch (e) {
        showError(el["design-error"], "分镜 JSON 格式无效：" + e.message);
        return;
      }
    } else {
      shots = null;
    }
    const body = {
      design: el["f-design-design"].value,
      shots: shots,
      prompt: el["f-design-prompt"].value
    };
    await withPending(el["btn-save-design"], async function () {
      try {
        const task = await api("/api/tasks/" + encodeURIComponent(state.activeTaskId) + "/design", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body)
        });
        state.detailDirty = false;
        if (task && task.id) {
          updateDetailFromTask(task);
        } else {
          const fresh = await api("/api/tasks/" + encodeURIComponent(state.activeTaskId));
          updateDetailFromTask(fresh);
        }
        showSuccess(el["design-success"], "设计已保存，报价已失效。");
        loadTasks();
      } catch (e) {
        showError(el["design-error"], e.message);
      }
    });
  }

  async function approveQuote() {
    if (!state.activeTaskId) return;
    const t = state.activeTask;
    if (!t || !t.quote || !t.quote.fingerprint) {
      showError(el["quote-error"], "缺少报价指纹，无法确认。");
      return;
    }
    const credits = t.quote.credits;
    const msg = "确认本次报价？将消耗积分：" + credits + "。注意：本工具不会自动放大（upscale）。";
    if (!window.confirm(msg)) return;
    showError(el["quote-error"], "");
    await withPending(el["btn-approve"], async function () {
      try {
        const task = await api("/api/tasks/" + encodeURIComponent(state.activeTaskId) + "/approve", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ fingerprint: t.quote.fingerprint })
        });
        if (task && task.id) {
          updateDetailFromTask(task);
        } else {
          const fresh = await api("/api/tasks/" + encodeURIComponent(state.activeTaskId));
          updateDetailFromTask(fresh);
        }
        loadTasks();
      } catch (e) {
        showError(el["quote-error"], e.message);
      }
    });
  }

  async function openBrowserLogin() {
    showError(el["list-error"], "");
    await withPending(el["btn-browser-login"], async function () {
      try {
        await api("/api/browser/login", { method: "POST" });
      } catch (e) {
        showError(el["list-error"], "打开浏览器失败：" + e.message);
      }
    });
  }

  async function refreshAll() {
    await withPending(el["btn-refresh"], async function () {
      await loadTasks();
    });
  }

  async function checkHealth() {
    await withPending(el["btn-health"], async function () {
      await loadHealth();
    });
  }

  function bind() {
    el["create-form"].addEventListener("submit", createTask);
    el["f-override"].addEventListener("change", function () {
      el["override-fields"].hidden = !el["f-override"].checked;
    });
    el["f-materials"].addEventListener("change", function () {
      const files = Array.from(el["f-materials"].files || []);
      state.materialFiles = state.materialFiles.concat(files);
      el["f-materials"].value = "";
      renderMaterialQueue();
    });
    el["btn-upload-materials"].addEventListener("click", uploadMaterials);
    el["btn-start"].addEventListener("click", doStart);
    el["btn-prepare"].addEventListener("click", doPrepare);
    el["btn-pause"].addEventListener("click", doPause);
    el["btn-resume"].addEventListener("click", doResume);
    el["btn-save-design"].addEventListener("click", saveDesign);
    el["btn-approve"].addEventListener("click", approveQuote);
    el["btn-browser-login"].addEventListener("click", openBrowserLogin);
    el["btn-refresh"].addEventListener("click", refreshAll);
    el["btn-health"].addEventListener("click", checkHealth);
    el["btn-help-dismiss"].addEventListener("click", function () {
      el["help-panel"].hidden = true;
    });

    for (const id of ["f-design-prompt", "f-design-design", "f-design-shots"]) {
      el[id].addEventListener("input", function () { state.detailDirty = true; });
    }

    window.addEventListener("beforeunload", closeEventSource);
  }

  async function init() {
    cache();
    bind();
    renderMaterialQueue();
    clearMessages();
    try {
      await loadSession();
    } catch (e) {
      showError(el["list-error"], "会话初始化失败：" + e.message);
    }
    await Promise.allSettled([loadHealth(), loadTasks()]);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
