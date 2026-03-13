#!/usr/bin/env bash
set -euo pipefail

IMAGE="ghcr.io/deepfoldprotein/patchr"
VERSION=$(python3 -c "
import tomllib, pathlib
d = tomllib.loads(pathlib.Path('pyproject.toml').read_text())
print(d['project']['version'])
")

echo "Building patchr v${VERSION}..."
docker build -t "${IMAGE}:${VERSION}" -t "${IMAGE}:latest" .

echo "Pushing ${IMAGE}:${VERSION} and :latest..."
docker push "${IMAGE}:${VERSION}"
docker push "${IMAGE}:latest"

echo "Done: ${IMAGE}:${VERSION}"
