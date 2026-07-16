from html import escape

import resend
from config import settings

resend.api_key = settings.resend_api_key

DANGEROUS_MIMES = {
    "application/x-sh", "text/x-sh", "application/x-executable",
    "application/x-mach-binary", "application/x-msdownload",
    "application/x-dosexec", "text/x-php", "application/x-php",
}


def _single_line(value: str, *, fallback: str = "-") -> str:
    cleaned = "".join(
        " " if character.isspace() or ord(character) < 32 or ord(character) == 127
        else character
        for character in str(value)
    )
    return " ".join(cleaned.split()) or fallback


def send_upload_notification(
    code: str,
    original_filename: str,
    file_size: int,
    stored_filename: str,
    mime_type: str,
) -> None:
    size_mb = file_size / 1024 / 1024
    display_code = _single_line(code)
    display_filename = _single_line(original_filename, fallback="unnamed-file")
    display_stored_filename = _single_line(stored_filename)
    display_mime_type = _single_line(mime_type)
    safe_code = escape(display_code)
    safe_filename = escape(display_filename)
    safe_stored_filename = escape(display_stored_filename)
    safe_mime_type = escape(display_mime_type)

    warning_html = ""
    warning_text = ""
    if mime_type in DANGEROUS_MIMES:
        warning_html = (
            '<p style="color:#dc2626;font-weight:bold;">'
            f"⚠️ 注意：此檔案類型可能為可執行檔 ({safe_mime_type})</p>"
        )
        warning_text = f"注意：此檔案類型可能為可執行檔 ({display_mime_type})\n\n"

    plain_text = (
        "新檔案上傳通知\n\n"
        f"{warning_text}"
        f"上傳碼: {display_code}\n"
        f"原始檔名: {display_filename}\n"
        f"檔案大小: {file_size:,} bytes ({size_mb:.2f} MB)\n"
        f"MIME 類型: {display_mime_type}\n"
        f"儲存名稱: {display_stored_filename}\n"
    )

    params: resend.Emails.SendParams = {
        "from": settings.from_email,
        "to": [settings.admin_email],
        "subject": f"[Upload] {display_filename}",
        "text": plain_text,
        "html": f"""
<div style="font-family:sans-serif;max-width:600px;margin:0 auto;padding:24px">
  <h2 style="color:#111827;border-bottom:1px solid #e5e7eb;padding-bottom:12px">新檔案上傳通知</h2>
  {warning_html}
  <table style="width:100%;border-collapse:collapse;margin-top:16px">
    <tr style="background:#f9fafb">
      <td style="padding:10px 16px;font-weight:600;color:#374151;width:120px">上傳碼</td>
      <td style="padding:10px 16px;font-family:monospace;letter-spacing:0.1em;color:#2563eb">{safe_code}</td>
    </tr>
    <tr>
      <td style="padding:10px 16px;font-weight:600;color:#374151">原始檔名</td>
      <td style="padding:10px 16px;color:#111827">{safe_filename}</td>
    </tr>
    <tr style="background:#f9fafb">
      <td style="padding:10px 16px;font-weight:600;color:#374151">檔案大小</td>
      <td style="padding:10px 16px;color:#111827">{file_size:,} bytes ({size_mb:.2f} MB)</td>
    </tr>
    <tr>
      <td style="padding:10px 16px;font-weight:600;color:#374151">MIME 類型</td>
      <td style="padding:10px 16px;color:#111827">{safe_mime_type}</td>
    </tr>
    <tr style="background:#f9fafb">
      <td style="padding:10px 16px;font-weight:600;color:#374151">儲存名稱</td>
      <td style="padding:10px 16px;font-family:monospace;font-size:12px;color:#6b7280">{safe_stored_filename}</td>
    </tr>
  </table>
</div>
""",
    }
    resend.Emails.send(params)
