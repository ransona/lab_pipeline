import json
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

    def test_binary_metadata_json_avoids_staging_ops_npy(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            source_bin = root_path / "plane0" / "data.bin"
            source_bin.parent.mkdir()
            source_bin.write_bytes(b"\x00\x01")
            input_root = root_path / "scratch" / "input"
            input_root.mkdir(parents=True)
            missing_ops = source_bin.parent / "ops.npy"

            staged_bin = launcher._stage_binary_input(
                source_bin,
                input_root,
                missing_ops,
                {"Ly": 512, "Lx": 512, "dtype": "int16"},
            )

            self.assertTrue(staged_bin.is_file())
            self.assertFalse((input_root / "ops.npy").exists())
            with (input_root / "data.json").open(encoding="utf-8") as handle:
                metadata = json.load(handle)
            self.assertEqual(
                metadata,
                {"Ly": 512, "Lx": 512, "dtype": "int16"},
            )

    def test_ops_npy_remains_fallback_without_binary_metadata(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            source_bin = root_path / "plane0" / "data.bin"
            source_bin.parent.mkdir()
            source_bin.write_bytes(b"\x00\x01")
            ops_path = source_bin.parent / "ops.npy"
            ops_path.write_bytes(b"legacy ops")
            input_root = root_path / "scratch" / "input"
            input_root.mkdir(parents=True)

            launcher._stage_binary_input(
                source_bin,
                input_root,
                ops_path,
                None,
            )

            self.assertEqual(
                (input_root / "ops.npy").read_bytes(),
                b"legacy ops",
            )


if __name__ == "__main__":
    unittest.main()
