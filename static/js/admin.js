"use strict";

const { escapeHtml: escHtml, isUploadCode, isCodeId } = globalThis.PG72AdminSecurity;
let csrfToken = null;

// ── Init ───────────────────────────────────────────────────────────────────
(async () => {
  await loadMe();
  await Promise.all([loadStats(), loadCodes(), loadUploads()]);
  setInterval(async () => { await loadStats(); await loadCodes(); await loadUploads(); }, 30000);
})();

async function loadMe() {
  try {
    const { email, role, csrf_token } = await api("/admin/api/me");
    csrfToken = csrf_token;
    document.getElementById("admin-email").textContent = `${email} · ${role}`;
  } catch {}
}

document.getElementById("logout-btn").addEventListener("click", async () => {
  try {
    await api("/admin/logout", "POST");
    window.location.assign("/admin/logged-out");
  } catch (err) {
    alert("登出失敗：" + err.message);
  }
});

async function loadStats() {
  try {
    const s = await api("/admin/api/stats");
    document.getElementById("stat-total-codes").textContent  = s.total_codes;
    document.getElementById("stat-active-codes").textContent = s.active_codes;
    document.getElementById("stat-uploads").textContent      = s.total_uploads;
    document.getElementById("stat-size").textContent         = fmtSize(s.total_size);
  } catch {}
}

// ── Codes ──────────────────────────────────────────────────────────────────
async function loadCodes() {
  try {
    const codes = await api("/admin/api/codes");
    const tbody = document.getElementById("codes-tbody");
    const now   = Date.now() / 1000;
    tbody.innerHTML = codes.filter((c) => isCodeId(c.id) && isUploadCode(c.code)).map((c) => {
      const active   = !c.is_revoked && c.expires_at > now;
      const expired  = !c.is_revoked && c.expires_at <= now;
      const revoked  = c.is_revoked;
      const badge    = active  ? `<span class="status-badge status-active">● 有效</span>`
                     : revoked ? `<span class="status-badge status-revoked">● 已撤銷</span>`
                     :           `<span class="status-badge status-expired">● 已過期</span>`;
      const remaining = active ? `${Math.max(0, Math.floor((c.expires_at - now) / 60))} 分鐘後到期` : "—";
      const actions = active
        ? `<button class="btn btn-outline btn-sm" type="button" data-code-action="qr" data-code-id="${c.id}">QR</button>
           <button class="btn btn-danger btn-sm" type="button" data-code-action="revoke" data-code-id="${c.id}">撤銷</button>`
        : `<button class="btn btn-outline btn-sm" type="button" data-code-action="qr" data-code-id="${c.id}">QR</button>`;
      const uploadCount = Number.isFinite(Number(c.upload_count)) ? Number(c.upload_count) : 0;
      return `<tr>
        <td><span class="code-badge">${c.code}</span></td>
        <td>${badge}</td>
        <td>${remaining}</td>
        <td>${uploadCount}</td>
        <td style="white-space:nowrap">${actions}</td>
      </tr>`;
    }).join("") || `<tr><td colspan="5" style="text-align:center;color:var(--text-2)">尚無上傳碼</td></tr>`;
  } catch {}
}

document.getElementById("codes-tbody").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-code-action]");
  if (!button) return;
  const codeId = button.dataset.codeId;
  if (!isCodeId(codeId)) return;
  if (button.dataset.codeAction === "qr") showQr(codeId);
  if (button.dataset.codeAction === "revoke") revokeCode(codeId);
});

document.getElementById("gen-code-btn").addEventListener("click", async () => {
  try {
    const data = await api("/admin/api/codes", "POST");
    showCodeModal(data);
    await loadStats();
    await loadCodes();
  } catch (err) {
    alert("產生失敗：" + err.message);
  }
});

async function revokeCode(codeId) {
  if (!confirm("確定要撤銷這個上傳碼嗎？")) return;
  try {
    await api(`/admin/api/codes/${codeId}`, "DELETE");
    await loadStats();
    await loadCodes();
  } catch (err) {
    alert("撤銷失敗：" + err.message);
  }
}

async function showQr(codeId) {
  try {
    const data = await api(`/admin/api/codes/${codeId}/qr`);
    showCodeModal(data);
  } catch {}
}

// ── Uploads ────────────────────────────────────────────────────────────────
async function loadUploads() {
  try {
    const uploads = await api("/admin/api/uploads");
    const tbody   = document.getElementById("uploads-tbody");
    tbody.innerHTML = uploads.map((u) => `<tr>
      <td>${escHtml(u.original_filename)}</td>
      <td><span class="code-badge">${escHtml(u.code)}</span></td>
      <td>${fmtSize(u.file_size)}</td>
      <td>${escHtml(u.mime_type || "—")}</td>
      <td>${new Date(u.uploaded_at * 1000).toLocaleString()}</td>
    </tr>`).join("") || `<tr><td colspan="5" style="text-align:center;color:var(--text-2)">尚無上傳紀錄</td></tr>`;
  } catch {}
}

// ── Modal ──────────────────────────────────────────────────────────────────
function showCodeModal(data) {
  document.getElementById("modal-code").textContent = data.code;
  document.getElementById("modal-qr").src = `data:image/png;base64,${data.qr}`;
  document.getElementById("modal-url").textContent  = data.url;
  const exp = new Date(data.expires_at * 1000).toLocaleString();
  document.getElementById("modal-expires").textContent = `到期：${exp}`;
  document.getElementById("modal-overlay").classList.add("show");
}

document.getElementById("modal-close").addEventListener("click", closeModal);
document.getElementById("modal-overlay").addEventListener("click", (e) => {
  if (e.target === e.currentTarget) closeModal();
});
function closeModal() {
  document.getElementById("modal-overlay").classList.remove("show");
}

document.getElementById("modal-copy").addEventListener("click", () => {
  const code = document.getElementById("modal-code").textContent;
  navigator.clipboard.writeText(code).then(() => {
    document.getElementById("modal-copy").textContent = "已複製！";
    setTimeout(() => { document.getElementById("modal-copy").textContent = "複製碼"; }, 2000);
  });
});

document.getElementById("modal-download-qr").addEventListener("click", () => {
  const a = document.createElement("a");
  a.href     = document.getElementById("modal-qr").src;
  a.download = `upload-qr-${document.getElementById("modal-code").textContent}.png`;
  a.click();
});

// ── Helpers ────────────────────────────────────────────────────────────────
async function api(path, method = "GET", body) {
  const opts = { method, headers: {} };
  if (method !== "GET" && method !== "HEAD") {
    if (!csrfToken) throw new Error("CSRF token 尚未載入");
    opts.headers["X-CSRF-Token"] = csrfToken;
  }
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  if (res.status === 401) {
    window.location.assign("/admin/login");
    throw new Error("管理員登入已過期");
  }
  if (!res.ok) {
    const json = await res.json().catch(() => ({}));
    throw new Error(json.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

function fmtSize(bytes) {
  if (!bytes) return "0 B";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
}
