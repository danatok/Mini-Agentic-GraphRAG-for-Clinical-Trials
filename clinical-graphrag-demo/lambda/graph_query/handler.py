"""Bedrock Agent Action Group Lambda: graph_query.

Loads a pre-built networkx graph (graph.gpickle, bundled in the deployment
package) and answers relationship questions over Trial/Condition/Intervention/
Site nodes. Runs entirely locally inside the Lambda — no external calls,
no cost beyond the Lambda invocation itself.
"""
import json
import pickle

import networkx as nx

with open("graph.gpickle", "rb") as f:
    GRAPH: nx.MultiDiGraph = pickle.load(f)


def _trial_summary(nct_id: str) -> dict:
    data = GRAPH.nodes[nct_id]
    return {"nct_id": nct_id, "title": data.get("title", "")}


def find_trials_by_intervention(intervention_name: str) -> dict:
    matches = [
        n for n, d in GRAPH.nodes(data=True)
        if d.get("kind") == "Intervention" and n.lower() == intervention_name.lower()
    ]
    if not matches:
        matches = [
            n for n, d in GRAPH.nodes(data=True)
            if d.get("kind") == "Intervention" and intervention_name.lower() in n.lower()
        ]
    if not matches:
        return {"intervention": intervention_name, "trials": []}

    trials = []
    for intervention_node in matches:
        for trial_id in GRAPH.predecessors(intervention_node):
            if GRAPH.nodes[trial_id].get("kind") == "Trial":
                trials.append(_trial_summary(trial_id))
    return {"intervention": intervention_name, "trials": trials}


def find_trials_sharing_site(nct_id: str) -> dict:
    if nct_id not in GRAPH or GRAPH.nodes[nct_id].get("kind") != "Trial":
        return {"nct_id": nct_id, "error": "trial not found", "shared_trials": []}

    sites = [
        target for _, target, data in GRAPH.out_edges(nct_id, data=True)
        if data.get("relation") == "CONDUCTED_AT"
    ]

    shared_trials = {}
    for site in sites:
        for other_trial in GRAPH.predecessors(site):
            if other_trial != nct_id and GRAPH.nodes[other_trial].get("kind") == "Trial":
                shared_trials.setdefault(other_trial, set()).add(GRAPH.nodes[site].get("facility", site))

    return {
        "nct_id": nct_id,
        "shared_trials": [
            {**_trial_summary(t), "shared_sites": sorted(sites_)}
            for t, sites_ in shared_trials.items()
        ],
    }


def get_trial_relationships(nct_id: str) -> dict:
    if nct_id not in GRAPH or GRAPH.nodes[nct_id].get("kind") != "Trial":
        return {"nct_id": nct_id, "error": "trial not found"}

    conditions, interventions, sites = [], [], []
    for _, target, data in GRAPH.out_edges(nct_id, data=True):
        relation = data.get("relation")
        target_data = GRAPH.nodes[target]
        if relation == "STUDIES":
            conditions.append(target)
        elif relation == "USES":
            interventions.append(target)
        elif relation == "CONDUCTED_AT":
            sites.append(target_data.get("facility", target))

    unique_sites = sorted(set(sites))
    trial_data = GRAPH.nodes[nct_id]
    return {
        "nct_id": nct_id,
        "title": trial_data.get("title", ""),
        "eligibility_criteria": trial_data.get("eligibility_criteria", ""),
        "conditions": conditions,
        "interventions": interventions,
        "site_count": len(unique_sites),
        "sites": unique_sites[:10],
    }


FUNCTIONS = {
    "find_trials_by_intervention": find_trials_by_intervention,
    "find_trials_sharing_site": find_trials_sharing_site,
    "get_trial_relationships": get_trial_relationships,
}


def lambda_handler(event, context):
    action_group = event.get("actionGroup", "graph_query")
    function = event.get("function")
    params = {p["name"]: p["value"] for p in event.get("parameters", [])}

    handler_fn = FUNCTIONS.get(function)
    if handler_fn is None:
        result = {"error": f"unknown function: {function}"}
    else:
        try:
            result = handler_fn(**params)
        except TypeError as e:
            result = {"error": f"bad parameters for {function}: {e}"}

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
