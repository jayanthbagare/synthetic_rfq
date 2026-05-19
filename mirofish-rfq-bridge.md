---
name: mirofish-rfq-bridge
description: >
  Runs MiroFish swarm intelligence simulations as a decision-support layer for
  the Hermes RFQ pipeline. Handles all three RFQ scenarios: (1) vendor behavior
  pre-simulation before invites, (6) supply shock stress-testing after shortlist,
  (7) new vendor synthetic due diligence. Activate when orchestrator requests a
  MiroFish run, or when user says "run MiroFish", "simulate vendors", "stress test
  shortlist", "new vendor profile", or "/mirofish {scenario} {rfq_id}".
version: 1.0.0
author: meridian-procurement
platforms: [linux, macos]
requires_toolsets: [shell, web]
required_environment_variables:
  - MERIDIAN_SHEETS_BID_LOG_ID
  - MERIDIAN_VENDOR_SHEET_ID
  - MERIDIAN_DRIVE_FOLDER_ID
  - MIROFISH_BASE_URL
tags: [mirofish, simulation, procurement, rfq, meridian]
category: Productivity
telegram_triggers:
  - "/mirofish"
  - "run MiroFish"
  - "simulate vendors"
  - "stress test"
  - "new vendor profile"
---

## Role

You are the **MiroFish Integration Bridge** for Meridian Industrial Systems.
You prepare seed data from the Hermes data layer, submit it to MiroFish,
poll for completion, retrieve predictions, and write results back to Sheets
for the other RFQ skills to consume.

MiroFish base URL: `$MIROFISH_BASE_URL` (e.g. `http://localhost:5001` if
self-hosted via Docker; or the remote URL if deployed).

---

## Scenario dispatch

Detect which scenario to run from the trigger:

```python
SCENARIO_MAP = {
    "scenario_1": run_scenario_1_vendor_presim,
    "scenario_6": run_scenario_6_supply_shock,
    "scenario_7": run_scenario_7_new_vendor,
    "1": run_scenario_1_vendor_presim,
    "6": run_scenario_6_supply_shock,
    "7": run_scenario_7_new_vendor,
}

handler = SCENARIO_MAP.get(scenario_arg)
if not handler:
    send_telegram(
        "⚠️ Unknown MiroFish scenario. Use:\n"
        "`/mirofish 1 {rfq_id}` — vendor pre-simulation\n"
        "`/mirofish 6 {rfq_id}` — supply shock stress test\n"
        "`/mirofish 7 {vendor_id}` — new vendor onboarding"
    )
    return
```

---

## Scenario 1 — Vendor behavior pre-simulation

**Purpose**: Before sending real RFQs, predict which vendors will respond
and at what price band.

**When**: Orchestrator Phase 1, before email dispatch.

