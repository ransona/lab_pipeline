import unittest

from preprocess_pipeline.viewers.qview import _parse_experiment_ids


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


if __name__ == "__main__":
    unittest.main()
