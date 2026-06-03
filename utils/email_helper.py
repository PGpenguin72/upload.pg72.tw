import resend
from config import settings

resend.api_key = settings.resend_api_key

DANGEROUS_MIMES = {
    "application/x-sh", "text/x-sh", "application/x-executable",
    "application/x-mach-binary", "application/x-msdownload",
    "application/x-dosexec", "text/x-php", "application/x-php",
}


def send_upload_notification(
    code: str,
    original_filename: str,
    file_size: int,
    stored_filename: str,
    mime_type: str,
) -> None:
    size_mb = file_size / 1024 / 1024
    warning = ""
    if mime_type in DANGEROUS_MIMES:
        warning = f'<p style="color:#dc2626;font-weight:bold;">⚠️ 注意：此檔案類型可能為可執行檔 ({mime_type})</p>'

    params: resend.Emails.SendParams = {
        "from": settings.from_email,
        "to": [settings.admin_email],
        "subject": f"[Upload] {original_filename}",
        "html": f"""
<div style="font-family:sans-serif;max-width:600px;margin:0 auto;padding:24px">
  <h2 style="color:#111827;border-bottom:1px solid #e5e7eb;padding-bottom:12px">新檔案上傳通知</h2>
  {warning}
  <table style="width:100%;border-collapse:collapse;margin-top:16px">
    <tr style="background:#f9fafb">
      <td style="padding:10px 16px;font-weight:600;color:#374151;width:120px">上傳碼</td>
      <td style="padding:10px 16px;font-family:monospace;letter-spacing:0.1em;color:#2563eb">{code}</td>
    </tr>
    <tr>
      <td style="padding:10px 16px;font-weight:600;color:#374151">原始檔名</td>
      <td style="padding:10px 16px;color:#111827">{original_filename}</td>
    </tr>
    <tr style="background:#f9fafb">
      <td style="padding:10px 16px;font-weight:600;color:#374151">檔案大小</td>
      <td style="padding:10px 16px;color:#111827">{file_size:,} bytes ({size_mb:.2f} MB)</td>
    </tr>
    <tr>
      <td style="padding:10px 16px;font-weight:600;color:#374151">MIME 類型</td>
      <td style="padding:10px 16px;color:#111827">{mime_type}</td>
    </tr>
    <tr style="background:#f9fafb">
      <td style="padding:10px 16px;font-weight:600;color:#374151">儲存名稱</td>
      <td style="padding:10px 16px;font-family:monospace;font-size:12px;color:#6b7280">{stored_filename}</td>
    </tr>
  </table>
</div>
""",
    }
    resend.Emails.send(params)
