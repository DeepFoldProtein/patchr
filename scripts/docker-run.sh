#!/usr/bin/env bash
set -euo pipefail

IMAGE="ghcr.io/deepfoldprotein/patchr:latest"
GPU="${PATCHR_GPU:-all}"
CACHE_DIR="${BOLTZ_CACHE:-$HOME/.boltz}"
OUTPUT_DIR="${PATCHR_OUTPUT:-$(pwd)/output}"

# Create directories if they don't exist
mkdir -p "${CACHE_DIR}"
mkdir -p "${OUTPUT_DIR}"

# Build --gpus flag: "all" or device ids like "0" / "0,1"
if [ "${GPU}" = "all" ]; then
    GPU_FLAG="--gpus all"
else
    GPU_FLAG="--gpus '\"device=${GPU}\"'"
fi

echo "Image:  ${IMAGE}"
echo "GPUs:   ${GPU}"
echo "Cache:  ${CACHE_DIR} -> /root/.boltz"
echo "Output: ${OUTPUT_DIR} -> /app/output"

eval docker run ${GPU_FLAG} \
    -p 31212:31212 \
    -v "${CACHE_DIR}:/root/.boltz" \
    -v "${OUTPUT_DIR}:/app/output" \
    -e BOLTZ_CACHE=/root/.boltz \
    -e PROTENIX_ROOT_DIR=/root/.boltz \
    "${@}" \
    "${IMAGE}"
