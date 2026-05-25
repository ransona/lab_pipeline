"""Universal pupil preprocessing entrypoint.

This intentionally uses the newer preprocess_pupil implementation for both
standard and mesoscope experiments. The old meso-specific pupil-fitting path is
not carried forward here; the only CSV naming convention supported is the newer
all_setups DeepLabCut output used by preprocess_pupil.py.
"""

import sys

from preprocess_pipeline.pupil.core import preprocess_pupil_run


def main():
    try:
        userID = sys.argv[1]
        expID = sys.argv[2]
        print('Parameters received via command line')
    except Exception:
        print('Parameters received via debug mode')
        userID = 'adamranson'
        expID = '2026-01-19_01_ESRC026'

    preprocess_pupil_run(userID, expID)


if __name__ == "__main__":
    main()
