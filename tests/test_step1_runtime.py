import tempfile
import unittest
from pathlib import Path
from unittest import mock

from preprocess_pipeline.step1 import runtime


class Suite2pRuntimeCommandTests(unittest.TestCase):
    def test_requested_binary_removal_is_passed_to_launcher(self):
        command = runtime._suite2p_cmd_for_work_unit(
            user_id="submitter",
            exp_id="2026-01-01_01_TEST001",
            tif_path="/data/raw/test",
            output_path="/data/processed/test",
            config_names=[
                {
                    "config": "settings.npy",
                    "remove_ch1_bins": False,
                    "remove_ch2_bins": True,
                }
            ],
            queued_command={"config": {"suite2p_env": "suite2p_1.1.0"}},
            work_unit_id="root",
        )

        self.assertNotIn("--remove-ch1-bins", command)
        self.assertIn("--remove-ch2-bins", command)

    def test_requested_env_runs_as_listener_user(self):
        command = runtime._suite2p_cmd_for_work_unit(
            user_id="submitter",
            exp_id="2026-01-01_01_TEST001",
            tif_path="/data/raw/test",
            output_path="/data/processed/test",
            config_names=[{"config": "settings.npy"}],
            queued_command={"config": {"suite2p_env": "suite2p_1.1.0"}},
            work_unit_id="root",
        )

        self.assertEqual(
            command[:5],
            [
                "/opt/scripts/conda-run.sh",
                "suite2p_1.1.0",
                "python",
                "-u",
                str(runtime.APP_ROOT / "s2p_launcher.py"),
            ],
        )
        self.assertNotIn("sudo", command)

    def test_fit_pupil_runs_in_pipeline_env(self):
        with mock.patch.object(runtime, "_stream_subprocess_for_job") as stream:
            runtime._run_fit_pupil(
                job_id="job.pickle",
                user_id="submitter",
                exp_id="2026-01-01_01_TEST001",
                queue_path="/tmp/queue",
            )

        stream.assert_called_once()
        command = stream.call_args.args[0]
        self.assertEqual(
            command,
            [
                "/opt/scripts/conda-run.sh",
                "lab_pipeline",
                "python",
                str(runtime.APP_ROOT / "preprocess_pupil.py"),
                "submitter",
                "2026-01-01_01_TEST001",
            ],
        )
        self.assertNotIn("sci", command)


class Step1RuntimeLocalPathTests(unittest.TestCase):
    def test_direct_runtime_copies_selected_scanfield_from_local_nas_root(self):
        exp_id = "2026-07-14_02_ESYB999"
        animal_id = "ESYB999"
        roi_name = f"{exp_id}_selectedScanfield.roi"

        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            raw_root = root_path / "Local_Repository"
            processed_root = root_path / "Local_Repository_Processed"
            nas_root = root_path / "Remote_Repository"
            local_raw_exp = raw_root / animal_id / exp_id
            nas_exp = nas_root / animal_id / exp_id
            local_raw_exp.mkdir(parents=True)
            nas_exp.mkdir(parents=True)
            (nas_exp / roi_name).write_text("roi payload", encoding="utf-8")

            queued_command = {
                "config": {
                    "local_raw_repository_root": str(raw_root),
                    "local_processed_repository_root": str(processed_root),
                    "local_nas_repository_root": str(nas_root),
                    "runhabituate": False,
                }
            }

            runtime.run_preprocess_step1_universal(
                "local-test.pickle",
                "scanimage",
                exp_id,
                False,
                False,
                False,
                queued_command=queued_command,
                queue_path=str(root_path / "_queue"),
            )

            copied = processed_root / animal_id / exp_id / roi_name
            self.assertTrue(copied.is_file())
            self.assertEqual(copied.read_text(encoding="utf-8"), "roi payload")

    def test_direct_runtime_copies_selected_scanfield_for_each_scanpath(self):
        exp_id = "2026-07-23_37_ESYB038"
        animal_id = "ESYB038"
        roi_name = f"{exp_id}_selectedScanfield.roi"

        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            raw_root = root_path / "Local_Repository"
            processed_root = root_path / "Local_Repository_Processed"
            raw_exp = raw_root / animal_id / exp_id
            raw_scanpath = raw_exp / "P1"
            raw_roi = raw_scanpath / "R001"
            raw_roi.mkdir(parents=True)
            (raw_scanpath / roi_name).write_text("scanpath roi payload", encoding="utf-8")

            queued_command = {
                "config": {
                    "local_raw_repository_root": str(raw_root),
                    "local_processed_repository_root": str(processed_root),
                    "runhabituate": False,
                }
            }

            runtime.run_preprocess_step1_universal(
                "local-test.pickle",
                "scanimage",
                exp_id,
                False,
                False,
                False,
                queued_command=queued_command,
                queue_path=str(root_path / "_queue"),
            )

            copied = processed_root / animal_id / exp_id / "P1" / roi_name
            self.assertTrue(copied.is_file())
            self.assertEqual(
                copied.read_text(encoding="utf-8"),
                "scanpath roi payload",
            )


if __name__ == "__main__":
    unittest.main()