```python
def run_scenario_1_vendor_presim(rfq_id, work_order_id):
    send_telegram(f"🔮 MiroFish Scenario 1: Vendor pre-simulation starting for RFQ {rfq_id}…")

    # 1. Load vendor master + performance snapshots from Drive CSVs
    vendor_data    = load_csv_from_drive("01_vendors.csv")
    perf_data      = load_csv_from_drive("02_vendor_performance.csv")
    market_signals = load_csv_from_drive("04_market_signals.csv")
    commodity_px   = load_csv_from_drive("03_commodity_prices.csv")
    sim_config     = load_csv_from_drive("19_mirofish_sim_runs.csv")
    personas       = load_csv_from_drive("17_mirofish_agent_personas.csv")

    # 2. Filter to invited vendors for this RFQ
    invited = get_invited_vendors(rfq_id)  # from Sheets
    invited_ids = [v["vendor_id"] for v in invited]

    # Filter personas and performance to invited set
    relevant_vendors  = [v for v in vendor_data if v["vendor_id"] in invited_ids]
    relevant_perf     = [p for p in perf_data   if p["vendor_id"] in invited_ids]
    relevant_personas = [p for p in personas    if p["bound_vendor_id"] in invited_ids]

    # 3. Prepare MiroFish seed payload
    seed_payload = {
        "world_name":   f"RFQ-{rfq_id}-Scenario1",
        "description":  f"Predict vendor bid behavior for Meridian RFQ {rfq_id}",
        "seed_materials": [
            {
                "type": "structured_data",
                "label": "vendor_master",
                "content": csv_to_text(relevant_vendors)
            },
            {
                "type": "structured_data",
                "label": "vendor_performance_18mo",
                "content": csv_to_text(relevant_perf)
            },
            {
                "type": "news_signals",
                "label": "market_context",
                "content": csv_to_text(market_signals[-6:])  # last 6 signals
            },
        ],
        "agent_configs": [
            {
                "agent_id":        p["agent_id"],
                "role":            p["role"],
                "persona_summary": p["persona_summary"],
                "decision_style":  p["decision_style"],
                "memory_seeds":    [p["memory_seed_1"], p["memory_seed_2"], p["memory_seed_3"]],
                "behavioral_rules":[p["behavioral_rule_1"], p["behavioral_rule_2"], p["behavioral_rule_3"]],
            }
            for p in relevant_personas
        ],
        "simulation_rounds":  30,
        "prediction_question": (
            f"Of the {len(invited_ids)} vendors invited for RFQ {rfq_id} "
            f"({work_order_id}, category {category}), predict for each: "
            f"(1) probability of submitting a bid, "
            f"(2) expected bid price range vs market index, "
            f"(3) expected lead time commitment."
        ),
        "output_format": "per_agent_predictions"
    }

    # 4. Submit to MiroFish
    sim_id = submit_to_mirofish(seed_payload)

    # 5. Poll for completion (max 15 min)
    predictions = poll_mirofish(sim_id, timeout_minutes=15)

    # 6. Parse and write predictions to Sheets
    rows = []
    for pred in predictions:
        rows.append([
            rfq_id, work_order_id, pred["vendor_id"],
            "scenario_1",
            pred.get("response_probability", 0),
            pred.get("bid_range_low_usd", 0),
            pred.get("bid_range_high_usd", 0),
            pred.get("predicted_delivery_days", 0),
            pred.get("prediction_confidence", 0),
            datetime.now().isoformat()
        ])

    subprocess.run([
        "gws", "sheets", "append",
        "--sheet-id", os.environ["MERIDIAN_SHEETS_BID_LOG_ID"],
        "--range", "MiroFishPredictions!A:J",
        "--values", json.dumps(rows)
    ])

    # 7. Telegram summary
    top_responders = sorted(predictions, key=lambda x: x.get("response_probability",0), reverse=True)[:5]
    summary = "\n".join([
        f"  {p['vendor_name']}: {p['response_probability']*100:.0f}% response prob, "
        f"${p.get('bid_range_low_usd',0):,.0f}–${p.get('bid_range_high_usd',0):,.0f}"
        for p in top_responders
    ])
    send_telegram(
        f"✅ MiroFish Scenario 1 complete.\n\n"
        f"*Top predicted responders:*\n{summary}\n\n"
        f"_Predictions written to Sheets. Vendor selector will use these to refine invite list._"
    )

    return predictions
```

---

## Scenario 6 — Supply shock stress test

**Purpose**: After shortlist is set, stress-test the 5 selected vendors
under active market shock scenarios (port disruption, tariff spike,
rare earth shortage).

**When**: Orchestrator Phase 4–5, after evaluation and before PO issuance.

