from pathlib import Path
import tempfile
import unittest

from preprocess_pipeline.step1.split_combined_s2p import clear_existing_suite2p_destinations


class ClearExistingSuite2pDestinationsTests(unittest.TestCase):
    def test_removes_normal_and_meso_outputs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            normal_root = temp_path / "normal"
            meso_root = temp_path / "meso" / "P0" / "R0"
            for root in (normal_root, meso_root):
                plane_dir = root / "suite2p" / "plane0"
                plane_dir.mkdir(parents=True)
                (plane_dir / "ops.npy").write_bytes(b"stale")
                (root / "unrelated.txt").write_text("keep", encoding="ascii")

            clear_existing_suite2p_destinations([str(normal_root), str(meso_root)])

            for root in (normal_root, meso_root):
                self.assertFalse((root / "suite2p").exists())
                self.assertEqual(
                    (root / "unrelated.txt").read_text(encoding="ascii"),
                    "keep",
                )

    def test_handles_ch2_and_duplicates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            ch2_root = Path(temp_dir) / "P0" / "R0" / "ch2"
            (ch2_root / "suite2p" / "plane1").mkdir(parents=True)

            clear_existing_suite2p_destinations([Path(ch2_root), str(ch2_root)])

            self.assertFalse((ch2_root / "suite2p").exists())


if __name__ == "__main__":
    unittest.main()
