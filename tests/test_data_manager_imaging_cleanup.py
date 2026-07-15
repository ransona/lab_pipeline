import tempfile
import unittest
from pathlib import Path

from preprocess_pipeline.viewers.external.data_manager.data_manager.database import DataStore
from preprocess_pipeline.viewers.external.data_manager.data_manager.imaging_cleanup import discover_imaging_targets


class ImagingCleanupDiscoveryTests(unittest.TestCase):
    def test_raw_discovers_tif_variants_recursively(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            experiment = Path(temp_dir)
            nested = experiment / "nested"
            nested.mkdir()
            (experiment / "one.tif").write_bytes(b"1")
            (nested / "two.TIFF").write_bytes(b"2")
            (nested / "keep.txt").write_bytes(b"3")

            targets = discover_imaging_targets("raw", experiment)

            self.assertEqual(
                {path.name for path, target_type in targets if target_type == "file"},
                {"one.tif", "two.TIFF"},
            )

    def test_processed_deduplicates_selected_containers(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            experiment = Path(temp_dir)
            (experiment / "P0" / "R001" / "suite2p").mkdir(parents=True)
            (experiment / "other" / "suite2p_combined").mkdir(parents=True)
            (experiment / "recordings").mkdir()
            (experiment / "cut").mkdir()
            (experiment / "recordings" / "s2p_001.pickle").write_bytes(b"1")
            (experiment / "cut" / "s2p_001_dF_cut.pickle").write_bytes(b"2")
            (experiment / "cut" / "wheel.pickle").write_bytes(b"3")

            targets = discover_imaging_targets("processed", experiment)
            relative = {(path.relative_to(experiment), kind) for path, kind in targets}

            self.assertIn((Path("P0"), "directory"), relative)
            self.assertNotIn((Path("P0/R001/suite2p"), "directory"), relative)
            self.assertIn((Path("other/suite2p_combined"), "directory"), relative)
            self.assertIn((Path("recordings/s2p_001.pickle"), "file"), relative)
            self.assertIn((Path("cut/s2p_001_dF_cut.pickle"), "file"), relative)
            self.assertNotIn((Path("cut/wheel.pickle"), "file"), relative)


class ImagingCleanupStoreTests(unittest.TestCase):
    def test_replace_and_clear_grouped_targets(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = DataStore(Path(temp_dir) / "manager.db")
            first = Path(temp_dir) / "first.tif"
            second = Path(temp_dir) / "second.tif"
            store.replace_imaging_deletions(
                "raw", None, "ANIMAL", "EXP", "tester", [(first, "file")]
            )
            store.replace_imaging_deletions(
                "raw", None, "ANIMAL", "EXP", "tester", [(second, "file")]
            )

            self.assertEqual(set(store.load_imaging_deletions()), {str(second)})
            self.assertIn(("raw", "", "ANIMAL", "EXP"), store.load_imaging_flags())

            store.clear_imaging_deletions_for_exp("raw", None, "ANIMAL", "EXP")
            self.assertFalse(store.load_imaging_deletions())


if __name__ == "__main__":
    unittest.main()
