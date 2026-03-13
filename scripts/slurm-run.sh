#!/usr/bin/env bash
#SBATCH --job-name=patchr
#SBATCH --partition=normal
#SBATCH --gres=gpu:ada:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=UNLIMITED
#SBATCH --output=slurm_logs/patchr_%j.out
#SBATCH --error=slurm_logs/patchr_%j.err
set -euo pipefail

IMAGE="docker://ghcr.io/deepfoldprotein/patchr:latest"
SIF_CACHE="${HOME}/.apptainer/cache"
CACHE_DIR="${BOLTZ_CACHE:-$HOME/.boltz}"
OUTPUT_DIR="${PATCHR_OUTPUT:-$(pwd)/output}"

mkdir -p "${CACHE_DIR}" "${OUTPUT_DIR}" slurm_logs "${SIF_CACHE}"

echo "Job ID:    ${SLURM_JOB_ID}"
echo "Node:      $(hostname)"
echo "GPUs:      ${CUDA_VISIBLE_DEVICES:-not set}"
echo "Image:     ${IMAGE}"
echo "Cache:     ${CACHE_DIR}"
echo "Output:    ${OUTPUT_DIR}"

apptainer run --nv \
    --bind "${CACHE_DIR}:/root/.boltz" \
    --bind "${OUTPUT_DIR}:/app/output" \
    --env BOLTZ_CACHE=/root/.boltz \
    --env PROTENIX_ROOT_DIR=/root/.boltz \
    "${IMAGE}" \
    patchr serve --host 0.0.0.0 --port 31212
