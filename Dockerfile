# syntax=docker/dockerfile:1
FROM nvidia/cuda:12.8.0-devel-ubuntu22.04

# ── Environment ──────────────────────────────────────────────────────
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CUTLASS_PATH=/opt/cutlass \
    CUDA_HOME=/usr/local/cuda

# ── System packages ──────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
        git wget curl \
        build-essential g++ gcc make cmake ninja-build \
        libc6-dev libffi-dev libssl-dev \
        software-properties-common \
        hmmer kalign \
    && add-apt-repository -y ppa:deadsnakes/ppa \
    && apt-get update && apt-get install -y --no-install-recommends \
        python3.11 python3.11-dev python3.11-venv python3.11-distutils \
    && update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1 \
    && update-alternatives --install /usr/bin/python python /usr/bin/python3.11 1 \
    && curl -sS https://bootstrap.pypa.io/get-pip.py | python3.11 \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# ── CUTLASS (needed by cuequivariance kernels) ───────────────────────
RUN git clone --depth 1 -b v3.5.1 https://github.com/NVIDIA/cutlass.git /opt/cutlass

# ── PyTorch (CUDA 12.8) ─────────────────────────────────────────────
RUN pip install --no-cache-dir \
        torch==2.10.0 --index-url https://download.pytorch.org/whl/cu128

# ── Python dependencies (leverage Docker layer cache) ────────────────
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ src/

# Install the project in editable mode
RUN pip install --no-cache-dir -e .

# ── Copy remaining project files ─────────────────────────────────────
COPY . .

# ── Expose server port ───────────────────────────────────────────────
EXPOSE 31212

# ── Default: launch the FastAPI server ───────────────────────────────
CMD ["patchr", "serve", "--host", "0.0.0.0", "--port", "31212"]
