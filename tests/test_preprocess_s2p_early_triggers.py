import numpy as np
import pytest

from preprocess_pipeline.suite2p.preprocess import (
    find_preexisting_acquisition_trigger_pause,
    maybe_discard_preexisting_acquisition_triggers,
)


def test_find_preexisting_acquisition_trigger_pause_discards_every_pre_pause_trigger():
    frame_starts = np.array([0.01, 0.04, 0.07, 1.20, 1.23, 1.26])

    candidate = find_preexisting_acquisition_trigger_pause(frame_starts, timeline_start_time=0.0)

    assert candidate["discard_count"] == 3
    assert candidate["pause_seconds"] == pytest.approx(1.13)
    assert candidate["first_retained_trigger_time"] == pytest.approx(1.20)


def test_no_correction_when_first_trigger_is_not_early():
    frame_starts = np.array([0.60, 0.63, 1.30, 1.33])

    assert find_preexisting_acquisition_trigger_pause(frame_starts, 0.0) is None


def test_accepted_correction_never_retains_pre_pause_triggers_with_frame_deficit():
    frame_starts = np.array([0.01, 0.04, 0.07, 1.20, 1.23])
    prompts = []
    issues = []

    corrected = maybe_discard_preexisting_acquisition_triggers(
        frame_starts,
        timeline_start_time=0.0,
        expected_frame_count=4,
        confirm_callback=lambda message: prompts.append(message) or True,
        issues=issues,
    )

    np.testing.assert_array_equal(corrected, np.array([1.20, 1.23]))
    assert len(prompts) == 2
    assert "2 more TIFF frames" in prompts[1]
    assert "Discarded 3 pre-pause" in issues[0]


def test_suspected_preexisting_triggers_require_interactive_confirmation():
    frame_starts = np.array([0.01, 0.04, 1.20, 1.23])

    with pytest.raises(RuntimeError, match="Re-run Step 2 from QView"):
        maybe_discard_preexisting_acquisition_triggers(
            frame_starts,
            timeline_start_time=0.0,
            expected_frame_count=2,
        )
