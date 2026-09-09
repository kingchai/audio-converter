(() => {
  const state = {
    files: [],
    jobs: [],
    busy: false,
    pollTimer: null,
    maxFiles: 10,
    maxFileSize: 200 * 1024 * 1024,
    maxTotalSize: 500 * 1024 * 1024,
    allowed: new Set(["wav", "m4a", "aac", "flac", "ogg", "oga", "wma", "aiff", "aif", "mp3", "mp4", "mov", "webm"]),
  };

  const $ = (id) => document.getElementById(id);
  const dropZone = $("dropZone");
  const fileInput = $("fileInput");
  const fileSection = $("fileSection");
  const fileList = $("fileList");
  const fileCount = $("fileCount");
  const queueSize = $("queueSize");
  const clearButton = $("clearButton");
  const controlPanel = $("controlPanel");
  const convertButton = $("convertButton");
  const resultsSection = $("resultsSection");
  const resultsTitle = $("resultsTitle");
  const resultSummary = $("resultSummary");
  const resultList = $("resultList");
  const downloadAllButton = $("downloadAllButton");
  const notice = $("notice");
  const noticeText = notice.querySelector("p");
  const noticeClose = notice.querySelector("button");

  function formatBytes(value) {
    if (!value) return "0 B";
    const units = ["B", "KB", "MB", "GB"];
    const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
    const number = value / (1024 ** index);
    return `${number >= 10 || index === 0 ? number.toFixed(0) : number.toFixed(1)} ${units[index]}`;
  }

  function extensionOf(name) {
    const parts = name.toLowerCase().split(".");
    return parts.length > 1 ? parts.pop() : "";
  }

  function extensionLabel(name) {
    return extensionOf(name).toUpperCase() || "FILE";
  }

  function showNotice(message, type = "info") {
    notice.className = `notice ${type === "error" ? "is-error" : type === "success" ? "is-success" : ""}`;
    noticeText.textContent = message;
    notice.hidden = false;
  }

  function hideNotice() {
    notice.hidden = true;
  }

  function setBusy(value) {
    state.busy = value;
    convertButton.disabled = value;
    clearButton.disabled = value;
    convertButton.querySelector(".button-label").textContent = value ? "正在准备…" : "开始转换";
  }

  function updateQualitySelection() {
    document.querySelectorAll(".quality-option").forEach((option) => {
      option.classList.toggle("is-selected", option.querySelector("input").checked);
    });
  }

  function createFileCard(file, index) {
    const card = document.createElement("article");
    card.className = "file-card";
    card.style.setProperty("--i", index);

    const glyph = document.createElement("div");
    glyph.className = "file-glyph";
    glyph.textContent = extensionLabel(file.name);

    const info = document.createElement("div");
    info.className = "file-info";
    const name = document.createElement("span");
    name.className = "file-name";
    name.title = file.name;
    name.textContent = file.name;
    const meta = document.createElement("span");
    meta.className = "file-meta";
    meta.textContent = `${formatBytes(file.size)} · 等待转换`;
    info.append(name, meta);

    const remove = document.createElement("button");
    remove.className = "file-remove";
    remove.type = "button";
    remove.setAttribute("aria-label", `移除 ${file.name}`);
    remove.textContent = "×";
    remove.addEventListener("click", () => {
      if (state.busy) return;
      state.files.splice(index, 1);
      renderQueue();
    });

    card.append(glyph, info, remove);
    return card;
  }

  function renderQueue() {
    const total = state.files.reduce((sum, file) => sum + file.size, 0);
    fileCount.textContent = state.files.length;
    queueSize.textContent = formatBytes(total);
    fileList.replaceChildren(...state.files.map(createFileCard));
    const hasFiles = state.files.length > 0;
    fileSection.hidden = !hasFiles;
    controlPanel.hidden = !hasFiles || state.busy;
    clearButton.hidden = !hasFiles;
    if (!state.busy) {
      convertButton.querySelector(".button-label").textContent = "开始转换";
    }
  }

  function addFiles(fileCollection) {
    if (state.busy) return;
    const incoming = Array.from(fileCollection || []);
    if (!incoming.length) return;
    const existingKeys = new Set(state.files.map((file) => `${file.name}:${file.size}:${file.lastModified}`));
    const next = [];
    let rejected = "";

    incoming.forEach((file) => {
      const extension = extensionOf(file.name);
      const key = `${file.name}:${file.size}:${file.lastModified}`;
      if (!state.allowed.has(extension)) {
        rejected = `${file.name} 暂不支持，请更换格式`;
        return;
      }
      if (file.size === 0) {
        rejected = `${file.name} 是空文件，请重新选择`;
        return;
      }
      if (file.size > state.maxFileSize) {
        rejected = `${file.name} 超过单文件 200MB 限制`;
        return;
      }
      if (existingKeys.has(key)) return;
      existingKeys.add(key);
      next.push(file);
    });

    if (state.files.length + next.length > state.maxFiles) {
      showNotice(`一次最多上传 ${state.maxFiles} 个文件`, "error");
      return;
    }
    const total = state.files.reduce((sum, file) => sum + file.size, 0) + next.reduce((sum, file) => sum + file.size, 0);
    if (total > state.maxTotalSize) {
      showNotice("本次上传总大小不能超过 500MB", "error");
      return;
    }
    if (rejected) showNotice(rejected, "error");
    if (next.length) {
      hideNotice();
      state.files.push(...next);
      renderQueue();
    }
    fileInput.value = "";
  }

  function errorMessage(payload, fallback = "操作失败，请稍后重试") {
    return payload?.error?.message || payload?.message || fallback;
  }

  async function responseJson(response) {
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(errorMessage(payload));
    return payload;
  }

  function statusLabel(status) {
    return ({ queued: "排队中", converting: "正在转换", success: "转换完成", error: "转换失败" })[status] || "处理中";
  }

  function createResultCard(job, index) {
    const card = document.createElement("article");
    card.className = `file-card result-card ${job.status === "success" ? "is-success" : job.status === "error" ? "is-error" : ""}`;
    card.style.setProperty("--i", index);

    const glyph = document.createElement("div");
    glyph.className = "file-glyph";
    glyph.textContent = "MP3";

    const info = document.createElement("div");
    info.className = "file-info";
    const name = document.createElement("span");
    name.className = "file-name";
    name.title = job.output_filename || job.original_filename;
    name.textContent = job.output_filename || job.original_filename;
    const status = document.createElement("span");
    status.className = "result-status";
    status.textContent = job.status === "error" ? (job.error || "转换失败") : `${statusLabel(job.status)}${job.status === "converting" ? ` · ${job.progress || 0}%` : ""}`;
    info.append(name, status);

    const actions = document.createElement("div");
    actions.className = "result-actions";
    if (job.status === "success") {
      const link = document.createElement("a");
      link.className = "download-button";
      link.href = `/api/download/${encodeURIComponent(job.id)}`;
      link.download = job.output_filename || "converted.mp3";
      link.innerHTML = "下载 <span aria-hidden=\"true\">↓</span>";
      actions.append(link);
    }

    card.append(glyph, info, actions);
    if (job.status === "queued" || job.status === "converting") {
      const progressWrap = document.createElement("div");
      progressWrap.className = "progress-wrap";
      const progress = document.createElement("div");
      progress.className = "progress-bar";
      progress.style.width = `${Math.max(0, Math.min(100, job.progress || 0))}%`;
      progressWrap.append(progress);
      card.append(progressWrap);
    }
    return card;
  }

  function renderResults() {
    if (!state.jobs.length) {
      resultsSection.hidden = true;
      return;
    }
    const completed = state.jobs.filter((job) => job.status === "success").length;
    const failed = state.jobs.filter((job) => job.status === "error").length;
    const finished = completed + failed === state.jobs.length;
    resultsSection.hidden = false;
    resultsTitle.textContent = finished ? (failed ? "有文件需要重试" : "转换完成") : "正在转换";
    resultSummary.replaceChildren();
    [
      `${completed} 个已完成`,
      failed ? `${failed} 个失败` : `${state.jobs.length} 个任务进行中`,
      `输出 MP3 · ${state.jobs[0]?.bitrate || 192} kbps`,
    ].forEach((text) => {
      const span = document.createElement("span");
      span.textContent = text;
      resultSummary.append(span);
    });
    resultList.replaceChildren(...state.jobs.map(createResultCard));
    const successfulIds = state.jobs.filter((job) => job.status === "success").map((job) => job.id);
    downloadAllButton.hidden = successfulIds.length < 2;
    downloadAllButton.dataset.jobIds = JSON.stringify(successfulIds);
  }

  async function pollJobs() {
    if (!state.jobs.length) return;
    try {
      const responses = await Promise.all(state.jobs.map((job) => fetch(`/api/convert/${encodeURIComponent(job.id)}`, { credentials: "same-origin" }).then(responseJson)));
      state.jobs = responses.map((payload) => payload.data);
      renderResults();
      if (state.jobs.some((job) => job.status === "queued" || job.status === "converting")) {
        state.pollTimer = window.setTimeout(pollJobs, 850);
        return;
      }
      state.files = [];
      setBusy(false);
      renderQueue();
      showNotice(
        state.jobs.some((job) => job.status === "error") ? "部分文件没有完成转换，请检查失败原因。" : "全部文件已转换完成，可以下载 MP3。",
        state.jobs.some((job) => job.status === "error") ? "error" : "success",
      );
    } catch (error) {
      setBusy(false);
      showNotice(error.message || "无法获取转换进度，请刷新页面重试", "error");
    }
  }

  async function startConversion() {
    if (!state.files.length || state.busy) return;
    hideNotice();
    setBusy(true);
    const formData = new FormData();
    state.files.forEach((file) => formData.append("files", file, file.name));
    formData.append("bitrate", document.querySelector("input[name=bitrate]:checked").value);
    try {
      const payload = await fetch("/api/convert", { method: "POST", body: formData, credentials: "same-origin" }).then(responseJson);
      state.jobs = payload.data || [];
      renderResults();
      resultsSection.scrollIntoView({ behavior: "smooth", block: "start" });
      window.clearTimeout(state.pollTimer);
      state.pollTimer = window.setTimeout(pollJobs, 260);
    } catch (error) {
      setBusy(false);
      showNotice(error.message || "转换服务暂时不可用，请稍后重试", "error");
    }
  }

  function clearAll() {
    if (state.busy) return;
    state.files = [];
    state.jobs = [];
    renderQueue();
    resultsSection.hidden = true;
    hideNotice();
    fileInput.value = "";
  }

  async function downloadAll() {
    const ids = JSON.parse(downloadAllButton.dataset.jobIds || "[]");
    if (ids.length < 2) return;
    try {
      const response = await fetch("/api/download-batch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ job_ids: ids }),
      });
      if (!response.ok) throw new Error("批量下载暂时不可用，请稍后重试");
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "sonora-mp3-files.zip";
      link.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      showNotice(error.message, "error");
    }
  }

  async function loadCapabilities() {
    try {
      const payload = await fetch("/api/capabilities", { credentials: "same-origin" }).then(responseJson);
      state.maxFiles = payload.max_files || state.maxFiles;
      state.maxFileSize = payload.max_file_size || state.maxFileSize;
      state.maxTotalSize = payload.max_total_size || state.maxTotalSize;
    } catch (_error) {
      // The page remains usable with safe defaults if the capability endpoint is unavailable.
    }
  }

  dropZone.addEventListener("click", () => fileInput.click());
  dropZone.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      fileInput.click();
    }
  });
  fileInput.addEventListener("change", () => addFiles(fileInput.files));
  ["dragenter", "dragover"].forEach((eventName) => dropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropZone.classList.add("is-dragging");
  }));
  ["dragleave", "drop"].forEach((eventName) => dropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropZone.classList.remove("is-dragging");
  }));
  dropZone.addEventListener("drop", (event) => addFiles(event.dataTransfer.files));
  clearButton.addEventListener("click", clearAll);
  convertButton.addEventListener("click", () => {
    if (!state.files.length && !state.busy) fileInput.click();
    else startConversion();
  });
  downloadAllButton.addEventListener("click", downloadAll);
  noticeClose.addEventListener("click", hideNotice);
  document.querySelectorAll(".quality-option input").forEach((input) => input.addEventListener("change", updateQualitySelection));

  updateQualitySelection();
  renderQueue();
  loadCapabilities();
})();