```python
def run_scenario_6_supply_shock(rfq_id):
    send_telegram(f"⚡ MiroFish Scenario 6: Supply shock stress test for RFQ {rfq_id}…")

    shortlist  = get_shortlisted_vendors(rfq_id)   # 5 vendors
    world_evts = load_csv_from_drive("18_mirofish_world_events.csv")
    market_sig = load_csv_from_drive("04_market_signals.csv")
    comm_px    = load_csv_from_drive("03_commodity_prices.csv")
    personas   = load_csv_from_drive("17_mirofish_agent_personas.csv")

    # Active shocks: filter world events with high severity and cascade_potential
    active_shocks = [e for e in world_evts
                     if int(e["severity_1_10"]) >= 7
                     and "scenario_6" in e["scenario"]]

    shortlist_ids = [v["vendor_id"] for v in shortlist]
    relevant_personas = [p for p in personas if p["bound_vendor_id"] in shortlist_ids
                         or p["role"] in ("market_agent","regulator_agent","buyer_agent")]

    seed_payload = {
        "world_name":   f"RFQ-{rfq_id}-Scenario6",
        "description":  "Supply chain shock stress test on RFQ shortlisted vendors",
        "seed_materials": [
            {"type": "structured_data", "label": "shortlisted_vendors",
             "content": csv_to_text(shortlist)},
            {"type": "news_signals",    "label": "active_market_signals",
             "content": csv_to_text(market_sig)},
            {"type": "price_data",      "label": "commodity_prices_18mo",
             "content": csv_to_text(comm_px[-52:])},  # last year of weekly data
        ],
        "agent_configs": [p_to_config(p) for p in relevant_personas],
        "simulation_rounds": 50,
        "injection_events": [
            {
                "round":            int(e["injection_round"]),
                "event_description":e["description"],
                "severity":         int(e["severity_1_10"]),
                "affected_agents":  e["affected_agent_roles"].split("|"),
                "variable_changes": {
                    "price_shock_pct": int(e["severity_1_10"]) * 2,
                    "lead_time_extension_days": int(e["severity_1_10"]) * 3,
                }
            }
            for e in active_shocks
        ],
        "prediction_question": (
            "Under the injected supply chain shocks, for each shortlisted vendor predict: "
            "(1) vendor_resilience_score 0–1, "
            "(2) expected_price_revision_pct (how much they will revise their bid price), "
            "(3) expected_lead_time_extension_days, "
            "(4) dropout_probability (probability they cannot fulfil the PO)."
        ),
        "output_format": "per_agent_resilience_scores"
    }

    sim_id     = submit_to_mirofish(seed_payload)
    predictions = poll_mirofish(sim_id, timeout_minutes=20)

    # Write resilience scores to Sheets
    rows = []
    for pred in predictions:
        rows.append([
            rfq_id, pred["vendor_id"], "scenario_6",
            pred.get("vendor_resilience_score", 0.5),
            pred.get("expected_price_revision_pct", 0),
            pred.get("expected_lead_time_extension_days", 0),
            pred.get("dropout_probability", 0),
            pred.get("expected_market_impact", ""),
            datetime.now().isoformat()
        ])

    subprocess.run([
        "gws", "sheets", "append",
        "--sheet-id", os.environ["MERIDIAN_SHEETS_BID_LOG_ID"],
        "--range", "MiroFishPredictions!A:I",
        "--values", json.dumps(rows)
    ])

    # Alert for any vendors with dropout_probability > 0.30
    at_risk = [p for p in predictions if p.get("dropout_probability",0) > 0.30]
    risk_msg = ""
    if at_risk:
        risk_msg = "\n\n⚠️ *High dropout risk vendors:*\n" + "\n".join([
            f"  {p['vendor_name']}: {p['dropout_probability']*100:.0f}% dropout risk"
            for p in at_risk
        ])

    send_telegram(
        f"✅ MiroFish Scenario 6 complete.{risk_msg}\n\n"
        f"_Resilience scores written to Sheets. Bid evaluator will blend these into final scoring._"
    )

    return predictions
```

---

## Scenario 7 — New vendor synthetic due diligence

**Purpose**: Build a synthetic behavioral profile for a new/unknown vendor
using analog archetype swarm simulation.

**When**: Before `rfq-vendor-selector` includes a new vendor in an invite list.

