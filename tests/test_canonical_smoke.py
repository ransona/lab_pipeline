from pathlib import Path
import importlib
import unittest


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


if __name__ == "__main__":
    unittest.main()
