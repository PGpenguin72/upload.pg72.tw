"use strict";

((root) => {
  const uploadCodePattern = /^[ABCDEFGHJKLMNPQRSTUVWXYZ23456789]{16}$/;
  const codeIdPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

  function escapeHtml(value = "") {
    return String(value ?? "").replace(/[&<>"']/g, (character) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    })[character]);
  }

  function isUploadCode(value) {
    return typeof value === "string" && uploadCodePattern.test(value);
  }

  function isCodeId(value) {
    return typeof value === "string" && codeIdPattern.test(value);
  }

  root.PG72AdminSecurity = Object.freeze({ escapeHtml, isUploadCode, isCodeId });
})(globalThis);
