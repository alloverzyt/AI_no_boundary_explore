"""Offline image-only vision regression checks."""
import base64
import io
import sys
import unittest
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    Image = None

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))
import vision


@unittest.skipIf(Image is None, "Pillow is optional")
class VisionTests(unittest.TestCase):
    @staticmethod
    def obs(color):
        image = Image.new("RGB", (64, 40), color)
        buf = io.BytesIO()
        image.save(buf, format="JPEG")
        return {"image_jpeg_base64": base64.b64encode(buf.getvalue()).decode()}

    def test_uniform_center_water_has_center_offset(self):
        self.assertAlmostEqual(vision.water_offset(self.obs((20, 60, 140))), 0.0, delta=0.12)


if __name__ == "__main__":
    unittest.main()
