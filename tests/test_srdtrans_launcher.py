import tempfile
import unittest
from pathlib import Path

from preprocess_pipeline.srdtrans import launcher


class SRDTransLauncherConfigTests(unittest.TestCase):
    def test_model_patch_shape_is_loaded_when_not_supplied(self):
        with tempfile.TemporaryDirectory() as root:
            model_root = Path(root)
            model_dir = model_root / "test_model"
            model_dir.mkdir()
            (model_dir / "para.yaml").write_text(
                "patch_x: 128\npatch_y: 128\npatch_t: 128\n",
                encoding="utf-8",
            )

            config = launcher._normalize_config(
                {"model_root": str(model_root), "model": "test_model"}
            )

            self.assertEqual(config["patch_x"], 128)
            self.assertEqual(config["patch_t"], 128)

    def test_model_patch_shape_overrides_legacy_step1_values(self):
        with tempfile.TemporaryDirectory() as root:
            model_root = Path(root)
            model_dir = model_root / "test_model"
            model_dir.mkdir()
            (model_dir / "para.yaml").write_text(
                "patch_x: 128\npatch_y: 128\npatch_t: 128\n",
                encoding="utf-8",
            )

            config = launcher._normalize_config(
                {
                    "model_root": str(model_root),
                    "model": "test_model",
                    "patch_x": 120,
                    "patch_t": 120,
                }
            )

            self.assertEqual(config["patch_x"], 128)
            self.assertEqual(config["patch_t"], 128)


if __name__ == "__main__":
    unittest.main()
