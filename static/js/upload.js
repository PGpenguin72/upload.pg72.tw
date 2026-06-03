"use strict";

const CHUNK_SIZE = 5 * 1024 * 1024; // 5 MB

// ── State ──────────────────────────────────────────────────────────────────
let sessionToken = null;
let sessionCode = null;
let files = [];       // { file, id, status, progress }
let uploading = false;

// ── DOM refs ───────────────────────────────────────────────────────────────
const $ = (id) => document.getElementById(id);
const codeSection   = $("code-section");
const uploadSection = $("upload-section");
const codeInput     = $("code-input");
const validateBtn   = $("validate-btn");
const scanBtn       = $("scan-btn");
const qrWrap        = $("qr-scanner-wrap");
const qrVideo       = $("qr-video");
const dropzone      = $("dropzone");
const fileInput     = $("file-input");
const fileList      = $("file-list");
const uploadBtn     = $("upload-btn");
const codeAlert     = $("code-alert");
const uploadAlert   = $("upload-alert");
const sessionInfo   = $("session-info");

// ── Code input filter ──────────────────────────────────────────────────────
const SAFE_CHARS = new Set("ABCDEFGHJKLMNPQRSTUVWXYZ23456789");

codeInput.addEventListener("input", () => {
  const raw = codeInput.value.toUpperCase().split("").filter((c) => SAFE_CHARS.has(c)).join("");
  codeInput.value = raw.slice(0, 16);
});

codeInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") validateCode();
});

validateBtn.addEventListener("click", validateCode);

async function validateCode() {
  const code = codeInput.value.trim();
  if (code.length !== 16) {
    showAlert(codeAlert, "error", "請輸入完整的 16 位上傳碼");
    return;
  }
  validateBtn.disabled = true;
  validateBtn.textContent = "驗證中…";
  hideAlert(codeAlert);

  try {
    const res = await api("/api/validate", "POST", { code });
    sessionToken = res.session_token;
    sessionCode  = res.code;

    codeSection.style.display = "none";
    uploadSection.style.display = "block";
    stopQrScanner();

    const exp = new Date(res.expires_at * 1000).toLocaleTimeString();
    sessionInfo.textContent = `上傳碼：${sessionCode}　到期時間：${exp}`;
  } catch (err) {
    showAlert(codeAlert, "error", err.message || "驗證失敗，請確認上傳碼是否正確");
  } finally {
    validateBtn.disabled = false;
    validateBtn.textContent = "開始上傳";
  }
}

// ── QR Scanner ─────────────────────────────────────────────────────────────
let qrStream = null;
let qrAnimFrame = null;

scanBtn.addEventListener("click", toggleQrScanner);

async function toggleQrScanner() {
  if (qrWrap.classList.contains("show")) {
    stopQrScanner();
    return;
  }
  try {
    qrStream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } });
    qrVideo.srcObject = qrStream;
    await qrVideo.play();
    qrWrap.classList.add("show");
    scanBtn.textContent = "停止掃描";
    scanQrFrame();
  } catch {
    showAlert(codeAlert, "error", "無法存取相機");
  }
}

function stopQrScanner() {
  if (qrStream) { qrStream.getTracks().forEach((t) => t.stop()); qrStream = null; }
  if (qrAnimFrame) { cancelAnimationFrame(qrAnimFrame); qrAnimFrame = null; }
  qrWrap.classList.remove("show");
  scanBtn.textContent = "掃描 QR Code";
}

function scanQrFrame() {
  if (!qrStream) return;
  const canvas = document.createElement("canvas");
  canvas.width  = qrVideo.videoWidth;
  canvas.height = qrVideo.videoHeight;
  if (canvas.width && canvas.height) {
    const ctx = canvas.getContext("2d");
    ctx.drawImage(qrVideo, 0, 0);
    const imgData = ctx.getImageData(0, 0, canvas.width, canvas.height);
    const code = jsQR(imgData.data, canvas.width, canvas.height);
    if (code) {
      const url = new URL(code.data);
      const extracted = url.searchParams.get("code");
      if (extracted) {
        codeInput.value = extracted.toUpperCase().slice(0, 16);
        stopQrScanner();
        validateCode();
        return;
      }
    }
  }
  qrAnimFrame = requestAnimationFrame(scanQrFrame);
}

// ── Dropzone ───────────────────────────────────────────────────────────────
dropzone.addEventListener("click", () => fileInput.click());
fileInput.addEventListener("change", () => addFiles(fileInput.files));

