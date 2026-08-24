"""Build a local networkx graph from trials.json.

Fallback for the Neptune graph layer: this AWS account's plan blocks the
Neptune engine type (FreeTierRestrictionError), so the graph runs locally
via networkx instead of Neptune Database Serverless — see README for the
architecture note. Zero AWS cost, same node/edge model CLAUDE.md specifies.

Nodes: Trial, Condition, Intervention, Site (typed via a "kind" attribute)
Edges: (Trial)-[STUDIES]->(Condition)
       (Trial)-[USES]->(Intervention)
       (Trial)-[CONDUCTED_AT]->(Site)
"""
import json
import pickle
from pathlib import Path

import networkx as nx

ROOT = Path(__file__).resolve().parent.parent
TRIALS_PATH = ROOT / "data" / "processed" / "trials.json"
GRAPH_PATH = ROOT / "data" / "processed" / "graph.gpickle"


def site_key(site: dict) -> str:
    return f"{site.get('facility')}|{site.get('city') or ''}"


def build_graph(trials: list[dict]) -> nx.MultiDiGraph:
    g = nx.MultiDiGraph()

    for trial in trials:
        nct_id = trial.get("nct_id")
        if not nct_id:
            continue

        g.add_node(
            nct_id,
            kind="Trial",
            title=trial.get("title") or "",
            brief_summary=trial.get("brief_summary") or "",
            eligibility_criteria=trial.get("eligibility_criteria") or "",
        )

        for condition in trial.get("conditions", []):
            if not condition:
                continue
            g.add_node(condition, kind="Condition")
            g.add_edge(nct_id, condition, relation="STUDIES")

        for intervention in trial.get("interventions", []):
            name = intervention.get("name")
            if not name:
                continue
            g.add_node(name, kind="Intervention", type=intervention.get("type") or "UNKNOWN")
            g.add_edge(nct_id, name, relation="USES")

        for site in trial.get("sites", []):
            facility = site.get("facility")
            if not facility:
                continue
            key = site_key(site)
            g.add_node(
                key,
                kind="Site",
                facility=facility,
                city=site.get("city") or "",
                state=site.get("state") or "",
                country=site.get("country") or "",
            )
            g.add_edge(nct_id, key, relation="CONDUCTED_AT")

    return g


def main() -> None:
    trials = json.loads(TRIALS_PATH.read_text())
    print(f"Building graph from {len(trials)} trials")

    g = build_graph(trials)

    GRAPH_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(GRAPH_PATH, "wb") as f:
        pickle.dump(g, f)
    print(f"Wrote graph to {GRAPH_PATH}")

    kinds: dict[str, int] = {}
    for _, data in g.nodes(data=True):
        kinds[data["kind"]] = kinds.get(data["kind"], 0) + 1
    print("\nNode counts:")
    for kind, count in sorted(kinds.items()):
        print(f"  {kind}: {count}")
    print(f"\nTotal edges: {g.number_of_edges()}")


if __name__ == "__main__":
    main()
