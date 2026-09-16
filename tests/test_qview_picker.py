import unittest
from unittest import mock

from preprocess_pipeline.viewers.qview import (
    _parse_experiment_ids,
    _suite2p_gui_environment,
)


class PickerExperimentIdParsingTests(unittest.TestCase):
    def test_parses_spaces_commas_and_newlines(self):
        text = (
            "2026-08-01_01_TEST001, 2026-08-01_02_TEST001\n"
            "2026-08-01_03_TEST001   2026-08-01_04_TEST001"
        )
        self.assertEqual(
            _parse_experiment_ids(text),
            [
                "2026-08-01_01_TEST001",
                "2026-08-01_02_TEST001",
                "2026-08-01_03_TEST001",
                "2026-08-01_04_TEST001",
            ],
        )

    def test_removes_duplicate_ids_without_reordering(self):
        self.assertEqual(
            _parse_experiment_ids("exp1, exp2 exp1"),
            ["exp1", "exp2"],
        )


class Suite2pGuiEnvironmentTests(unittest.TestCase):
    @mock.patch("preprocess_pipeline.viewers.qview.subprocess.run")
    def test_prefers_suite2p_lab_when_probe_succeeds(self, run):
        run.return_value = mock.Mock(returncode=0, stderr="")

        self.assertEqual(_suite2p_gui_environment(), "suite2p_lab")
        self.assertIn("conda activate suite2p_lab", run.call_args.args[0][-1])
        self.assertIn("from suite2p import gui", run.call_args.args[0][-1])

    @mock.patch("preprocess_pipeline.viewers.qview.subprocess.run")
    def test_falls_back_to_existing_environment_when_probe_fails(self, run):
        run.side_effect = [
            mock.Mock(returncode=1, stderr="EnvironmentNameNotFound"),
            mock.Mock(returncode=0, stderr=""),
        ]

        self.assertEqual(_suite2p_gui_environment(), "suite2p_1.1.0")


if __name__ == "__main__":
    unittest.main()
