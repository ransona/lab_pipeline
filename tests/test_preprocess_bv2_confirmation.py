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


if __name__ == "__main__":
    unittest.main()
