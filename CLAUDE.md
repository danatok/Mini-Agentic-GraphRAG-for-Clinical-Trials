# Claude Code Instructions — Mini Agentic GraphRAG for Clinical Trials

Paste this into Claude Code (in VS Code) as your opening prompt. Adjust AWS profile/region details to match your setup before running.

---

# Claude Code Instructions — Mini Agentic GraphRAG for Clinical Trials

Paste this into Claude Code (in VS Code) as your opening prompt. Adjust AWS profile/region details to match your setup before running.

---

## ⚠️ Budget: keep total AWS spend under 5-10 CHF

This project must be cost-controlled. Before writing any infrastructure code, do the following and confirm with me:

1. **Set an AWS Budget alert** at $8 USD (roughly the CHF 5-10 range) via AWS Budgets, so I get a warning before any accidental overspend.
2. **Vector storage: use a local FAISS index, not a managed AWS vector store.** This avoids OpenSearch Serverless entirely — its "Classic" collection type bills a minimum 24/7 (roughly $175-350/month) even sitting idle if the wrong collection type is accidentally selected, and that risk isn't worth taking for a one-day demo. FAISS running locally has zero AWS cost and no risk of a forgotten billable resource. This is also a direct callback to real production experience (SBERT + FAISS semantic search work), so it's a stronger interview story than a brand-new managed service touched for the first time.
3. **Neptune: use Neptune Database Serverless, not Neptune Analytics.** Neptune Analytics' smallest capacity tier is 32 m-NCUs, which is both oversized and more expensive than needed for a 20-30 node demo graph doing simple relationship traversal (no heavy graph algorithms needed here). Neptune Database Serverless scales down to a 1 NCU minimum (~$0.11/hour), which is the cheaper and better-fitting choice for this use case. Configure it with a low max NCU cap (e.g. 2.5) to prevent runaway autoscaling costs. **This is the only billable AWS resource this project creates** — everything else (FAISS, Bedrock, Lambda) is either free or pay-per-call with no idle cost.
4. **Bedrock: use a small/cheap model for both embeddings and LLM calls** — Titan Text Embeddings V2 for embeddings, and Claude Haiku (or an equivalent small model) for the agent's reasoning/synthesis calls, not a large model. Query volume here is tiny (dozens of calls at most), so cost risk from Bedrock itself is minimal regardless, but use the cheap models anyway.
5. **Minimize active infrastructure time.** Build and test the pipeline in stages, but don't leave Neptune running between work sessions — pause/stop it (paused = ~10% of compute cost) between sessions if you're spreading this across more than one sitting.
6. **Run the teardown script (step 6 below) the moment the demo is working and captured** — don't leave Neptune running after you've recorded example output for the README.

## Project goal

Build a small, working demonstration of **Agentic GraphRAG** applied to clinical trial data — combining a knowledge graph (structured relationships between trials, conditions, drugs, and sites) with unstructured document retrieval (trial descriptions and eligibility criteria), orchestrated by an **Amazon Bedrock Agent** that can query both and synthesize an answer neither source could produce alone.

This is a portfolio/demo project to prepare for an AWS ProServe interview (Healthcare & Life Sciences data consulting role) — it should be small, well-documented, and genuinely working end-to-end rather than large in scope. Prioritize a clean, explainable architecture over breadth of features.

## Target architecture

```
ClinicalTrials.gov API (data source)
        │
        ▼
Local staging (JSON/CSV) — trials, conditions, interventions, sites
        │
        ├──► Graph layer: Amazon Neptune Database Serverless (public endpoint, no VPC, min 1 NCU)
        │      nodes: Trial, Condition, Intervention, Site
        │      edges: STUDIES, USES_INTERVENTION, CONDUCTED_AT
        │
        └──► Vector layer: local FAISS index (no AWS cost, no idle-billing risk)
               embeds: trial descriptions + eligibility criteria text (Titan Text Embeddings V2)
        │
        ▼
Amazon Bedrock Agent (Action Groups) — given a natural-language question:
  1. Agent reasons about whether it needs graph traversal, vector search, or both
  2. Action Group 1 (Lambda): runs an openCypher query against Neptune Database
  3. Action Group 2 (Lambda): loads the local FAISS index, embeds the question via Titan, runs similarity search
  4. Agent synthesizes both result sets into a final answer with citations to which trial(s) it used
```

## Step-by-step build plan

### 1. Project scaffolding
- Create a new Python project (`clinical-graphrag-demo/`) with a virtual environment
- `requirements.txt`: `boto3`, `requests`, `faiss-cpu`, `python-dotenv`
- `.env.example` for AWS profile/region and any config
- `README.md` with a short architecture diagram (ASCII is fine) and setup instructions — this README is the actual interview artifact, write it clearly

### 2. Data ingestion — ClinicalTrials.gov
- Use the free ClinicalTrials.gov API (v2, `https://clinicaltrials.gov/api/v2/studies`) to pull ~20-30 trials for a specific condition (e.g. "type 2 diabetes" or "breast cancer" — pick one to keep the demo focused)
- Extract for each trial: NCT ID, title, brief summary, eligibility criteria text, conditions studied, interventions/drugs used, and study sites (location/facility name)
- Save raw responses to `data/raw/` and a cleaned, flattened version to `data/processed/trials.json`
- Write this as a standalone script (`scripts/01_fetch_data.py`) so it's re-runnable

