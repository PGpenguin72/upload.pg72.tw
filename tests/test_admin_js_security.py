import json
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AdminJavaScriptSecurityTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js is required for JS unit tests")
    def test_escape_and_identifier_allowlists(self):
        script = r"""
require('./static/js/admin_security.js');
const security = globalThis.PG72AdminSecurity;
process.stdout.write(JSON.stringify({
  escaped: security.escapeHtml('<img src=x onerror="alert(1)">&\''),
  validCode: security.isUploadCode('ABCDEFGHJKLMNPQR'),
  invalidCode: security.isUploadCode('<script>alert(1)</script>'),
  validId: security.isCodeId('123e4567-e89b-42d3-a456-426614174000'),
  invalidId: security.isCodeId("x' onclick='alert(1)"),
}));
"""
        result = subprocess.run(
            ["node", "-e", script],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        output = json.loads(result.stdout)
        self.assertEqual(
            output["escaped"],
            "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;&amp;&#39;",
        )
        self.assertTrue(output["validCode"])
        self.assertFalse(output["invalidCode"])
        self.assertTrue(output["validId"])
        self.assertFalse(output["invalidId"])

    def test_admin_renderer_does_not_use_dynamic_inline_handlers(self):
        source = (ROOT / "static/js/admin.js").read_text(encoding="utf-8")
        self.assertNotIn("onclick=", source)
        self.assertIn('escHtml(u.mime_type || "—")', source)
        self.assertIn("isCodeId(c.id) && isUploadCode(c.code)", source)

    def test_logout_redirect_stays_on_upload_origin(self):
        source = (ROOT / "static/js/admin.js").read_text(encoding="utf-8")
        self.assertIn('await api("/admin/logout", "POST");', source)
        self.assertIn('window.location.assign("/admin/logged-out");', source)
        self.assertNotIn("const { logout_url }", source)


if __name__ == "__main__":
    unittest.main()
