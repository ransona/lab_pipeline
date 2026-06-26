import logging
import unittest

from preprocess_pipeline.suite2p.backend import Suite2pProgressNoiseFilter


class Suite2pProgressNoiseFilterTests(unittest.TestCase):
    def setUp(self):
        self.filter = Suite2pProgressNoiseFilter()

    def _keeps(self, message):
        record = logging.LogRecord("suite2p", logging.INFO, "", 0, message, (), None)
        return self.filter.filter(record)

    def test_drops_roi_candidate_progress_messages(self):
        self.assertFalse(
            self._keeps(
                "ROIs: 0, candidates: 6000, current peak score: 30.5955, "
                "minimum peak score: 10.3167, time: 48.33sec, size rejected: min_pixels=6001"
            )
        )

    def test_drops_legacy_roi_progress_messages(self):
        self.assertFalse(self._keeps("ROIs: 500,\t last score: 12.3456, \t time: 4.20sec"))

    def test_keeps_useful_suite2p_messages(self):
        self.assertTrue(self._keeps("----------- ROI DETECTION"))
        self.assertTrue(self._keeps("Detected 42 ROIs, 8.25 sec"))


if __name__ == "__main__":
    unittest.main()