### 3. Build the graph layer — Neptune Database Serverless
- Write a script (`scripts/02_build_graph.py`) that transforms `trials.json` into openCypher `CREATE` statements or Neptune's CSV bulk-load format:
  - Nodes: Trial, Condition, Intervention, Site
  - Edges: STUDIES (Trial→Condition), USES (Trial→Intervention), CONDUCTED_AT (Trial→Site)
- Write `scripts/setup_neptune.py` (boto3) that:
  - Creates a **Neptune Database Serverless** cluster with a public endpoint (explicitly confirm no VPC/private endpoint is configured, to avoid setup overhead) and a capped NCU range (min 1, max 2.5)
  - Loads the graph data (small enough to load via direct openCypher `CREATE` calls rather than needing S3 bulk import, given only ~100-150 total nodes/edges)
- Write 3-4 example openCypher queries in a script (`scripts/03_query_graph.py`) demonstrating multi-hop traversal, e.g.: "find all trials studying Drug X" or "find trials sharing a site with Trial Y"

### 4. Build the vector layer — local FAISS
- Write `scripts/04_build_vector_index.py` that:
  - Takes each trial's brief summary + eligibility criteria text
  - Generates embeddings using **Amazon Bedrock Titan Text Embeddings V2** via boto3 (no AWS storage infra needed — the embedding call is pay-per-call, no idle cost)
  - Builds a local FAISS index (`data/index/trials.faiss`) with a mapping back to NCT IDs and source text, saved to disk
- Keep this simple — no need for chunking strategy complexity given the small document size (trial summaries are short)

### 5. Orchestration — Amazon Bedrock Agent
- Set up a **Bedrock Agent** with two Action Groups, each backed by a small Lambda function:
  - `graph_query` — takes extracted entities (e.g. a drug or condition name) and runs the corresponding openCypher query against Neptune Database, returns the relationship results
  - `vector_search` — takes the user's question, embeds it via Titan, loads the local FAISS index (bundle it with the Lambda deployment package, or load from S3 if size requires it) and runs similarity search, returns matching trial text snippets
- Write the agent's instructions/system prompt to explain when to use each tool (graph for relationship questions, vector search for contextual/free-text questions, both when the question needs both — see the "why combine graph and unstructured retrieval" reasoning in the interview prep PDF for the framing to give the agent)
- Use **Claude Haiku** (or an equivalent small Bedrock model) as the agent's underlying model to keep inference costs minimal
- Write `scripts/05_test_agent.py` that invokes the agent with 2-3 example questions and prints the full response, so you have real output to paste into the README
- Example questions to test, chosen because they showcase why *both* sources are needed:
  - "What eligibility restrictions are mentioned in trials that study Drug X at more than one site?" (graph finds the trials, vector search pulls the restriction text)
  - "Which trials studying similar conditions to Trial NCT12345 have documented site-related risks in their descriptions?"

### 6. Cleanup script — run this immediately after capturing demo output
- `scripts/06_teardown.py` (boto3) that, in order:
  - Deletes the Bedrock Agent and its Action Groups/Lambda functions
  - Deletes the Neptune Database Serverless cluster
  - Deletes any S3 scratch data/buckets created (the local FAISS index file itself needs no cloud cleanup — it's just a local file)
  - Prints a final confirmation listing everything that was deleted, so there's a clear record that cleanup happened
- Run this script and confirm its output before ending the work session — don't leave infrastructure running "just in case"

### 7. README — write this last, and make it good
Include:
- One-paragraph explanation of the architecture and why graph + vector are combined (graphs show explicit relationships like trial→site→intervention, but can't capture nuanced eligibility/risk language living in free text — this is the same reasoning covered in the interview prep material)
- Architecture diagram (ASCII)
- Setup/run instructions
- 2-3 example agent queries with actual output pasted in (from step 5's test script)
- A short "what I'd do differently at production scale" section — e.g. mention that a production version would use a managed vector store (Bedrock Knowledge Bases with OpenSearch Serverless, sized properly) instead of local FAISS, Bedrock Knowledge Bases' managed GraphRAG as an alternative to hand-building this pipeline, AWS Context as a way to auto-infer the graph relationships instead of hand-modeling them, and Bedrock AgentCore for production-grade policy controls and observability beyond what a single Bedrock Agent provides — this shows you understand the toy-demo-vs-production distinction, which matters in a consulting interview

## Constraints and priorities

- **Time-boxed to one day.** If Neptune or Bedrock Agent setup eats too much time, it's acceptable to fall back to a local graph library (`networkx`) and a simpler direct-LLM-call orchestration instead of a full Bedrock Agent, noting this simplification clearly in the README. A working local demo beats a half-finished cloud one.
- **Cost discipline is a hard constraint, not a nice-to-have** — re-read the budget section above before creating any billable resource, and confirm cluster configuration explicitly rather than accepting defaults. Neptune Database Serverless is the only billable resource this project should create.
- **Keep the dataset small** (~20-30 trials, one condition) — this is a demo of the pattern, not a production system.
- **Prioritize the README and a working demo over code polish** — what gets talked about in the interview is the architecture and the reasoning, not code style.
- Confirm AWS credentials/profile are configured, that Bedrock model access is enabled for Titan Embeddings and Claude Haiku, and that the AWS Budget alert from step 1 is active before running any script that creates billable AWS resources.

