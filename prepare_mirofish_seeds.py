"""
prepare_mirofish_seeds.py
=========================
Converts synthetic CSV data from generate_rfq_data.py into narrative
seed documents for MiroFish. Run this AFTER generate_rfq_data.py.

Output: ./mirofish_seeds/
  scenario_1_vendor_presim.md   — vendor behavior pre-simulation
  scenario_6_supply_shock.md    — supply chain shock stress test
  scenario_7_new_vendor.md      — new vendor synthetic due diligence

Usage:
  python3 prepare_mirofish_seeds.py

Then upload each .md file to MiroFish at http://localhost:3000
"""

import pandas as pd, os
from datetime import datetime

DATA_DIR = "./output"       # output from generate_rfq_data.py
SEED_DIR = "./mirofish_seeds"
os.makedirs(SEED_DIR, exist_ok=True)

vendors  = pd.read_csv(f"{DATA_DIR}/01_vendors.csv")
perf     = pd.read_csv(f"{DATA_DIR}/02_vendor_performance.csv")
comms    = pd.read_csv(f"{DATA_DIR}/03_commodity_prices.csv")
signals  = pd.read_csv(f"{DATA_DIR}/04_market_signals.csv")
bids     = pd.read_csv(f"{DATA_DIR}/12_bids.csv")
evals    = pd.read_csv(f"{DATA_DIR}/13_bid_evaluation.csv")
personas = pd.read_csv(f"{DATA_DIR}/17_mirofish_agent_personas.csv")
events   = pd.read_csv(f"{DATA_DIR}/18_mirofish_world_events.csv")


# ── Scenario 1: Vendor Pre-Simulation ────────────────────────────────────────
def build_scenario_1():
    lines = [
        "# Meridian Industrial Systems — Vendor Procurement Intelligence Report",
        f"*Generated: {datetime.now().strftime('%B %Y')}*\n",
        "## Executive Summary",
        "Meridian Industrial Systems (MIS) is a Bangalore-based manufacturer of "
        "CNC machines and robotic assembly cells. This report profiles the active "
        "vendor ecosystem for Mechanical Parts, Electrical Components, and Raw "
        "Materials procurement. Meridian issues approximately 180 RFQs per year "
        "across 24 active vendors in 3 categories.\n",
        "## Vendor Profiles\n",
    ]

    for _, v in vendors[vendors["is_new_vendor"] == False].iterrows():
        vp      = perf[perf["vendor_id"] == v["vendor_id"]].tail(3)
        avg_otd = vp["on_time_delivery_rate"].mean() if len(vp) else v["base_otd_rate"]
        avg_pi  = vp["price_index"].mean()           if len(vp) else v["base_price_index"]
        avg_rr  = vp["response_rate"].mean()         if len(vp) else v["base_response_rate"]
        avg_qs  = vp["quality_score"].mean()         if len(vp) else v["base_quality_score"]

        lines.append(f"### {v['vendor_name']} ({v['country']}, {v['city']})")
        lines.append(
            f"Category: {v['category']}. Relationship: {v['relationship_years']} years. "
            f"Behavioural profile: {v['behavioral_archetype'].replace('_',' ')}. "
            f"Risk tier: {v['risk_tier']}. Certifications: {v['certifications']}. "
            f"Recent on-time delivery: {avg_otd:.0%}. "
            f"Recent response rate to RFQs: {avg_rr:.0%}. "
            f"Recent quality score: {avg_qs:.1f}/10. "
            f"Price index vs market: {avg_pi:.3f} "
            f"({'below' if avg_pi < 1.0 else 'above'} market average). "
            f"Financial health: {v['financial_health_score']}/10. "
            f"Payment preference: {v['preferred_payment_terms']}. "
            f"Past disputes: {v.get('past_disputes', 0)}.\n"
        )

    lines += [
        "## Market Signals (last 18 months)\n",
        "The following events are affecting vendor behaviour and bid pricing:\n",
    ]
    for _, s in signals.iterrows():
        lines.append(
            f"- **{s['date']}** | {s['signal_type']} | Source: {s['source']}\n"
            f"  {s['full_text']}\n"
            f"  Affected commodities: {s['affected_commodities'] or 'general'}. "
            f"  Sentiment: {s['sentiment_score']:+.1f}. "
            f"  Cascade potential: {s['cascade_potential']:.0%}.\n"
        )

    # Add commodity trend summary
    lines += ["\n## Commodity Price Trends\n"]
    for comm in comms["commodity"].unique():
        c_data = comms[comms["commodity"] == comm]
        first_price = c_data.iloc[0]["price"]
        last_price  = c_data.iloc[-1]["price"]
        change_pct  = (last_price - first_price) / first_price * 100
        shock_weeks = c_data["shock_flag"].sum()
        lines.append(
            f"- **{comm}**: {first_price:.2f} → {last_price:.2f} "
            f"({change_pct:+.1f}% over 18 months). "
            f"Shock-affected weeks: {shock_weeks}."
        )

    lines += [
        "\n## Prediction Requirement",
        "Given the vendor profiles, relationship history, recent performance trends, "
        "and current market signals above, predict for the next Meridian Industrial "
        "Systems RFQ in the Mechanical Parts category:",
        "1. Which vendors are most likely to respond to the RFQ invite (probability 0–1)?",
        "2. What price band will each responding vendor bid at, relative to the market index?",
        "3. What lead time will each vendor commit to (in calendar days)?",
        "4. Which vendors show signs of capacity stress, price volatility, or dropout risk?",
        "5. Which vendors are currently best positioned to win the business and why?",
    ]

    path = f"{SEED_DIR}/scenario_1_vendor_presim.md"
    with open(path, "w") as f:
        f.write("\n".join(lines))
    size = os.path.getsize(path)
    print(f"  ✓ scenario_1_vendor_presim.md  ({size:,} bytes)")


