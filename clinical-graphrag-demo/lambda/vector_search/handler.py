"""Bedrock Agent Action Group Lambda: vector_search.

Embeds the user's question via Bedrock Titan Text Embeddings V2, then runs
similarity search against a pre-built local FAISS index (trials.faiss,
bundled in the deployment package) and returns matching trial snippets.
"""
import json
import os

import boto3
import faiss
import numpy as np

REGION = os.environ.get("AWS_REGION", "us-east-1")
EMBEDDING_MODEL_ID = os.environ.get("BEDROCK_EMBEDDING_MODEL_ID", "amazon.titan-embed-text-v2:0")

bedrock = boto3.client("bedrock-runtime", region_name=REGION)
INDEX = faiss.read_index("trials.faiss")
with open("trials_mapping.json") as f:
    MAPPING = json.load(f)


def embed_text(text: str) -> np.ndarray:
    resp = bedrock.invoke_model(
        modelId=EMBEDDING_MODEL_ID,
        body=json.dumps({"inputText": text[:8000]}),
        contentType="application/json",
        accept="application/json",
    )
    payload = json.loads(resp["body"].read())
    vec = np.array([payload["embedding"]], dtype="float32")
    faiss.normalize_L2(vec)
    return vec


def search_trials(query_text: str, top_k: str = "3") -> dict:
    k = min(int(top_k), len(MAPPING))
    query_vec = embed_text(query_text)
    scores, indices = INDEX.search(query_vec, k)

    results = []
    for score, idx in zip(scores[0], indices[0]):
        if idx < 0:
            continue
        entry = MAPPING[idx]
        results.append(
            {
                "nct_id": entry["nct_id"],
                "title": entry["title"],
                "score": float(score),
                "snippet": entry["text"][:600],
            }
        )
    return {"query": query_text, "results": results}


def lambda_handler(event, context):
    action_group = event.get("actionGroup", "vector_search")
    function = event.get("function")
    params = {p["name"]: p["value"] for p in event.get("parameters", [])}

    if function == "search_trials":
        result = search_trials(**params)
    else:
        result = {"error": f"unknown function: {function}"}

    return {
        "messageVersion": "1.0",
        "response": {
            "actionGroup": action_group,
            "function": function,
            "functionResponse": {
                "responseBody": {"TEXT": {"body": json.dumps(result)}}
            },
        },
    }
