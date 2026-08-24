"""Build a local FAISS index over trial text, embedded via Bedrock Titan Text Embeddings V2.

Each trial's brief summary + eligibility criteria are concatenated into one
document and embedded. The index and a sidecar mapping (row -> nct_id + text)
are written to data/index/, so a similarity search can be mapped back to the
source trial.
"""
import json
import os
from pathlib import Path

import boto3
import faiss
import numpy as np
from dotenv import load_dotenv

load_dotenv()

REGION = os.getenv("AWS_REGION", "us-east-1")
EMBEDDING_MODEL_ID = os.getenv("BEDROCK_EMBEDDING_MODEL_ID", "amazon.titan-embed-text-v2:0")

ROOT = Path(__file__).resolve().parent.parent
TRIALS_PATH = ROOT / "data" / "processed" / "trials.json"
INDEX_DIR = ROOT / "data" / "index"
INDEX_PATH = INDEX_DIR / "trials.faiss"
MAPPING_PATH = INDEX_DIR / "trials_mapping.json"

bedrock = boto3.client("bedrock-runtime", region_name=REGION)


def embed_text(text: str) -> list[float]:
    resp = bedrock.invoke_model(
        modelId=EMBEDDING_MODEL_ID,
        body=json.dumps({"inputText": text[:8000]}),
        contentType="application/json",
        accept="application/json",
    )
    payload = json.loads(resp["body"].read())
    return payload["embedding"]


def trial_document(trial: dict) -> str:
    parts = [
        trial.get("title") or "",
        trial.get("brief_summary") or "",
        trial.get("eligibility_criteria") or "",
    ]
    return "\n\n".join(p for p in parts if p)


def main() -> None:
    trials = json.loads(TRIALS_PATH.read_text())
    print(f"Embedding {len(trials)} trials with {EMBEDDING_MODEL_ID}")

    vectors: list[list[float]] = []
    mapping: list[dict] = []
    for i, trial in enumerate(trials, 1):
        nct_id = trial.get("nct_id")
        if not nct_id:
            continue
        doc = trial_document(trial)
        if not doc.strip():
            continue
        embedding = embed_text(doc)
        vectors.append(embedding)
        mapping.append({"nct_id": nct_id, "title": trial.get("title") or "", "text": doc})
        print(f"  [{i}/{len(trials)}] embedded {nct_id} (dim={len(embedding)})")

    matrix = np.array(vectors, dtype="float32")
    dim = matrix.shape[1]

    index = faiss.IndexFlatIP(dim)
    faiss.normalize_L2(matrix)
    index.add(matrix)

    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(INDEX_PATH))
    MAPPING_PATH.write_text(json.dumps(mapping, indent=2))

    print(f"\nWrote FAISS index ({index.ntotal} vectors, dim={dim}) to {INDEX_PATH}")
    print(f"Wrote mapping to {MAPPING_PATH}")


if __name__ == "__main__":
    main()
