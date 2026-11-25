import base64
import os
import unittest
from unittest.mock import patch


os.environ.setdefault("UPLOAD_DIR", "/tmp/pg72-upload-email-tests")
os.environ.setdefault("TEMP_DIR", "/tmp/pg72-upload-email-tests-temp")
os.environ.setdefault("RESEND_API_KEY", "re_test_only")
os.environ.setdefault("ADMIN_EMAIL", "upload-test@example.invalid")
os.environ.setdefault("BASE_URL", "https://upload.test")
os.environ.setdefault("OIDC_ISSUER", "https://sso.test")
os.environ.setdefault("OIDC_CLIENT_ID", "pg72-upload-test")
os.environ.setdefault("OIDC_CLIENT_SECRET", "pg72_cs_test_only")
os.environ.setdefault(
    "OIDC_BOOTSTRAP_ADMIN_SUB", "00000000-0000-4000-8000-000000000072"
)
os.environ.setdefault(
    "ADMIN_TOKEN_ENCRYPTION_KEY", base64.urlsafe_b64encode(b"u" * 32).decode()
)

from utils import email_helper


class EmailHelperTests(unittest.TestCase):
    def test_filename_cannot_inject_headers_or_html(self):
        filename = (
            'report\r\nBcc: hidden@example.invalid '
            '<img src=x onerror="alert(1)">.txt'
        )
        mime_type = 'text/plain"><script>alert(2)</script>'
        stored_filename = 'stored"><img src=x>.txt'

        with patch.object(email_helper.resend.Emails, "send") as send:
            email_helper.send_upload_notification(
                "ABCDEFGHJKLMNPQR",
                filename,
                1024,
                stored_filename,
                mime_type,
            )

        send.assert_called_once()
        params = send.call_args.args[0]
        self.assertNotIn("\r", params["subject"])
        self.assertNotIn("\n", params["subject"])
        self.assertIn("report Bcc:", params["subject"])
        self.assertNotIn("<img", params["html"])
        self.assertNotIn("<script>alert(2)</script>", params["html"])
        self.assertIn("&lt;img", params["html"])
        self.assertIn("&lt;script&gt;alert(2)&lt;/script&gt;", params["html"])
        self.assertIn("原始檔名: report Bcc:", params["text"])
        self.assertNotIn("\r", params["text"])
        self.assertNotIn("<div", params["text"])

    def test_dangerous_mime_warning_is_present_in_both_bodies(self):
        with patch.object(email_helper.resend.Emails, "send") as send:
            email_helper.send_upload_notification(
                "ABCDEFGHJKLMNPQR",
                "sample.exe",
                2048,
                "stored.exe",
                "application/x-msdownload",
            )

        params = send.call_args.args[0]
        self.assertIn("可能為可執行檔", params["html"])
        self.assertIn("可能為可執行檔", params["text"])


if __name__ == "__main__":
    unittest.main()
