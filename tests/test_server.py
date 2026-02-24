#!/usr/bin/env python3
"""Simple test script for Boltz Inpainting API Server."""

import json
import shutil
import time
import zipfile
from pathlib import Path

import requests

# Configuration
BASE_URL = "http://localhost:31212"
CIF_FILE = "examples/inpainting/4j76.cif"
FASTA_FILE = "examples/inpainting/4j76_uniprot.fasta"
CHAIN_IDS = "A,B"  # Both chains


def read_fasta_sequences(fasta_file: str) -> dict:
    """Read sequences from FASTA file and return as dict {chain: sequence}."""
    sequences = {}
    current_chain = None
    current_seq = []
    
    with open(fasta_file, "r") as f:
        for line in f:
            line = line.strip()
            if line.startswith(">"):
                # Save previous chain if exists
                if current_chain and current_seq:
                    sequences[current_chain] = "".join(current_seq)
                
                # Parse chain from header (e.g., ">Chain A" -> "A")
                header = line[1:].strip()
                if "Chain" in header:
                    current_chain = header.split("Chain")[-1].strip()
                else:
                    # Fallback: use first word after >
                    current_chain = header.split()[0] if header.split() else None
                
                current_seq = []
            elif line and current_chain:
                current_seq.append(line)
        
        # Save last chain
        if current_chain and current_seq:
            sequences[current_chain] = "".join(current_seq)
    
    return sequences


def main():
    """Test server with 4j76.cif file and FASTA sequences."""
    print("Testing Boltz Inpainting API Server")
    print("=" * 50)

    # 1. Health check
    print("\n1. Health check...")
    try:
        response = requests.get(f"{BASE_URL}/api/v1/health")
        response.raise_for_status()
        print(f"✓ Server is healthy: {response.json()}")
    except Exception as e:
        print(f"✗ Health check failed: {e}")
        return

    # 2. Read FASTA sequences
    print(f"\n2. Reading FASTA sequences from {FASTA_FILE}...")
    if not Path(FASTA_FILE).exists():
        print(f"✗ File not found: {FASTA_FILE}")
        return
    
    sequences = read_fasta_sequences(FASTA_FILE)
    print(f"✓ Found sequences for chains: {list(sequences.keys())}")
    for chain, seq in sequences.items():
        print(f"  Chain {chain}: {len(seq)} residues")

    # 3. Upload CIF file with custom sequences
    print(f"\n3. Uploading {CIF_FILE} with custom sequences...")
    if not Path(CIF_FILE).exists():
        print(f"✗ File not found: {CIF_FILE}")
        return

    # Format custom sequences as "A:SEQ1,B:SEQ2"
    custom_sequences_str = ",".join([f"{chain}:{seq}" for chain, seq in sequences.items()])
    
    with open(CIF_FILE, "rb") as f:
        files = {"cif_file": (Path(CIF_FILE).name, f, "application/octet-stream")}
        data = {
            "chain_ids": CHAIN_IDS,
            "custom_sequences": custom_sequences_str,
        }

        try:
            response = requests.post(
                f"{BASE_URL}/api/v1/template/upload",
                files=files,
                data=data,
            )
            response.raise_for_status()
            template_job = response.json()
            job_id = template_job["job_id"]
            print(f"✓ Template job created: {job_id}")
            print(f"  Status: {template_job['status']}")
            print(f"  Chains: {CHAIN_IDS}")
        except Exception as e:
            print(f"✗ Upload failed: {e}")
            return

    # 4. Wait for template generation
    print("\n4. Waiting for template generation...")
    while True:
        response = requests.get(f"{BASE_URL}/api/v1/jobs/{job_id}")
        response.raise_for_status()
        status = response.json()

        print(f"  Status: {status['status']}")
        if status.get("progress"):
            print(f"  Progress: {status['progress']}")

        if status["status"] == "completed":
            print("✓ Template generation completed!")
            break
        elif status["status"] == "failed":
            print(f"✗ Template generation failed: {status.get('error')}")
            return

        time.sleep(2)

    # 5. Run prediction
    print("\n5. Running prediction...")
    payload = {
        "job_id": job_id,
        "recycling_steps": 3,
        "sampling_steps": 200,
        "diffusion_samples": 1,
        "devices": 1,
        "accelerator": "gpu",
        "use_msa_server": False,
    }

    try:
        response = requests.post(
            f"{BASE_URL}/api/v1/predict/run",
            json=payload,
        )
        response.raise_for_status()
        prediction_job = response.json()
        print(f"✓ Prediction started: {prediction_job['status']}")
    except Exception as e:
        print(f"✗ Prediction start failed: {e}")
        return

    # 6. Monitor prediction progress
    print("\n6. Monitoring prediction progress...")
    print("  (This may take a while...)")

    while True:
        response = requests.get(f"{BASE_URL}/api/v1/jobs/{job_id}")
        response.raise_for_status()
        status = response.json()

        current_status = status["status"]
        if status.get("progress"):
            print(f"  [{current_status}] {status['progress']}")

        if current_status == "completed":
            print("\n✓ Prediction completed!")
            break
        elif current_status == "failed":
            print(f"\n✗ Prediction failed: {status.get('error')}")
            return

        time.sleep(5)

    # 7. Download and extract results
    print("\n7. Downloading and extracting results...")
    output_dir = Path("test_outputs") / job_id
    output_dir.mkdir(parents=True, exist_ok=True)
    
    try:
        # Download prediction results
        print("  Downloading prediction results...")
        response = requests.get(
            f"{BASE_URL}/api/v1/jobs/{job_id}/files/prediction",
            stream=True,
        )
        response.raise_for_status()
        
        zip_path = output_dir / f"{job_id}_predictions.zip"
        with open(zip_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        
        print(f"  ✓ Downloaded: {zip_path}")
        
        # Extract zip file
        print("  Extracting zip file...")
        extract_dir = output_dir / "predictions"
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(extract_dir)
        
        print(f"  ✓ Extracted to: {extract_dir}")
        
        # List extracted files
        extracted_files = list(extract_dir.rglob("*"))
        print(f"  ✓ Extracted {len(extracted_files)} files")
        for f in sorted(extracted_files)[:10]:  # Show first 10 files
            if f.is_file():
                print(f"    - {f.relative_to(extract_dir)}")
        if len(extracted_files) > 10:
            print(f"    ... and {len(extracted_files) - 10} more files")
            
    except Exception as e:
        print(f"  ✗ Failed to download/extract results: {e}")

    # 8. Final status
    print("\n8. Final job status:")
    response = requests.get(f"{BASE_URL}/api/v1/jobs/{job_id}")
    response.raise_for_status()
    final_status = response.json()
    print(json.dumps(final_status, indent=2))

    print("\n" + "=" * 50)
    print("Test completed!")
    print(f"Job ID: {job_id}")
    print(f"View status: {BASE_URL}/api/v1/jobs/{job_id}")
    print(f"Results extracted to: {output_dir / 'predictions'}")


if __name__ == "__main__":
    main()
