#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."

PRED=outputs/1kx3_nuc/patchr_results_1kx3/predictions/1kx3
OUT=outputs/1kx3_nuc
FRAMES=$OUT/frames

.venv_viz/bin/python scripts/animation/render_pymol.py \
  --cif $PRED/1kx3_model_0.cif \
  --metadata $PRED/inpainting_metadata_1kx3.json \
  --npz $PRED/detailed_trajectory_1kx3_model_0.npz \
  --input-template-cif examples/inpainting/1KX3.cif \
  --out-dir $FRAMES \
  --width 1280 --height 960 \
  --every 4 --lrd-every 1 \
  --morph-frames 12 --intro-frames 12 \
  --rotate-x ${ROTX:-90} \
  --zoom-buffer 10

ffmpeg -y -framerate 24 \
  -i $FRAMES/frame_%04d.png \
  -vf "tpad=stop_mode=clone:stop_duration=2,fps=24" \
  -c:v libx264 -pix_fmt yuv420p -crf 18 \
  $OUT/1kx3_nuc_v1.mp4
