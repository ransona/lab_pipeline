import tempfile
import unittest
from pathlib import Path

import numpy as np

from preprocess_pipeline.shared import suite2p_npy
from preprocess_pipeline.suite2p import launcher


class Channel2ViewingMetadataTests(unittest.TestCase):
    def test_disabled_detection_hides_then_restores_mean_only_in_final_ops(self):
        mean_chan2 = np.arange(16, dtype=np.float32).reshape(4, 4)
        corrected = mean_chan2 + 1

        with tempfile.TemporaryDirectory() as temp_dir:
            plane_dir = Path(temp_dir)
            reg_outputs_path = plane_dir / "reg_outputs.npy"
            suite2p_npy.save_object_npy(
                reg_outputs_path,
                {
                    "badframes": np.zeros(3, dtype=bool),
                    "meanImg_chan2": mean_chan2,
                    "meanImg_chan2_corrected": corrected,
                },
            )
            registration_ops = {
                "badframes": np.zeros(3, dtype=bool),
                "reg_file_chan2": str(plane_dir / "data_chan2.bin"),
                "meanImg_chan2": mean_chan2,
                "meanImg_chan2_corrected": corrected,
            }
            extraction_ops = {
                **registration_ops,
                "nchannels": 2,
                "detection": {"cellpose_chan2": True},
            }

            launcher.apply_chan2_detection_mode(
                extraction_ops,
                "off",
                str(plane_dir),
                paired_channel_available=True,
            )

            self.assertEqual(extraction_ops["nchannels"], 1)
            self.assertFalse(extraction_ops["detection"]["cellpose_chan2"])
            self.assertNotIn("meanImg_chan2", extraction_ops)
            self.assertNotIn("meanImg_chan2_corrected", extraction_ops)
            self.assertNotIn("reg_file_chan2", extraction_ops)
            detection_reg_outputs = suite2p_npy.load_object_dict(reg_outputs_path)
            self.assertNotIn("meanImg_chan2", detection_reg_outputs)
            self.assertNotIn("meanImg_chan2_corrected", detection_reg_outputs)

            launcher.restore_chan2_viewing_metadata(
                extraction_ops,
                registration_ops,
                "off",
                paired_channel_available=True,
            )

            np.testing.assert_array_equal(extraction_ops["meanImg_chan2"], mean_chan2)
            np.testing.assert_array_equal(
                extraction_ops["meanImg_chan2_corrected"], corrected
            )
            self.assertNotIn("reg_file_chan2", extraction_ops)
            self.assertEqual(extraction_ops["nchannels"], 1)

            launcher.save_registration_outputs_for_plane(str(plane_dir), extraction_ops)
            final_reg_outputs = suite2p_npy.load_object_dict(reg_outputs_path)
            self.assertNotIn("meanImg_chan2", final_reg_outputs)
            self.assertNotIn("meanImg_chan2_corrected", final_reg_outputs)

    def test_viewing_metadata_is_not_restored_when_chan2_detection_is_enabled(self):
        ops = {}
        launcher.restore_chan2_viewing_metadata(
            ops,
            {"meanImg_chan2": np.ones((2, 2), dtype=np.float32)},
            "intensity",
            paired_channel_available=True,
        )
        self.assertNotIn("meanImg_chan2", ops)


if __name__ == "__main__":
    unittest.main()
