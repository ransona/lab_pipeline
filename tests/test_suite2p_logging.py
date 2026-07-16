import logging
import unittest
from unittest import mock

from preprocess_pipeline.suite2p import backend
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


class Suite2pApiDetectionTests(unittest.TestCase):
    def test_detects_new_suite2p_api_from_signature_when_version_is_unknown(self):
        def run_s2p(db=None, settings=None):
            return None

        with mock.patch.object(backend, "suite2p_version", return_value="unknown"):
            with mock.patch.object(backend.suite2p, "run_s2p", run_s2p):
                self.assertTrue(backend.is_suite2p_1x())

    def test_keeps_legacy_suite2p_api_when_signature_has_ops(self):
        def run_s2p(ops=None, db=None):
            return None

        with mock.patch.object(backend, "suite2p_version", return_value="unknown"):
            with mock.patch.object(backend.suite2p, "run_s2p", run_s2p):
                self.assertFalse(backend.is_suite2p_1x())


if __name__ == "__main__":
    unittest.main()