```python
def run_scenario_7_new_vendor(vendor_id):
    send_telegram(f"🆕 MiroFish Scenario 7: New vendor profiling for {vendor_id}…")

    new_vendor = get_vendor_by_id(vendor_id)
    all_vendors = load_csv_from_drive("01_vendors.csv")
    perf_data   = load_csv_from_drive("02_vendor_performance.csv")
    personas    = load_csv_from_drive("17_mirofish_agent_personas.csv")
    world_evts  = load_csv_from_drive("18_mirofish_world_events.csv")

    # Find 2 analog vendors (same category, similar risk tier, established)
    analogs = [v for v in all_vendors
               if v["category"] == new_vendor["category"]
               and v["is_new_vendor"] == "False"
               and v["risk_tier"] in ("low","medium")][:2]

    analog_perf = [p for p in perf_data if p["vendor_id"] in [a["vendor_id"] for a in analogs]]
    analog_personas = [p for p in personas if p["bound_vendor_id"] in [a["vendor_id"] for a in analogs]]

    seed_payload = {
        "world_name":   f"NewVendor-{vendor_id}-Scenario7",
        "description":  f"Synthetic due diligence for new vendor {new_vendor['vendor_name']}",
        "seed_materials": [
            {"type": "structured_data", "label": "new_vendor_profile",
             "content": csv_to_text([new_vendor])},
            {"type": "structured_data", "label": "analog_vendor_profiles",
             "content": csv_to_text(analogs)},
            {"type": "structured_data", "label": "analog_performance_18mo",
             "content": csv_to_text(analog_perf)},
        ],
        "agent_configs": [p_to_config(p) for p in analog_personas],
        "simulation_rounds": 25,
        "prediction_question": (
            f"Given the behavioral profiles of analog vendors {[a['vendor_name'] for a in analogs]}, "
            f"construct a behavioral prior for new vendor {new_vendor['vendor_name']} and predict: "
            f"(1) synthetic_trust_score 0–1, "
            f"(2) estimated_response_rate 0–1, "
            f"(3) estimated_bid_delta_pct vs market (positive = above market), "
            f"(4) onboarding_risk_rating: low | medium | high, "
            f"(5) recommended_trial_po_value_usd."
        ),
        "output_format": "new_vendor_profile"
    }

    sim_id      = submit_to_mirofish(seed_payload)
    predictions = poll_mirofish(sim_id, timeout_minutes=10)
    p           = predictions[0] if predictions else {}

    # Write synthetic profile to Sheets
    row = [
        vendor_id, new_vendor["vendor_name"], "scenario_7",
        p.get("synthetic_trust_score", 0.5),
        p.get("estimated_response_rate", 0.5),
        p.get("estimated_bid_delta_pct", 0),
        p.get("onboarding_risk_rating", "medium"),
        p.get("recommended_trial_po_value_usd", 10000),
        "|".join([a["vendor_name"] for a in analogs]),
        datetime.now().isoformat()
    ]

    subprocess.run([
        "gws", "sheets", "append",
        "--sheet-id", os.environ["MERIDIAN_SHEETS_BID_LOG_ID"],
        "--range", "MiroFishPredictions!A:J",
        "--values", json.dumps([row])
    ])

    send_telegram(
        f"✅ Scenario 7 complete for *{new_vendor['vendor_name']}*\n\n"
        f"*Synthetic trust score*: {p.get('synthetic_trust_score',0):.2f}\n"
        f"*Est. response rate*: {p.get('estimated_response_rate',0)*100:.0f}%\n"
        f"*Est. bid vs market*: {p.get('estimated_bid_delta_pct',0):+.1f}%\n"
        f"*Onboarding risk*: {p.get('onboarding_risk_rating','medium')}\n"
        f"*Recommended trial PO*: ${p.get('recommended_trial_po_value_usd',10000):,.0f}\n"
        f"*Analog vendors used*: {', '.join(a['vendor_name'] for a in analogs)}"
    )

    return p
```

---

## MiroFish API helpers

```python
import time, requests

MIROFISH_URL = os.environ["MIROFISH_BASE_URL"]

def submit_to_mirofish(payload: dict) -> str:
    """POST seed payload, return simulation_id."""
    resp = requests.post(
        f"{MIROFISH_URL}/api/simulate",
        json=payload,
        timeout=30
    )
    resp.raise_for_status()
    return resp.json()["simulation_id"]

def poll_mirofish(sim_id: str, timeout_minutes: int = 15) -> list:
    """Poll until complete or timeout. Return predictions list."""
    deadline = time.time() + timeout_minutes * 60
    while time.time() < deadline:
        resp = requests.get(f"{MIROFISH_URL}/api/simulate/{sim_id}/status")
        resp.raise_for_status()
        data = resp.json()
        if data["status"] == "complete":
            return data["predictions"]
        elif data["status"] == "failed":
            raise RuntimeError(f"MiroFish simulation {sim_id} failed: {data.get('error')}")
        time.sleep(30)
    raise TimeoutError(f"MiroFish simulation {sim_id} did not complete in {timeout_minutes} min")

def load_csv_from_drive(filename: str) -> list:
    """Load a CSV from the Meridian Drive data folder."""
    result = subprocess.run([
        "gws", "drive", "download",
        "--query", f"name='{filename}' and '{os.environ['MERIDIAN_DRIVE_FOLDER_ID']}' in parents",
        "--format", "json"
    ], capture_output=True, text=True)
    import csv, io
    return list(csv.DictReader(io.StringIO(result.stdout)))

def csv_to_text(rows: list) -> str:
    """Convert list of dicts to CSV string for MiroFish seed."""
    if not rows:
        return ""
    import csv, io
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()

def p_to_config(p: dict) -> dict:
    """Convert a persona row to MiroFish agent_config dict."""
    return {
        "agent_id":        p["agent_id"],
        "role":            p["role"],
        "persona_summary": p["persona_summary"],
        "decision_style":  p["decision_style"],
        "memory_seeds":    [p["memory_seed_1"], p["memory_seed_2"], p["memory_seed_3"]],
        "behavioral_rules":[p["behavioral_rule_1"], p["behavioral_rule_2"], p["behavioral_rule_3"]],
    }
```

## Notes for MiroFish self-hosted setup

```bash
# If running MiroFish locally via Docker:
docker compose up -d
# Set in Hermes config:
hermes config set MIROFISH_BASE_URL http://localhost:5001

# If using remote deployment:
hermes config set MIROFISH_BASE_URL https://your-mirofish-instance.com
```
