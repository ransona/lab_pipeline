import unittest
from unittest import mock
import sys

sys.modules.setdefault("harp", mock.Mock())
from preprocess_pipeline.behavior import preprocess_bv2


class ConfirmationTests(unittest.TestCase):
    def test_uses_gui_confirmation_callback_when_provided(self):
        callback = mock.Mock(return_value=True)

        accepted = preprocess_bv2._confirm_continue("Continue?", callback)

        self.assertTrue(accepted)
        callback.assert_called_once_with("Continue?")

    @mock.patch("builtins.input", return_value="n")
    def test_command_line_runs_still_use_stdin(self, input_mock):
        self.assertFalse(preprocess_bv2._confirm_continue("Continue?"))
        input_mock.assert_called_once()

    def test_detects_timeline_pd_only_count_mismatch(self):
        self.assertTrue(
            preprocess_bv2._is_timeline_pd_only_count_mismatch(
                [0, 1],
                [0, 1, 2],
                [0, 1, 2],
                [0, 1, 2],
            )
        )

    def test_does_not_treat_harp_mismatch_as_timeline_pd_only(self):
        self.assertFalse(
            preprocess_bv2._is_timeline_pd_only_count_mismatch(
                [0, 1, 2],
                [0, 1],
                [0, 1, 2],
                [0, 1, 2],
            )
        )

    def test_does_not_treat_multiple_mismatches_as_timeline_pd_only(self):
        self.assertFalse(
            preprocess_bv2._is_timeline_pd_only_count_mismatch(
                [0, 1],
                [0, 1, 2],
                [0, 1],
                [0, 1, 2],
            )
        )


if __name__ == "__main__":
    unittest.main()
