from pathlib import Path
import importlib
import unittest

from preprocess_pipeline.shared import paths


REPO_ROOT = Path(__file__).resolve().parents[1]


class CanonicalSmokeTests(unittest.TestCase):
    def test_direct_entrypoints_exist(self):
        app_names = [
            "run_step1.py",
            "preprocess_step1.py",
            "run_step2.py",
            "preprocess_step2.py",
            "s2p_launcher.py",
            "dlc_launcher.py",
            "preprocess_pupil.py",
            "preprocess_s2p.py",
            "split_combined_s2p.py",
            "preprocess_habituate.py",
            "preprocess_cam.py",
            "preprocess_ephys.py",
            "preprocess_cut.py",
            "preprocess_bv.py",
            "preprocess_pupil_timestamp.py",
            "queue_listener.py",
        ]
        for app_name in app_names:
            self.assertTrue((REPO_ROOT / "apps" / app_name).exists(), app_name)

    def test_safe_canonical_modules_import(self):
        module_names = [
            "preprocess_pipeline.step1.run_batch",
            "preprocess_pipeline.step1.runtime",
            "preprocess_pipeline.step2.run_batch",
            "preprocess_pipeline.step2.runtime",
            "preprocess_pipeline.queue.listener",
            "preprocess_pipeline.suite2p.preprocess",
            "preprocess_pipeline.step1.split_combined_s2p",
        ]
        for module_name in module_names:
            importlib.import_module(module_name)

    def test_local_processed_path_includes_user(self):
        _, _, _, exp_dir_processed, _ = paths.find_paths(
            "adamranson",
            "2025-10-30_10_ESYB025",
            local_raw_repository_root="raw_root",
            local_processed_repository_root="processed_root",
        )
        self.assertTrue(
            exp_dir_processed.endswith(
                "processed_root/adamranson/ESYB025/2025-10-30_10_ESYB025"
            )
        )


if __name__ == "__main__":
    unittest.main()
