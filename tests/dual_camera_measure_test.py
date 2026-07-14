"""Focused safety checks for current empty-reference gating."""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dual_camera_measure import (
    ERR_MEASURE_FAILED, MeasureConfig, _presence_and_extent,
    measure_dual_camera, probe_width_px,
)


def main() -> None:
    frame = np.full((100, 200, 3), 220, dtype=np.uint8)
    cfg = MeasureConfig(board_y_range_left=(20, 80), board_y_range_right=(20, 80),
                        presence_min_span_px=20, require_empty_reference=True)
    assert _presence_and_extent(frame, None, (20, 80), cfg) == (False, None, None)
    result = measure_dual_camera(frame, frame, None, cfg)
    assert result.error == ERR_MEASURE_FAILED
    assert "empty-deck reference" in result.notes[0]

    probe_frame = np.zeros((100, 200), dtype=np.uint8)
    probe_frame[31:79, 90:111] = 200
    width_px, samples = probe_width_px(
        probe_frame, 100, (10, 90), threshold=125,
        offsets=(-8, -4, 0, 4, 8), min_h=8, max_h=80)
    assert width_px == 48 and samples == 5
    print("PASS")


if __name__ == "__main__":
    main()
