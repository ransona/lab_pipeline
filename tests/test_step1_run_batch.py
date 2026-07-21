from datetime import datetime
import unittest

from preprocess_pipeline.step1 import run_batch


class Step1RunBatchFilenameTests(unittest.TestCase):
    def test_binary_removal_choices_are_preserved_in_normalized_config(self):
        normalized = run_batch._normalize_config_entry(
            {
                "config": "settings.npy",
                "functional_chan": 1,
                "remove_ch1_bins": False,
                "remove_ch2_bins": True,
            }
        )

        self.assertFalse(normalized["remove_ch1_bins"])
        self.assertTrue(normalized["remove_ch2_bins"])

    def test_combined_s2p_filename_cannot_collide_with_first_experiment_job(self):
        now = datetime(2026, 6, 26, 21, 55, 55)
        combined = run_batch._combined_s2p_command_filename(
            now,
            "adamranson",
            "2026-06-01_05_ESRC033",
            False,
        )
        per_experiment = run_batch._command_filename(
            now,
            "adamranson",
            "2026-06-01_05_ESRC033",
            False,
        )

        self.assertEqual(
            combined,
            "2026_06_26_21_55_55_adamranson_combined_s2p_2026-06-01_05_ESRC033.pickle",
        )
        self.assertNotEqual(combined, per_experiment)
        self.assertIn("_combined_s2p_", combined)

    def test_combined_s2p_jump_queue_filename_still_has_distinct_label(self):
        now = datetime(2026, 6, 26, 21, 55, 55)
        self.assertEqual(
            run_batch._combined_s2p_command_filename(
                now,
                "adamranson",
                "2026-06-01_05_ESRC033",
                True,
            ),
            "00_00_00_00_00_00_adamranson_combined_s2p_2026-06-01_05_ESRC033.pickle",
        )

    def test_combined_per_experiment_dlc_filename_has_distinct_label(self):
        now = datetime(2026, 6, 26, 21, 55, 55)
        self.assertEqual(
            run_batch._combined_per_experiment_command_filename(
                now,
                "adamranson",
                "2026-06-01_05_ESRC033",
                False,
                True,
            ),
            "2026_06_26_21_55_55_adamranson_dlc_2026-06-01_05_ESRC033.pickle",
        )

    def test_combined_per_experiment_dlc_jump_queue_filename_has_distinct_label(self):
        now = datetime(2026, 6, 26, 21, 55, 55)
        self.assertEqual(
            run_batch._combined_per_experiment_command_filename(
                now,
                "adamranson",
                "2026-06-01_05_ESRC033",
                True,
                True,
            ),
            "00_00_00_00_00_00_adamranson_dlc_2026-06-01_05_ESRC033.pickle",
        )

    def test_combined_per_experiment_without_dlc_uses_standard_filename(self):
        now = datetime(2026, 6, 26, 21, 55, 55)
        self.assertEqual(
            run_batch._combined_per_experiment_command_filename(
                now,
                "adamranson",
                "2026-06-01_05_ESRC033",
                False,
                False,
            ),
            run_batch._command_filename(now, "adamranson", "2026-06-01_05_ESRC033", False),
        )


if __name__ == "__main__":
    unittest.main()
