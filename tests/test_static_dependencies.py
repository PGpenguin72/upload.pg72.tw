import hashlib
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
JSQR_SHA256 = (
    "bc40c8a15196236b2314db0856f72ca0b49980cd5413b8c852a7349f5fee0859"
)


class StaticDependencyTests(unittest.TestCase):
    def test_runtime_scripts_and_styles_are_local(self):
        index = (ROOT / "static/index.html").read_text(encoding="utf-8")
        admin = (ROOT / "static/admin.html").read_text(encoding="utf-8")
        styles = (ROOT / "static/css/style.css").read_text(encoding="utf-8")

        script_sources = re.findall(r'<script[^>]+src="([^"]+)"', index)
        self.assertEqual(
            script_sources,
            ["/vendor/jsqr/jsQR-1.4.0.js", "/js/upload.js"],
        )
        for source in (index, admin, styles):
            self.assertNotIn("cdn.jsdelivr.net", source)
            self.assertNotIn("fonts.googleapis.com", source)
            self.assertNotIn("fonts.gstatic.com", source)

    def test_vendored_jsqr_matches_audited_npm_bundle(self):
        bundle = ROOT / "static/vendor/jsqr/jsQR-1.4.0.js"
        license_file = ROOT / "static/vendor/jsqr/LICENSE"
        notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")

        self.assertEqual(hashlib.sha256(bundle.read_bytes()).hexdigest(), JSQR_SHA256)
        self.assertIn("Apache License", license_file.read_text(encoding="utf-8"))
        self.assertIn("jsQR 1.4.0", notices)
        self.assertIn(JSQR_SHA256, notices)


if __name__ == "__main__":
    unittest.main()
