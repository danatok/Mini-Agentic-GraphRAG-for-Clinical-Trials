# Mini-Agentic-GraphRAG-for-Clinical-Trials

A small, working demo of **Agentic GraphRAG** over clinical trial data: a knowledge graph of explicit relationships (which trials study which conditions, use which drugs, run at which sites) combined with vector search over unstructured trial text (descriptions, eligibility criteria), orchestrated by an LLM that decides which source(s) a question needs and synthesizes a cited answer. Graphs are precise about relationships but blind to nuance in free text ("what does this trial's eligibility criteria say about pregnancy?"); vector search is the reverse — it's fluent with free text but has no notion of explicit structure ("which trials use this drug?"). Neither source alone answers every question a clinical researcher would ask; combining them does.

Built as a portfolio project for an AWS ProServe (Healthcare & Life Sciences) interview. Full original build plan: [CLAUDE.md](CLAUDE.md).

**[Open the interactive graph visualization](graph_visualization.html)** — a self-contained, dependency-free HTML file (`scripts/07_visualize_graph.py` generates it from `data/processed/graph.gpickle`). Drag nodes, scroll to zoom, search to highlight, and toggle node types via the legend — Site nodes (213 of them) start hidden since there are far more of them than Trials/Conditions/Interventions combined.

## Architecture

```
ClinicalTrials.gov API (v2)
        │
        ▼
scripts/01_fetch_data.py  →  data/processed/trials.json  (25 type 2 diabetes trials)
        │
        ├──► scripts/02_build_graph.py                 ├──► scripts/04_build_vector_index.py
        │    local networkx graph                       │    Bedrock Titan Embeddings V2
        │    Trial / Condition / Intervention / Site     │    local FAISS index
        │    STUDIES / USES / CONDUCTED_AT edges          │    (data/index/trials.faiss)
        │    (data/processed/graph.gpickle)               │
        │                                                 │
        ▼                                                 ▼
  lambda/graph_query/handler.py                    lambda/vector_search/handler.py
  (bundles graph.gpickle)                           (bundles trials.faiss + mapping)
  find_trials_by_intervention                       search_trials(query_text, top_k)
  find_trials_sharing_site
  get_trial_relationships (incl. eligibility text)
        │                                                 │
        └───────────────────┬─────────────────────────────┘
                             ▼
              scripts/05_test_agent.py
              Claude Haiku 4.5 (Bedrock Converse API, native tool-use)
              reasons about the question → calls graph_query and/or
              vector_search Lambdas via boto3 → synthesizes a cited answer
```

Both Lambda functions are real, deployed AWS Lambdas — they're exactly what would have backed a Bedrock Agent's Action Groups. Orchestration is a local tool-calling loop instead of a managed Bedrock Agent resource; see "Why not a managed Bedrock Agent" below for why.

## Setup

```bash
cd clinical-graphrag-demo
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # adjust AWS_REGION / CONDITION if desired

python scripts/01_fetch_data.py          # pull trials from ClinicalTrials.gov
python scripts/02_build_graph.py         # build local networkx graph
python scripts/04_build_vector_index.py  # embed trials + build FAISS index
python scripts/07_visualize_graph.py     # generate graph_visualization.html
```

The two Lambda functions (`clinical-graphrag-graph-query`, `clinical-graphrag-vector-search`) and their IAM roles are created via the AWS CLI — see the packaging/deploy commands in [CLAUDE.md](CLAUDE.md) step 5, or redeploy by zipping `lambda/graph_query/` and `lambda/vector_search/` (bundling `graph.gpickle` / `trials.faiss` + `trials_mapping.json` alongside `handler.py`) and running `aws lambda update-function-code`.

Then run the orchestration/test script:

```bash
python scripts/05_test_agent.py
```

Prerequisites: AWS credentials configured (`aws configure`), an AWS Budget alert set (see CLAUDE.md step 1), and Bedrock model access enabled for `amazon.titan-embed-text-v2:0` and an Anthropic Claude model (Anthropic requires a one-time "use case details" form submission in the Bedrock console — see below).

## Example queries

**Q: What eligibility restrictions are mentioned in trials that study insulin glargine?**

The agent calls `find_trials_by_intervention("insulin glargine")`, gets back two trials, then calls `get_trial_relationships` on each to pull their eligibility text directly from the graph:

