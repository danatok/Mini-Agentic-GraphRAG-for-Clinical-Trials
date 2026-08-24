"""Agentic GraphRAG orchestration and test harness.

Bedrock Agents (Classic) is in account-wide maintenance mode as of this
project (new agent creation blocked for accounts without prior usage — see
README's "Why not a managed Bedrock Agent" note), so orchestration here is a
script-driven tool-calling loop instead of a managed Agent resource:

  1. Claude Haiku 4.5 (via Bedrock Converse API) reasons over the question
     and decides which tool(s) to call, using native tool-use.
  2. Each tool call is executed by invoking the SAME Lambda functions that
     would have backed a Bedrock Agent's Action Groups
     (clinical-graphrag-graph-query, clinical-graphrag-vector-search) — so
     the real Action Group architecture is exercised, just orchestrated
     locally instead of by a managed Agent.
  3. Tool results are fed back to the model, which synthesizes a final,
     cited answer.

Run directly to execute the example questions and print full transcripts.
"""
import json
import os
from pathlib import Path

import boto3
from dotenv import load_dotenv

load_dotenv()

REGION = os.getenv("AWS_REGION", "us-east-1")
MODEL_ID = os.getenv("BEDROCK_AGENT_MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001-v1:0")

GRAPH_QUERY_LAMBDA = "clinical-graphrag-graph-query"
VECTOR_SEARCH_LAMBDA = "clinical-graphrag-vector-search"

bedrock = boto3.client("bedrock-runtime", region_name=REGION)
lambda_client = boto3.client("lambda", region_name=REGION)

SYSTEM_PROMPT = (Path(__file__).resolve().parent.parent / "agent_instruction.txt").read_text()

TOOLS = [
    {
        "toolSpec": {
            "name": "find_trials_by_intervention",
            "description": "Find trials that use a given drug/intervention, via the knowledge graph.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {"intervention_name": {"type": "string", "description": "Drug or intervention name"}},
                    "required": ["intervention_name"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "find_trials_sharing_site",
            "description": "Find other trials that were conducted at the same site(s) as a given trial, via the knowledge graph.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {"nct_id": {"type": "string", "description": "NCT ID of the trial"}},
                    "required": ["nct_id"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "get_trial_relationships",
            "description": "Get the conditions, interventions, sites, and full eligibility criteria text for a specific trial by NCT ID, via the knowledge graph. Prefer this over vector search when you already know the NCT ID.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {"nct_id": {"type": "string", "description": "NCT ID of the trial"}},
                    "required": ["nct_id"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "search_trials",
            "description": "Semantic search over trial descriptions and eligibility criteria free text. Use for nuanced language questions that aren't explicit relationships.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "query_text": {"type": "string", "description": "Natural-language search query"},
                        "top_k": {"type": "string", "description": "Number of results to return, default 3"},
                    },
                    "required": ["query_text"],
                }
            },
        }
    },
]

TOOL_TO_LAMBDA = {
    "find_trials_by_intervention": (GRAPH_QUERY_LAMBDA, "graph_query"),
    "find_trials_sharing_site": (GRAPH_QUERY_LAMBDA, "graph_query"),
    "get_trial_relationships": (GRAPH_QUERY_LAMBDA, "graph_query"),
    "search_trials": (VECTOR_SEARCH_LAMBDA, "vector_search"),
}


def invoke_tool(tool_name: str, tool_input: dict) -> dict:
    function_name, action_group = TOOL_TO_LAMBDA[tool_name]
    payload = {
        "actionGroup": action_group,
        "function": tool_name,
        "parameters": [{"name": k, "type": "string", "value": str(v)} for k, v in tool_input.items()],
    }
    resp = lambda_client.invoke(FunctionName=function_name, Payload=json.dumps(payload).encode())
    body = json.loads(resp["Payload"].read())
    return json.loads(body["response"]["functionResponse"]["responseBody"]["TEXT"]["body"])


def ask(question: str, max_turns: int = 6) -> str:
    messages = [{"role": "user", "content": [{"text": question}]}]

    for _ in range(max_turns):
        resp = bedrock.converse(
            modelId=MODEL_ID,
            system=[{"text": SYSTEM_PROMPT}],
            messages=messages,
            toolConfig={"tools": TOOLS},
        )
        output_message = resp["output"]["message"]
        messages.append(output_message)

        if resp["stopReason"] != "tool_use":
            return "".join(block.get("text", "") for block in output_message["content"])

        tool_results = []
        for block in output_message["content"]:
            if "toolUse" not in block:
                continue
            tool_use = block["toolUse"]
            print(f"  [tool call] {tool_use['name']}({tool_use['input']})")
            result = invoke_tool(tool_use["name"], tool_use["input"])
            print(f"  [tool result] {json.dumps(result)[:300]}")
            tool_results.append(
                {
                    "toolResult": {
                        "toolUseId": tool_use["toolUseId"],
                        "content": [{"json": result}],
                    }
                }
            )
        messages.append({"role": "user", "content": tool_results})

    return "(max turns reached without a final answer)"


EXAMPLE_QUESTIONS = [
    "What eligibility restrictions are mentioned in trials that study insulin glargine?",
    "What conditions and interventions are associated with trial NCT00982644, and what does its eligibility criteria say about pregnancy?",
    "Which trials focus on elderly patients with type 2 diabetes, based on their descriptions?",
]


def main() -> None:
    for i, question in enumerate(EXAMPLE_QUESTIONS, 1):
        print("=" * 80)
        print(f"Q{i}: {question}")
        print("=" * 80)
        answer = ask(question)
        print(f"\nAnswer:\n{answer}\n")


if __name__ == "__main__":
    main()