# ── Scenario 6: Supply Shock Stress Test ─────────────────────────────────────
def build_scenario_6():
    shock_events = events[events["scenario"] == "scenario_6"].copy()
    shock_comms  = comms[comms["shock_flag"] == 1].groupby("commodity").tail(6)
    shortlisted  = evals[evals["selected"] == True].drop_duplicates("vendor_id").head(5)

    lines = [
        "# Meridian Industrial Systems — Supply Chain Disruption Risk Assessment",
        f"*Classified: Procurement Stress Test — {datetime.now().strftime('%B %Y')}*\n",
        "## Situation",
        "Meridian Industrial Systems has completed an RFQ evaluation and shortlisted "
        "5 vendors for a Mechanical Parts purchase order. Before purchase orders are "
        "issued, the Chief Procurement Officer has requested a stress test of each "
        "vendor's resilience against the following active and concurrent supply chain "
        "disruptions.\n",
        "## Active Disruption Events\n",
    ]

    for _, e in shock_events.iterrows():
        lines.append(f"### {e['event_type'].replace('_',' ').title()}")
        lines.append(
            f"**Date**: {e['event_date']}  \n"
            f"**Severity**: {e['severity_1_10']}/10  \n"
            f"**Description**: {e['description']}  \n"
            f"**Affected roles**: {e['affected_agent_roles']}  \n"
            f"**Expected market impact**: {e['expected_market_impact']}  \n"
            f"**Mitigation options**: "
            f"{e['mitigation_option_1']} OR {e['mitigation_option_2']}\n"
        )

    lines += ["\n## Shock-Affected Commodity Prices\n"]
    for _, r in shock_comms.iterrows():
        lines.append(
            f"- **{r['commodity']}** ({r['unit']}): "
            f"Price {r['price']:.2f} as of week {r['week_start']}. "
            f"Currently in shock-affected period."
        )

    lines += ["\n## The 5 Shortlisted Vendors\n",
        "These vendors have already submitted bids and been ranked. "
        "They must now be evaluated for supply-chain resilience:\n"]

    for _, ev in shortlisted.iterrows():
        v_rows = vendors[vendors["vendor_id"] == ev["vendor_id"]]
        if v_rows.empty:
            continue
        v  = v_rows.iloc[0]
        vp = perf[perf["vendor_id"] == v["vendor_id"]].tail(6)
        avg_otd = vp["on_time_delivery_rate"].mean() if len(vp) else v["base_otd_rate"]
        avg_pi  = vp["price_index"].mean()           if len(vp) else v["base_price_index"]

        lines.append(
            f"### {v['vendor_name']} ({v['country']}, {v['city']})\n"
            f"Category: {v['category']}. "
            f"Behavioural archetype: {v['behavioral_archetype'].replace('_',' ')}. "
            f"Risk tier: {v['risk_tier']}. "
            f"Capacity utilisation: {v['capacity_utilization_pct']}%. "
            f"Financial health: {v['financial_health_score']}/10. "
            f"Recent OTD: {avg_otd:.0%}. "
            f"Recent price index: {avg_pi:.3f}. "
            f"Bid composite score: {ev['composite_score']}.\n"
        )

    lines += [
        "\n## Prediction Requirement",
        "Under the combined active disruptions listed above, for each shortlisted vendor predict:",
        "1. **Resilience score** (0–1): Can this vendor absorb the shocks and fulfil the PO?",
        "2. **Price revision %**: By how much will they revise their quoted price upward?",
        "3. **Lead time extension**: How many additional days will they need?",
        "4. **Dropout probability**: Likelihood they cannot fulfil the order at all.",
        "5. **Most likely mitigation**: Which option will they invoke (from the list above)?",
        "6. **Recommendation**: Should Meridian proceed with this vendor, seek alternatives, "
        "   or negotiate different terms?",
    ]

    path = f"{SEED_DIR}/scenario_6_supply_shock.md"
    with open(path, "w") as f:
        f.write("\n".join(lines))
    size = os.path.getsize(path)
    print(f"  ✓ scenario_6_supply_shock.md   ({size:,} bytes)")