> Based on the trials studying insulin glargine, here are the eligibility restrictions:
>
> **NCT00982644** — "Comparison of NN1250 Versus Insulin Glargine in Subjects With Type 2 Diabetes"
> Inclusion: Type 2 diabetes mellitus; oral antidiabetic treatment ≥3 months at unchanged dose; HbA1c 7.0–10.0%; BMI ≤40.0 kg/m².
> Exclusion: Exenatide/liraglutide use within 3 months; cardiovascular disease within 6 months; uncontrolled severe hypertension; pregnancy/breastfeeding/inadequate contraception; cancer history.
>
> **NCT00191464** — "Long-Term Effects of Insulin Plus Metformin Regimens..."
> Inclusion: Type 2 diabetes; prior metformin/sulfonylurea use; HbA1c 6.5–11%; clinically acceptable LDL-C.
> Exclusion: Hypersensitivity to metformin/insulin lispro/insulin glargine; metabolic or lactic acidosis; renal transplant/dialysis; Class III/IV cardiac disease; clinical liver disease.

**Q: What conditions and interventions are associated with trial NCT00982644, and what does its eligibility criteria say about pregnancy?**

The agent calls `get_trial_relationships("NCT00982644")` — one graph lookup, no vector search needed, since the NCT ID is already known:

> **Conditions:** Diabetes, Diabetes Mellitus Type 2
> **Interventions:** Insulin degludec, Insulin glargine
> **Pregnancy:** The trial explicitly excludes pregnant women and those who are breastfeeding. Exclusion criteria state: "Pregnancy, breast-feeding, the intention of becoming pregnant or not using adequate contraceptive measures."

This is the clearest illustration of why the two layers are complementary: earlier versions of this demo tried answering the same question with `vector_search` alone, which searches semantically across *all* 25 trials and has no way to filter to a specific NCT ID — it kept surfacing unrelated trials instead of NCT00982644's own text. Routing through the graph once the ID is known fixed it; see the "lesson learned" note below.

**Q: Which trials focus on elderly patients with type 2 diabetes, based on their descriptions?**

The agent tries two `vector_search` queries with different phrasings and honestly reports a negative result rather than fabricating one:

> Based on my semantic search, the search results did not identify any trials with a strong explicit focus on elderly patients. Most trials in this dataset have broad inclusion criteria (e.g. 18+ or 18-75 years) rather than specifically geriatric-focused populations. Would you like me to check full eligibility text for age cutoffs, or search with different keywords ("frailty", "comorbidities")?

## Why not Neptune

The original design called for the graph layer to run on **Amazon Neptune Database Serverless**. During setup, `CreateDBCluster` failed with:

```
FreeTierRestrictionError: The specified cluster engine type is not available with free plan accounts.
Available engine types: [aurora-postgresql]
```

This AWS account is on a "Free Plan" that restricts managed database cluster engines to Aurora PostgreSQL only — Neptune isn't available without upgrading the account's billing plan, independent of any code or configuration. CLAUDE.md explicitly allows for this fallback ("if Neptune setup eats too much time, it's acceptable to fall back to a local graph library"), so the graph layer runs on **local `networkx`** instead: same node/edge model (`Trial`/`Condition`/`Intervention`/`Site`, `STUDIES`/`USES`/`CONDUCTED_AT`), same multi-hop traversal, zero AWS cost — at the cost of not demonstrating an actual managed graph database.

### How the local graph is modeled

`scripts/02_build_graph.py` builds an in-memory `networkx.MultiDiGraph` from `trials.json` and pickles it to `data/processed/graph.gpickle`:

- **Trial nodes** are keyed by NCT ID, with `title`, `brief_summary`, and `eligibility_criteria` stored as node *attributes* — eligibility text is a property of the trial, not a separate relationship, which is what lets `get_trial_relationships` return it directly in one lookup (see the "lesson learned" section above).
- **Condition and Intervention nodes** are keyed by their name string itself (e.g. `"Diabetes Mellitus, Type 2"`). Because networkx no-ops on `add_node` for an ID that already exists, two different trials that mention the same condition/drug automatically share one node — this is what turns 25 independent trials into a connected graph rather than 25 disconnected trees.
- **Site nodes** are keyed by `facility|city`, not facility name alone — ClinicalTrials.gov trials sponsored by the same company often reuse a generic facility label (e.g. `"Novo Nordisk Investigational Site"`) across dozens of physically different locations, so facility name alone would have wrongly merged unrelated sites into one node.
- **Edges** always point out from the Trial (`Trial -[STUDIES]-> Condition`, etc.), with the relation type stored as an edge attribute.
- Everything is queried in Python: `find_trials_by_intervention` filters nodes by `kind == "Intervention"` and walks `GRAPH.predecessors(...)`, `get_trial_relationships` walks `GRAPH.out_edges(nct_id, data=True)` and buckets by `relation`. There's no query planner or index — every access pattern is a hand-written traversal function.

### What would be different with Neptune

