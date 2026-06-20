import unittest

from preprocess_pipeline.step1 import runtime


class Suite2pRuntimeCommandTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
