from unittest import TestCase
from unittest.mock import patch

from preprocess_pipeline.queue import listener


class QueueIntegrityTests(TestCase):
    def test_dlc_only_job_checks_nas_and_camera_inputs(self):
        command = {
            "userID": "adamranson",
            "config": {"runs2p": False, "rundlc": True},
        }
        with (
            patch.object(listener.paths, "find_paths", return_value=(None, None, None, "/processed", "/raw")),
            patch.object(listener.file_check, "verify_file_data", side_effect=[(True, "Hash correct"), (False, "Missing")]) as verify,
            patch.object(listener.matrix_notify, "main"),
        ):
            ready = listener.verify_job_input_integrity(
                command, "2026-09-01_02_ESRC036"
            )

        self.assertFalse(ready)
        self.assertEqual([call.args[0] for call in verify.call_args_list], ["nas", "cams"])

    def test_non_imaging_job_does_not_require_scanimage_manifest(self):
        command = {
            "userID": "adamranson",
            "config": {"runs2p": False, "rundlc": False},
        }
        with (
            patch.object(listener.paths, "find_paths", return_value=(None, None, None, "/processed", "/raw")),
            patch.object(listener.file_check, "verify_file_data", return_value=(True, "Hash correct")) as verify,
            patch.object(listener.matrix_notify, "main"),
        ):
            ready = listener.verify_job_input_integrity(
                command, "2026-09-01_02_ESRC036"
            )

        self.assertTrue(ready)
        self.assertEqual([call.args[0] for call in verify.call_args_list], ["nas"])
