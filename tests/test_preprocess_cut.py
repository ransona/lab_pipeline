import os
import pickle
import tempfile
import unittest
import warnings
from unittest import mock

import numpy as np

from preprocess_pipeline.behavior import preprocess_cut


class PreprocessCutTests(unittest.TestCase):
    def assert_nested_array_dict_equal(self, actual, expected):
        self.assertEqual(set(actual), set(expected))
        for key in expected:
            if isinstance(expected[key], list):
                self.assertEqual(len(actual[key]), len(expected[key]))
                for actual_value, expected_value in zip(actual[key], expected[key]):
                    np.testing.assert_array_equal(actual_value, expected_value)
            else:
                np.testing.assert_array_equal(actual[key], expected[key])

    def test_f_cut_preserves_nan_padding_without_integer_cast_warning(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            exp_id = "2026-06-01_05_ESRC033"
            processed_dir = os.path.join(tmpdir, exp_id)
            raw_dir = os.path.join(tmpdir, "raw", exp_id)
            recordings_dir = os.path.join(processed_dir, "recordings")
            os.makedirs(recordings_dir)
            os.makedirs(raw_dir)

            with open(os.path.join(processed_dir, f"{exp_id}_all_trials.csv"), "w", encoding="utf-8") as handle:
                handle.write("time,duration\n")
                handle.write("0.2,0.2\n")
                handle.write("1.0,0.4\n")

            ca_data = {
                "t": np.arange(30, dtype=np.float32) / 10.0,
                "dF": np.arange(60, dtype=np.float32).reshape(2, 30),
                "F": (np.arange(60, dtype=np.float32).reshape(2, 30) + 100.0),
                "Spikes": np.arange(60, dtype=np.float32).reshape(2, 30),
                "Depths": np.array([[0], [1]], dtype=np.int64),
                "OriginalSuite2pCellIDs": np.array([[11], [22]], dtype=np.int64),
                "AllRoiPix": {0: [np.array([1, 2, 3])], 1: [np.array([4, 5, 6])]},
                "AllRoiMaps": {0: np.array([[1, 0], [0, 0]]), 1: np.array([[0, 0], [0, 2]])},
                "AllFOV": {0: np.ones((2, 2), dtype=np.float32), 1: np.ones((2, 2), dtype=np.float32) * 2},
                "Scanpaths": np.array([[1], [2]], dtype=np.int64),
                "SIRois": np.array([[0], [1]], dtype=np.int64),
            }
            with open(os.path.join(recordings_dir, "s2p_001.pickle"), "wb") as handle:
                pickle.dump(ca_data, handle)

            find_paths_result = ("ESRC033", tmpdir, tmpdir, processed_dir, raw_dir)
            with (
                mock.patch.object(preprocess_cut.paths, "find_paths", return_value=find_paths_result),
                mock.patch.object(preprocess_cut, "_is_local_run", return_value=True),
                warnings.catch_warnings(),
            ):
                warnings.simplefilter("error", RuntimeWarning)
                preprocess_cut.run_preprocess_cut("ESRC033", exp_id, pre_time=0.1, post_time=0.1)

            with open(os.path.join(processed_dir, "cut", "s2p_001_F_cut.pickle"), "rb") as handle:
                f_cut = pickle.load(handle)
            with open(os.path.join(processed_dir, "cut", "s2p_001_dF_cut.pickle"), "rb") as handle:
                df_cut = pickle.load(handle)
            with open(os.path.join(processed_dir, "cut", "s2p_001_Spikes_cut.pickle"), "rb") as handle:
                spikes_cut = pickle.load(handle)

        self.assertEqual(f_cut["F"].dtype, np.float32)
        self.assertTrue(np.isnan(f_cut["F"][0, 0, -1]))
        for cut_output in (f_cut, df_cut, spikes_cut):
            np.testing.assert_array_equal(cut_output["Depths"], ca_data["Depths"])
            np.testing.assert_array_equal(
                cut_output["OriginalSuite2pCellIDs"],
                ca_data["OriginalSuite2pCellIDs"],
            )
            np.testing.assert_array_equal(cut_output["Scanpaths"], ca_data["Scanpaths"])
            np.testing.assert_array_equal(cut_output["SIRois"], ca_data["SIRois"])
            self.assert_nested_array_dict_equal(cut_output["AllRoiPix"], ca_data["AllRoiPix"])
            self.assert_nested_array_dict_equal(cut_output["AllRoiMaps"], ca_data["AllRoiMaps"])
            self.assert_nested_array_dict_equal(cut_output["AllFOV"], ca_data["AllFOV"])


if __name__ == "__main__":
    unittest.main()