dropzone.addEventListener("dragover", (e) => { e.preventDefault(); dropzone.classList.add("drag-over"); });
dropzone.addEventListener("dragleave", () => dropzone.classList.remove("drag-over"));
dropzone.addEventListener("drop", (e) => {
  e.preventDefault();
  dropzone.classList.remove("drag-over");
  addFiles(e.dataTransfer.files);
});

function addFiles(fileObjects) {
  for (const f of fileObjects) {
    files.push({ file: f, id: crypto.randomUUID(), status: "pending", progress: 0 });
  }
  renderFileList();
  uploadBtn.disabled = files.length === 0;
}

function renderFileList() {
  fileList.innerHTML = "";
  for (const item of files) {
    const el = document.createElement("div");
    el.className = "file-item";
    el.innerHTML = `
      <div class="file-item-header">
        <span class="file-name">${escHtml(item.file.name)}</span>
        <span class="file-size">${fmtSize(item.file.size)}</span>
        <span class="file-status ${item.status}" id="status-${item.id}">${statusLabel(item.status)}</span>
      </div>
      <div class="progress-bar">
        <div class="progress-fill ${item.status === "done" ? "done" : item.status === "error" ? "error" : ""}"
             id="prog-${item.id}"
             style="width:${item.progress * 100}%"></div>
      </div>`;
    fileList.appendChild(el);
  }
}

function updateFileProgress(id, progress, status) {
  const item = files.find((f) => f.id === id);
  if (!item) return;
  item.progress = progress;
  item.status   = status;

  const prog   = $(`prog-${id}`);
  const statusEl = $(`status-${id}`);
  if (prog) {
    prog.style.width = `${progress * 100}%`;
    prog.className = `progress-fill${status === "done" ? " done" : status === "error" ? " error" : ""}`;
  }
  if (statusEl) {
    statusEl.textContent = statusLabel(status);
    statusEl.className   = `file-status ${status}`;
  }
}

uploadBtn.addEventListener("click", startUpload);

async function startUpload() {
  if (uploading || !sessionToken) return;
  uploading = true;
  uploadBtn.disabled = true;
  hideAlert(uploadAlert);

  const pending = files.filter((f) => f.status === "pending");
  let allOk = true;

  for (const item of pending) {
    try {
      updateFileProgress(item.id, 0, "uploading");
      await uploadFile(item);
      updateFileProgress(item.id, 1, "done");
    } catch (err) {
      updateFileProgress(item.id, item.progress, "error");
      allOk = false;
    }
  }

  if (allOk) {
    showAlert(uploadAlert, "success", `上傳完成！共 ${pending.length} 個檔案`);
  } else {
    showAlert(uploadAlert, "error", "部分檔案上傳失敗，請重試");
  }

  uploading = false;
  uploadBtn.disabled = files.filter((f) => f.status === "pending").length === 0;
}

async function uploadFile(item) {
  const { file, id } = item;
  const totalChunks = Math.max(1, Math.ceil(file.size / CHUNK_SIZE));

  // Init
  const { upload_id } = await api("/api/upload/init", "POST", {
    filename:     file.name,
    filesize:     file.size,
    total_chunks: totalChunks,
  });

  // Upload chunks
  for (let i = 0; i < totalChunks; i++) {
    const start = i * CHUNK_SIZE;
    const end   = Math.min(start + CHUNK_SIZE, file.size);
    const chunk = file.slice(start, end);

    const form = new FormData();
    form.append("chunk", chunk, "chunk");

    const resp = await fetch(`/api/upload/${upload_id}/chunk/${i}`, {
      method:  "PUT",
      headers: { "X-Session-Token": sessionToken },
      body:    form,
    });
    if (!resp.ok) throw new Error(await resp.text());

    updateFileProgress(id, (i + 1) / totalChunks * 0.95, "uploading");
  }

  // Complete
  await api(`/api/upload/${upload_id}/complete`, "POST", null);
}

// ── Helpers ────────────────────────────────────────────────────────────────
async function api(path, method, body) {
  const opts = {
    method,
    headers: { "Content-Type": "application/json" },
  };
  if (sessionToken) opts.headers["X-Session-Token"] = sessionToken;
  if (body !== null && body !== undefined) opts.body = JSON.stringify(body);

  const res = await fetch(path, opts);
  if (!res.ok) {
    const json = await res.json().catch(() => ({}));
    throw new Error(json.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

function showAlert(el, type, msg) {
  el.className = `alert alert-${type} show`;
  el.textContent = msg;
}
function hideAlert(el) { el.className = "alert"; }
function statusLabel(s) {
  return { pending: "待上傳", uploading: "上傳中…", done: "完成 ✓", error: "失敗 ✗" }[s] ?? s;
}
function fmtSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
}
function escHtml(str) {
  return str.replace(/[&<>"']/g, (c) => ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;" }[c]));
}