| | networkx (this project) | Neptune Database Serverless (original design) |
|---|---|---|
| Storage | In-process Python object, pickled to a local file | Managed, network-accessible graph database cluster |
| Query language | Hand-written Python traversal functions (`out_edges`, `predecessors`) | Declarative **openCypher**: `MATCH (t:Trial)-[:USES]->(i:Intervention {name: $name}) RETURN t` |
| Access from Lambda | The whole graph file must be *bundled inside the Lambda deployment package* — why `lambda/graph_query/handler.py` loads `graph.gpickle` from disk at cold start | Lambda would make an HTTPS `/openCypher` call over the network — no data bundling, and any client can query the same live graph |
| Updates | Regenerate the pickle and redeploy the Lambda package | Write directly to the live graph; no redeploy needed |
| Site node collisions | Had to encode disambiguating info (`facility|city`) into the node's *identity* itself, since there's no query-time property filtering | Sites could stay identified by facility name alone as a property, with a query like `MATCH (s:Site {facility: $name, city: $city})` — collisions become a query concern, not an identity-modeling one |
| Scale | Fine for ~300 nodes; degrades linearly with Python object size | Built for millions of nodes/edges with real query optimization and indexing |
| Durability | The pickle file *is* the entire durability story — no backups, no point-in-time recovery | Automated backups, point-in-time recovery, Multi-AZ durability |
| Cost | Zero | ~$0.11/hr minimum (1 NCU floor), capped at 2.5 NCU max |

The actual query *behavior* would be identical either way — `find_trials_by_intervention`, `find_trials_sharing_site`, and `get_trial_relationships` were designed to mirror what an openCypher query would do. The real difference is architectural: Neptune turns the graph into a shared, queryable service other systems can plug into, while `networkx` makes it a private, in-memory structure that only exists inside whatever process loads the pickle file.

## Why not a managed Bedrock Agent

The original design also called for orchestration via a **Bedrock Agent** with two Action Groups. Building that surfaced two more account-level restrictions, both unrelated to the Neptune issue above:

1. **Bedrock Agents (Classic) is in account-wide maintenance mode.** `create-agent` failed with `AccessDeniedException: Bedrock Agents is in Maintenance Mode. New agent creation is not available for accounts without prior service usage.` AWS stopped accepting new customers into the classic Agents service on 2026-07-30 — an account-history cutoff with no exception process, not a billing-plan issue. (The successor, Bedrock AgentCore, was out of scope for a one-day build.)
2. **A separate, one-time Anthropic "use case details" requirement.** Even direct `invoke-model` calls to any Anthropic model failed with `ResourceNotFoundException: Model use case details have not been submitted for this account` until the form was submitted once via the Bedrock console (Model catalog → any Claude model). This is unrelated to model access grants — it's a one-time Anthropic policy gate that applies account-wide.

Rather than drop the Action Group architecture, the two Lambda functions were built and deployed exactly as a Bedrock Agent would have used them (`clinical-graphrag-graph-query`, `clinical-graphrag-vector-search`), and `scripts/05_test_agent.py` drives them with a local tool-calling loop against Claude Haiku 4.5's native tool-use (Bedrock Converse API) instead of a managed Agent resource. The Lambda/Action-Group layer is real; only the managed orchestrator is swapped for a script.

## Lesson learned: graph lookup beats vector search for known entities

`get_trial_relationships` originally didn't return a trial's `eligibility_criteria`, even though the graph node stores it — so the agent fell back to `vector_search` (a corpus-wide semantic search) to answer "what does trial X's eligibility say about Y", which frequently missed because vector search can't filter to a specific NCT ID. Adding `eligibility_criteria` to the graph lookup's response, and telling the agent (via its system prompt) to prefer the graph once it has an NCT ID, fixed this — a small but real demonstration of the core GraphRAG thesis: exact/structured lookup beats semantic search whenever you already know which entity you're asking about.

## What I'd do differently at production scale

- **Vector store**: local FAISS works for 25 documents; a production system would use a managed vector store — Bedrock Knowledge Bases with a properly-sized OpenSearch Serverless collection (not the "Classic" collection type, which bills 24/7 even idle).
- **Graph**: Neptune Database Serverless as originally designed, with the account's billing plan upgraded ahead of time — or Neptune Analytics if the workload grows to need heavier graph algorithms beyond simple traversal.
- **Orchestration**: Bedrock AgentCore instead of a hand-rolled tool-calling loop, once account access allows it — it adds production-grade policy controls, memory, and observability beyond what a script or even a classic Bedrock Agent provides.
- **Knowledge extraction**: AWS Context (or an equivalent LLM-driven graph extraction step) to auto-infer relationships from unstructured trial text, instead of hand-modeling a fixed schema — this scales better as the entity/relationship vocabulary grows beyond Trial/Condition/Intervention/Site.
- **Retrieval quality**: chunking eligibility criteria into inclusion/exclusion sub-sections rather than embedding a trial's full text as one document, and filtering vector search to a specific NCT ID when the graph has already identified the trial (the exact gap the "lesson learned" section above found and fixed for the graph path — vector search should get the same filtering capability at scale).
