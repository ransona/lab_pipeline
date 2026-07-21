from pathlib import Path
import pickle
import tempfile
import unittest

from preprocess_pipeline.step1.split_combined_s2p import (
    clear_existing_suite2p_destinations,
    requested_binary_removals,
    split_output_channel,
)


class ClearExistingSuite2pDestinationsTests(unittest.TestCase):
    def test_reads_binary_removal_choices_for_requested_work_unit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "pipeline_config.pickle"
            with config_path.open("wb") as handle:
                pickle.dump(
                    {
                        "config": {
                            "suite2p_plan": [
                                {
                                    "work_unit": "P0/R0",
                                    "suite2p_configs": [
                                        {
                                            "config": "settings.npy",
                                            "remove_ch1_bins": False,
                                            "remove_ch2_bins": True,
                                        }
                                    ],
                                }
                            ]
                        }
                    },
                    handle,
                )

            self.assertEqual(
                requested_binary_removals(temp_dir, "P0/R0"),
                (False, True),
            )
            self.assertEqual(
                requested_binary_removals(temp_dir, "P1/R0"),
                (False, False),
            )
            self.assertEqual(split_output_channel(temp_dir, "P0/R0", False), 1)

    def test_split_root_can_represent_channel_two_only(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "pipeline_config.pickle"
            with config_path.open("wb") as handle:
                pickle.dump(
                    {
                        "config": {
                            "suite2p_plan": [
                                {
                                    "work_unit": "root",
                                    "suite2p_configs": [
                                        {"config": "settings.npy", "functional_chan": 2}
                                    ],
                                }
                            ]
                        }
                    },
                    handle,
                )

            self.assertEqual(split_output_channel(temp_dir, "root", False), 2)

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
