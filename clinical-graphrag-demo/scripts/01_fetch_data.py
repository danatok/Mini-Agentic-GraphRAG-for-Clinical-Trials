"""Fetch trials from the ClinicalTrials.gov v2 API and flatten them for downstream use.

Saves raw API responses to data/raw/ and a cleaned, flattened list to
data/processed/trials.json.
"""
import json
import os
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

CONDITION = os.getenv("CONDITION", "type 2 diabetes")
TRIAL_COUNT = int(os.getenv("TRIAL_COUNT", "25"))

API_URL = "https://clinicaltrials.gov/api/v2/studies"

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
PROCESSED_DIR = ROOT / "data" / "processed"


def fetch_studies(condition: str, page_size: int) -> list[dict]:
    params = {
        "query.cond": condition,
        "pageSize": min(page_size, 100),
        "format": "json",
    }
    studies: list[dict] = []
    next_token = None
    while len(studies) < page_size:
        if next_token:
            params["pageToken"] = next_token
        resp = requests.get(API_URL, params=params, timeout=30)
        resp.raise_for_status()
        payload = resp.json()
        studies.extend(payload.get("studies", []))
        next_token = payload.get("nextPageToken")
        if not next_token:
            break
    return studies[:page_size]


def flatten_study(study: dict) -> dict:
    protocol = study.get("protocolSection", {})
    identification = protocol.get("identificationModule", {})
    description = protocol.get("descriptionModule", {})
    conditions_module = protocol.get("conditionsModule", {})
    eligibility = protocol.get("eligibilityModule", {})
    arms_interventions = protocol.get("armsInterventionsModule", {})
    contacts_locations = protocol.get("contactsLocationsModule", {})

    interventions = [
        {"name": i.get("name"), "type": i.get("type")}
        for i in arms_interventions.get("interventions", [])
    ]
    locations = [
        {
            "facility": loc.get("facility"),
            "city": loc.get("city"),
            "state": loc.get("state"),
            "country": loc.get("country"),
        }
        for loc in contacts_locations.get("locations", [])
    ]

    return {
        "nct_id": identification.get("nctId"),
        "title": identification.get("briefTitle"),
        "brief_summary": description.get("briefSummary", ""),
        "eligibility_criteria": eligibility.get("eligibilityCriteria", ""),
        "conditions": conditions_module.get("conditions", []),
        "interventions": interventions,
        "sites": locations,
    }


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Fetching {TRIAL_COUNT} trials for condition: {CONDITION!r}")
    studies = fetch_studies(CONDITION, TRIAL_COUNT)
    print(f"Fetched {len(studies)} studies")

    raw_path = RAW_DIR / "studies.json"
    raw_path.write_text(json.dumps(studies, indent=2))
    print(f"Wrote raw response to {raw_path}")

    flattened = [flatten_study(s) for s in studies]
    processed_path = PROCESSED_DIR / "trials.json"
    processed_path.write_text(json.dumps(flattened, indent=2))
    print(f"Wrote {len(flattened)} flattened trials to {processed_path}")


if __name__ == "__main__":
    main()