# ── Scenario 7: New Vendor Synthetic Due Diligence ────────────────────────────
def build_scenario_7():
    new_vendors   = vendors[vendors["is_new_vendor"] == True].copy()
    known_vendors = vendors[vendors["is_new_vendor"] == False].copy()

    lines = [
        "# Meridian Industrial Systems — New Vendor Onboarding Due Diligence",
        f"*Procurement Risk Assessment — {datetime.now().strftime('%B %Y')}*\n",
        "## Background",
        "Meridian Industrial Systems is evaluating four new vendor candidates who "
        "have expressed interest in joining the approved vendor list. None of these "
        "vendors have prior transaction history with Meridian. To assess their likely "
        "bid behaviour and reliability, each candidate is paired with two established "
        "Meridian vendors whose category, geography, and company profile are most "
        "analogous. The analog vendors' 18-month performance records are provided as "
        "the behavioral prior.\n",
    ]

    for _, nv in new_vendors.iterrows():
        lines.append(f"## New Vendor Candidate: {nv['vendor_name']}")
        lines.append(
            f"**Country**: {nv['country']}, {nv['city']}  \n"
            f"**Category**: {nv['category']}  \n"
            f"**Onboarded into evaluation**: {nv['onboarded_date']}  \n"
            f"**Risk tier (initial assessment)**: {nv['risk_tier']}  \n"
            f"**Financial health**: {nv['financial_health_score']}/10  \n"
            f"**Certifications**: {nv['certifications']}  \n"
            f"**Payment preference**: {nv['preferred_payment_terms']}  \n"
            f"**Transaction history with Meridian**: None — first engagement.\n"
        )

        # 2 analog vendors: same category, established, low/medium risk
        analogs = known_vendors[
            (known_vendors["category"] == nv["category"]) &
            (known_vendors["risk_tier"].isin(["low", "medium"]))
        ].head(2)

        if analogs.empty:
            analogs = known_vendors[known_vendors["category"] == nv["category"]].head(2)

        lines.append(f"### Analog Vendor Profiles for {nv['vendor_name']}\n")

        for _, av in analogs.iterrows():
            ap      = perf[perf["vendor_id"] == av["vendor_id"]].tail(6)
            avg_otd = ap["on_time_delivery_rate"].mean() if len(ap) else av["base_otd_rate"]
            avg_pi  = ap["price_index"].mean()           if len(ap) else av["base_price_index"]
            avg_rr  = ap["response_rate"].mean()         if len(ap) else av["base_response_rate"]
            avg_qs  = ap["quality_score"].mean()         if len(ap) else av["base_quality_score"]

            # Their bid history
            av_bids = bids[bids["vendor_id"] == av["vendor_id"]].tail(5)
            avg_delta = av_bids["price_delta_pct"].mean() if len(av_bids) else 0

            lines.append(
                f"**{av['vendor_name']}** ({av['country']}) — selected as analog for "
                f"similar category, region, and risk profile.\n"
                f"- Behavioural archetype: {av['behavioral_archetype'].replace('_',' ')}\n"
                f"- Relationship with Meridian: {av['relationship_years']} years\n"
                f"- On-time delivery (6-month avg): {avg_otd:.0%}\n"
                f"- RFQ response rate: {avg_rr:.0%}\n"
                f"- Quality score: {avg_qs:.1f}/10\n"
                f"- Price index vs market: {avg_pi:.3f}\n"
                f"- Average bid delta vs target: {avg_delta:+.1f}%\n"
                f"- Financial health: {av['financial_health_score']}/10\n"
                f"- Risk tier: {av['risk_tier']}\n"
                f"- Certifications: {av['certifications']}\n"
            )

        lines.append("---\n")

    lines += [
        "\n## Prediction Requirement",
        "For each new vendor candidate above, using the behavioral profiles of their "
        "paired analog vendors as the prior, construct a synthetic behavioral model and predict:",
        "1. **Response probability**: Likelihood they will respond to a first RFQ invite (0–1)",
        "2. **Expected bid vs market**: Estimated price index relative to market (e.g. 0.95 = 5% below)",
        "3. **Lead time**: Expected commitment in calendar days",
        "4. **Synthetic trust score** (0–1): Predicted reliability based on analog profiles",
        "5. **Onboarding risk rating**: low / medium / high",
        "6. **Maximum trial PO value** (USD): Recommended spend ceiling for first engagement",
        "7. **Conditions for full approval**: What would this vendor need to demonstrate to become "
        "   a Tier-1 approved vendor at Meridian?",
    ]

    path = f"{SEED_DIR}/scenario_7_new_vendor.md"
    with open(path, "w") as f:
        f.write("\n".join(lines))
    size = os.path.getsize(path)
    print(f"  ✓ scenario_7_new_vendor.md     ({size:,} bytes)")


# ── Run all ───────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"\nMiroFish Seed Document Generator")
    print(f"Data source: {os.path.abspath(DATA_DIR)}")
    print(f"Output:      {os.path.abspath(SEED_DIR)}\n")
    build_scenario_1()
    build_scenario_6()
    build_scenario_7()
    print(f"\nUpload each .md file to MiroFish at http://localhost:3000")
    print("See MIROFISH_RUN_GUIDE.md for step-by-step instructions per scenario.")
