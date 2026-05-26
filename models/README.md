Models used by this repository
=============================

This directory stores depth models used by `video_ml.py`.

Included files
--------------

- `fast_depth.onnx`
  - Original name: Depth Anything V2 (small)
  - Source: https://huggingface.co/onnx-community/depth-anything-v2-small (onnx/model.onnx)
  - Notes: small/speed-focused ONNX model used as the "fast" backend.

- `midas_small.onnx`
  - Original name: MiDaS (small)
  - Source: https://github.com/isl-org/MiDaS
  - Notes: MiDaS small model used as the baseline/depth reference (may be a converted ONNX export).

If you prefer to keep model binaries under version control, remove the `models/*.onnx` entry from the repository `.gitignore`.

License & attribution
---------------------
Each model retains its original license and attribution. Refer to the upstream repositories for license terms and citation information.

If you want me to add additional metadata (SHA256 checksums, exact upstream download commands, or alternate model sources), tell me and I will update this file.
