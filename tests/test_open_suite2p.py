import builtins
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from apps.open_suite2p import _send_to_running_suite2p


class OpenSuite2pTests(unittest.TestCase):
    def test_missing_qtpy_starts_new_gui_instead_of_failing(self):
        original_import = builtins.__import__

        def import_without_qtpy(name, *args, **kwargs):
            if name == "qtpy":
                raise ImportError("No module named qtpy")
            return original_import(name, *args, **kwargs)

        with tempfile.TemporaryDirectory() as temp_dir:
            stat_path = Path(temp_dir) / "stat.npy"
            with mock.patch("builtins.__import__", side_effect=import_without_qtpy):
                self.assertFalse(_send_to_running_suite2p(stat_path))


if __name__ == "__main__":
    unittest.main()
