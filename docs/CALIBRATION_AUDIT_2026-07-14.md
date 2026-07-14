# Measurement Calibration Audit - 2026-07-14

## Scope

This audit covers `vision_host.yaml` measurement fields used by
`dual_camera_measure.py`. It does not enable measurement/scoring, change PLC
write behavior, or alter `vision_host_app.py` runtime behavior.

## Confirmed PLC Saw Bits

| Bit | Saw label | Physical mm from fence |
|---|---:|---:|
| 0 | 0.0 | 18 |
| 1 | 0.3 | 270 |
| 2 | 0.6 | 560 |
| 3 | 3.0 | 3057 |
| 4 | 3.6 | 3670 |
| 5 | 4.2 | 4249 |
| 6 | 4.8 | 4813 |
| 7 | 5.4 | 5490 |
| 8 | 6.0 | 6023 |
| 9 | 6.6 | 6660 |

`0x0201` decodes to `0.0+6.6`; `0x0000` is no cuts.
All ten saws set is `0x03FF`.

## Calibration Sources

- `vision_host.yaml` still has the old actual-measurement fit:
  - LEFT `px_per_mm_left=0.24193`, `width_line_px_left=1342`
  - RIGHT `px_per_mm_right=0.31057`, `right_view_x0_mm=3241.8`
- `calibration/grading_calibration_2026-07-09.json` is an operator-confirmed
  review-overlay point set, including LEFT 0.0 at x=888.252. It is not yet a
  validated measurement fit.

## Fit Check Against JSON Points

Using the confirmed physical millimetres above:

| Side | Fit | Maximum residual |
|---|---|---:|
| LEFT | linear `px = 0.30030411*mm + 1006.802` | 123.96 px |
| RIGHT | linear, excludes estimated 6.6 | 56.85 px |
| LEFT | projective fit | 7.14 px |
| RIGHT | projective fit, excludes estimated 6.6 | 6.87 px |

The required acceptance target is less than 3 px. Do not copy either fit
into the actual `vision_host.yaml` measurement fields.

## Required Fresh Calibration

1. Put a marked board in the normal stopped position using the current camera
   placement.
2. Mark at least 3-5 known fence distances in each camera view. Include 860
   mm for LEFT and do not rely on the estimated RIGHT 6.6 point.
3. Run `calibrate_from_lines.py` per camera with those exact millimetres and
   save the debug images.
4. Accept only a fit with maximum residual below 3 px.
5. Update `vision_host.yaml` measurement fields from that accepted fit.
6. Run `calib_saw_overlay.py` and visually inspect the generated overlays on
   the same current marked board before any measurement-mode use.
