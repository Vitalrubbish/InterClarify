# Vendored TurnSense service (pinned)

This directory vendors the standalone TurnSense ONNX HTTP service so the
round-one X-Talk runner can launch a turn detector without cloning an external
repository inside the job container.

- Upstream repository: https://github.com/xcc-zach/xtalk-TurnSense
- Pinned commit: `cc0681c85771117958785faf3d6a7f402018a83e` (2026-07-06)
- Files vendored verbatim: `service.py`, `infer.py`, `frontend/audio_frontend.py`,
  `frontend/__init__.py`, and `requirements.txt` (upstream
  `requirements/base.txt`).
- Not vendored: `install.sh` / `start.sh` (we launch `service.py` directly),
  examples, images, and the TurnBench harness.

Model assets are not vendored here. They are the upstream TurnSense 1.1 ONNX
export and CMVN file, staged by the round-one model preparation under
`$XTALK_ROUND1_MODEL_ROOT/turnsense/`:

- `model_int8.onnx` (default `service.py` model), and
- `am.mvn` (Kaldi-style CMVN).

Do not edit these files in place; re-vendor from the pinned upstream commit when
upgrading.
