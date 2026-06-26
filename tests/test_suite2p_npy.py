import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from preprocess_pipeline.shared import suite2p_npy


class Suite2pNpyCompatTests(unittest.TestCase):
    def test_classifies_flat_legacy_ops(self):
        ops = {"Ly": 512, "Lx": 512, "nframes": 100, "meanImg": np.zeros((2, 2))}
        self.assertEqual(suite2p_npy.classify_suite2p_npy("ops.npy", ops), "legacy")

    def test_classifies_nested_suite2p_1x_settings(self):
        settings = {section: {} for section in suite2p_npy.SUITE2P_1X_SETTINGS_SECTIONS}
        settings.update({"fs": 30, "tau": 1.0, "diameter": 12})
        self.assertEqual(suite2p_npy.classify_suite2p_npy("settings.npy", settings), "native1x")

    def test_legacy_save_routes_to_numpy1_when_current_numpy_is_2(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "ops.npy"
            ops = {"Ly": 512, "Lx": 512, "nframes": 100}
            with (
                mock.patch.object(suite2p_npy, "current_numpy_major", return_value=2),
                mock.patch.object(suite2p_npy, "current_conda_env", return_value="lab_pipeline"),
                mock.patch.object(suite2p_npy, "save_object_npy_with_numpy1") as save_with_numpy1,
            ):
                suite2p_npy.save_object_npy(path, ops)
        save_with_numpy1.assert_called_once_with(path, ops)

    def test_native1x_save_does_not_route_to_numpy1(self):
        settings = {section: {} for section in suite2p_npy.SUITE2P_1X_SETTINGS_SECTIONS}
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "settings.npy"
            with (
                mock.patch.object(suite2p_npy, "current_numpy_major", return_value=2),
                mock.patch.object(suite2p_npy, "current_conda_env", return_value="lab_pipeline"),
                mock.patch.object(suite2p_npy, "save_object_npy_with_numpy1") as save_with_numpy1,
            ):
                suite2p_npy.save_object_npy(path, settings)
                loaded = suite2p_npy.load_object_dict(path)
        save_with_numpy1.assert_not_called()
        self.assertEqual(set(suite2p_npy.SUITE2P_1X_SETTINGS_SECTIONS), set(loaded))

    def test_numpy1_worker_preserves_datetime_values(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "ops.npy"
            value = {
                "Ly": 512,
                "Lx": 512,
                "date_proc": dt.datetime(2026, 6, 26, 22, 30, 45),
                "nested": {
                    "date": dt.date(2026, 6, 26),
                    "time": dt.time(22, 30, 45),
                },
            }

            suite2p_npy.save_object_npy_with_numpy1(path, value)
            loaded = suite2p_npy.load_object_dict(path)

        self.assertEqual(loaded["date_proc"], value["date_proc"])
        self.assertEqual(loaded["nested"]["date"], value["nested"]["date"])
        self.assertEqual(loaded["nested"]["time"], value["nested"]["time"])


if __name__ == "__main__":
    unittest.main()
