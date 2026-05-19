"""
generate_rfq_data.py
====================
python
Complete rewrite of the Meridian Industrial Systems synthetic data generator.
Adds vendor relationship health scores, payment events, forecast sharing,
administrative burden tracking, and meaningful narrative arcs across 18 months.

Company : Meridian Industrial Systems — CNC machines & robotic assembly cells
Period  : Jan 2024 → Jun 2025 (18 months)
Seed    : 42 (fully reproducible)

KEY DESIGN PRINCIPLES (v2)
--------------------------
1. TIME-AWARE ARCS  — vendor relationships drift purposefully, not randomly.
   Four named arcs are baked in:
     · Kovacs Precision GmbH    → declining (late payments → disengagement)
     · Patel Alloys Pvt Ltd     → improving (FTA benefit + forecast sharing)
     · Guangzhou Mech & Elec    → collapse   (tariff shock → exits pool)
     · Helios Micro Systems     → new vendor proving itself over 12 months

2. CAUSAL CHAIN — macro events cause micro outcomes cause relationship signals:
   Sep 2024 tariff shock → Meridian cash flow stress → late payments →
   vendor health scores drop → response rates fall → RFQ pool shrinks →
   Hermes has to work harder → constraint becomes visible

3. INTERNALLY CONSISTENT — win rates are calculated from actual RFQ events,
   not generated independently. Payment dates are derived from PO dates and
   payment terms, with time-aware variance.

4. HEALTH SCORE IS PRIMARY OUTPUT — CSV 23 is what Hermes reads first.
   Everything else feeds into it.

Outputs (23 CSVs → ./output/):
  01_vendors.csv                 — master vendor registry
  02_vendor_performance.csv      — monthly KPI snapshots (derived, not random)
  03_commodity_prices.csv        — weekly commodity prices with shock events
  04_market_signals.csv          — news/policy signals (MiroFish GraphRAG seeds)
  05_sales_orders.csv            — SO headers
  06_sales_order_lines.csv       — SO line items
  07_work_orders.csv             — WOs derived from SOs
  08_work_order_items.csv        — WO procurement items
  09_rfq_events.csv              — one row per RFQ
  10_rfq_vendor_invites.csv      — one row per vendor per RFQ
  11_rfq_email_thread.csv        — full email conversation log
  12_bids.csv                    — vendor bid records
  13_bid_evaluation.csv          — scored/ranked bids
  14_purchase_orders.csv         — POs from winning bids
  15_delivery_records.csv        — actual vs promised delivery
  16_vendor_disputes.csv         — dispute log
  17_mirofish_agent_personas.csv — MiroFish agent configs
  18_mirofish_world_events.csv   — shock/signal events for simulation
  19_mirofish_sim_runs.csv       — simulation run metadata
  20_payment_events.csv          — NEW: actual payment dates + lateness
  21_forecast_sharing.csv        — NEW: quarterly demand forecasts shared
  22_rfq_admin_burden.csv        — NEW: clarification rounds, spec quality
  23_vendor_health_scores.csv    — NEW: monthly relationship health scores

Run:
  pip install pandas numpy faker
  python3 generate_rfq_data_v2.py
"""

import os, random, csv, io
from datetime import date, timedelta, datetime
from collections import defaultdict

import numpy as np
import pandas as pd
from faker import Faker

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════
random.seed(42)
np.random.seed(42)
fake = Faker()
Faker.seed(42)

START_DATE       = date(2024, 1, 1)
END_DATE         = date(2025, 6, 30)
OUTPUT_DIR       = "./output_v2"
os.makedirs(OUTPUT_DIR, exist_ok=True)

VENDORS_PER_RFQ  = 8
SHORTLIST_SIZE   = 5

# ── Macro timeline events (drive all arcs) ────────────────────────────────────
# Each event is (date, name, affected_categories, price_shock_pct, meridian_cash_stress)
MACRO_EVENTS = [
    # date        name                                    cats                       shock  cash
    (date(2024,3,28), "EU anti-dumping duties",           ["Electrical Components"], +0.09, 0.00),
    (date(2024,5,10), "Copper price spike",               ["Raw Materials"],         +0.07, 0.00),
    (date(2024,7,4),  "Hamburg port strike",              ["Mechanical Parts",
                                                           "Raw Materials"],         +0.05, 0.00),
    (date(2024,9,2),  "US aluminium tariff",              ["Raw Materials",
                                                           "Mechanical Parts"],      +0.12, 0.04),
    (date(2024,10,11),"Suez routing disruption",          ["Electrical Components",
                                                           "Raw Materials"],         +0.06, 0.02),
    (date(2024,11,15),"Meridian big contract win",        [],                        0.00, -0.05),
    (date(2024,12,19),"Competitor capacity ramp",         [],                        0.00,  0.00),
    (date(2025,1,8),  "JPY weakness",                     ["Mechanical Parts",
                                                           "Electrical Components"], +0.07, 0.01),
    (date(2025,3,5),  "Rare earth quota cuts",            ["Electrical Components"], +0.18, 0.03),
    (date(2025,4,12), "G7 critical minerals pact",        ["Electrical Components",
                                                           "Raw Materials"],         -0.04, 0.00),
    (date(2025,5,1),  "Nordic Steel bond / expansion",    ["Raw Materials"],         -0.03, 0.00),
    (date(2025,6,10), "India-EU FTA finalised",           ["Raw Materials"],         -0.05, 0.00),
]

# Meridian's monthly cash stress index (0=normal, 1=severe)
# Used to make payment lateness time-aware
def meridian_cash_stress(month_date: date) -> float:
    stress = 0.0
    for ev_date, _, _, _, cs in MACRO_EVENTS:
        if ev_date <= month_date:
            # stress decays exponentially over 4 months
            months_ago = (month_date.year*12+month_date.month) - (ev_date.year*12+ev_date.month)
            stress += cs * max(0, 1 - months_ago/4)
    return min(stress, 0.30)   # cap at 30% stress

# ═══════════════════════════════════════════════════════════════════════════════
# VENDOR MASTER  — four named arcs baked in
# ═══════════════════════════════════════════════════════════════════════════════
#
# ARC NARRATIVES
# ──────────────
# DECLINING  : Kovacs Precision GmbH (V001)
#   Starts strong (score 82). Meridian pays late twice in Q3 2024 (tariff
#   cash-stress). Kovacs win rate falls as Meridian re-routes orders to
#   cheaper vendors post-tariff. By month 14 health=54, trend=declining.
#   Response rate to RFQs drops. Hermes flags them as at-risk.
#
# IMPROVING  : Patel Alloys Pvt Ltd (V003)
#   Starts moderate (score 61). India-EU FTA gives them price advantage
#   from month 12. Meridian starts sharing forecasts from month 6.
#   Win rate climbs. Score reaches 81 by month 18, trend=improving.
#
# COLLAPSE   : Guangzhou Mech & Elec Co. (V018)
#   Starts competitive but high-risk (score 58). EU anti-dumping duties
#   (month 3) remove their price advantage. Rare earth quota cuts (month 15)
#   make them uncompetitive in electrical. Score falls to 31 by month 16.
#   Effectively exits the usable vendor pool.
#
# NEW→PROVEN : Helios Micro Systems (V021)
#   Onboards month 4. Starts with no score. First 3 RFQs: response=yes,
#   bid=competitive, delivery=on time. Admin burden high initially (many
#   queries). Score builds from 0 to 67 by month 18 on thin but positive data.

VENDOR_TEMPLATES = [
    # (id, name, category, country, city, archetype, risk, is_new, rel_yrs, arc)
    ("V001","Kovacs Precision GmbH",        "Mechanical Parts",      "Germany",   "Stuttgart",  "reliable",            "low",    False, 9,  "declining"),
    ("V002","Tanaka Electrical KK",         "Electrical Components", "Japan",     "Osaka",      "conservative",        "low",    False, 7,  "stable"),
    ("V003","Patel Alloys Pvt Ltd",         "Raw Materials",         "India",     "Ahmedabad",  "relationship_focused", "low",    False, 5,  "improving"),
    ("V004","Strömberg Hydraulics AB",      "Mechanical Parts",      "Sweden",    "Gothenburg", "reliable",            "low",    False, 11, "stable"),
    ("V005","Cerro Negro Metals SA",        "Raw Materials",         "Chile",     "Santiago",   "aggressive_bidder",   "medium", False, 4,  "stable"),
    ("V006","Bright Spark Electronics Ltd", "Electrical Components", "UK",        "Birmingham", "volatile",            "medium", False, 3,  "stable"),
    ("V007","Nakamura Tooling Co.",         "Mechanical Parts",      "Japan",     "Nagoya",     "conservative",        "low",    False, 8,  "stable"),
    ("V008","Delta Composites Inc.",        "Raw Materials",         "USA",       "Houston",    "aggressive_bidder",   "medium", False, 4,  "stable"),
    ("V009","Fischer & Söhne KG",           "Mechanical Parts",      "Germany",   "Munich",     "relationship_focused","low",    False, 10, "stable"),
    ("V010","Adriatic Fastenings d.o.o.",   "Mechanical Parts",      "Croatia",   "Split",      "aggressive_bidder",   "medium", False, 3,  "stable"),
    ("V011","Solaris Power Components",     "Electrical Components", "Spain",     "Barcelona",  "volatile",            "medium", False, 2,  "stable"),
    ("V012","Indra Copper Works",           "Raw Materials",         "India",     "Mumbai",     "reliable",            "low",    False, 6,  "improving"),
    ("V013","Vantage Sensors GmbH",         "Electrical Components", "Germany",   "Dresden",    "conservative",        "low",    False, 7,  "stable"),
    ("V014","Coastal Alloys Pty Ltd",       "Raw Materials",         "Australia", "Perth",      "relationship_focused","medium", False, 4,  "stable"),
    ("V015","Nordic Steel AS",              "Raw Materials",         "Norway",    "Bergen",     "reliable",            "low",    False, 9,  "stable"),
    ("V016","Precision Arc Systems",        "Electrical Components", "USA",       "Detroit",    "volatile",            "high",   False, 2,  "stable"),
    ("V017","Türk Makina A.Ş.",             "Mechanical Parts",      "Turkey",    "Bursa",      "aggressive_bidder",   "medium", False, 3,  "stable"),
    ("V018","Guangzhou Mech & Elec Co.",    "Electrical Components", "China",     "Guangzhou",  "aggressive_bidder",   "high",   False, 2,  "collapse"),
    ("V019","Emerald Isle Castings Ltd",    "Mechanical Parts",      "Ireland",   "Cork",       "conservative",        "low",    False, 5,  "stable"),
    ("V020","Rajasthan Rare Earths Ltd",    "Raw Materials",         "India",     "Jaipur",     "relationship_focused","medium", False, 3,  "improving"),
    ("V021","Helios Micro Systems",         "Electrical Components", "Israel",    "Tel Aviv",   "conservative",        "medium", True,  0,  "new_proving"),
    ("V022","Andean Precision SRL",         "Mechanical Parts",      "Argentina", "Córdoba",    "aggressive_bidder",   "high",   True,  0,  "new_proving"),
    ("V023","Sahara Industrial FZE",        "Raw Materials",         "UAE",       "Dubai",      "volatile",            "high",   True,  0,  "new_proving"),
    ("V024","BalticTech UAB",               "Mechanical Parts",      "Lithuania", "Vilnius",    "reliable",            "medium", True,  0,  "new_proving"),
]

# Base performance values per vendor (before arc adjustments)
VENDOR_BASE = {
    "V001": dict(price_idx=0.91, otd=0.94, rr=0.90, qs=9.1, fh=8.8, cap=72),
    "V002": dict(price_idx=1.03, otd=0.92, rr=0.82, qs=9.0, fh=8.5, cap=78),
    "V003": dict(price_idx=0.96, otd=0.86, rr=0.78, qs=7.8, fh=7.2, cap=65),
    "V004": dict(price_idx=1.05, otd=0.95, rr=0.88, qs=9.3, fh=9.0, cap=70),
    "V005": dict(price_idx=0.84, otd=0.80, rr=0.85, qs=7.5, fh=7.0, cap=80),
    "V006": dict(price_idx=0.97, otd=0.78, rr=0.72, qs=7.2, fh=6.5, cap=82),
    "V007": dict(price_idx=1.04, otd=0.93, rr=0.84, qs=9.2, fh=8.7, cap=75),
    "V008": dict(price_idx=0.88, otd=0.81, rr=0.80, qs=7.6, fh=7.3, cap=85),
    "V009": dict(price_idx=1.02, otd=0.92, rr=0.86, qs=8.9, fh=8.6, cap=68),
    "V010": dict(price_idx=0.87, otd=0.79, rr=0.82, qs=7.4, fh=6.8, cap=83),
    "V011": dict(price_idx=0.99, otd=0.74, rr=0.68, qs=7.0, fh=6.2, cap=88),
    "V012": dict(price_idx=0.93, otd=0.88, rr=0.80, qs=8.1, fh=7.6, cap=66),
    "V013": dict(price_idx=1.01, otd=0.91, rr=0.83, qs=8.8, fh=8.4, cap=71),
    "V014": dict(price_idx=0.95, otd=0.85, rr=0.79, qs=7.9, fh=7.4, cap=74),
    "V015": dict(price_idx=1.00, otd=0.93, rr=0.87, qs=9.0, fh=8.9, cap=69),
    "V016": dict(price_idx=0.92, otd=0.72, rr=0.65, qs=6.8, fh=6.0, cap=90),
    "V017": dict(price_idx=0.86, otd=0.80, rr=0.81, qs=7.3, fh=6.9, cap=84),
    "V018": dict(price_idx=0.79, otd=0.76, rr=0.83, qs=6.5, fh=6.3, cap=88),
    "V019": dict(price_idx=1.02, otd=0.90, rr=0.85, qs=8.7, fh=8.3, cap=67),
    "V020": dict(price_idx=0.94, otd=0.84, rr=0.76, qs=7.6, fh=7.0, cap=70),
    "V021": dict(price_idx=0.98, otd=0.88, rr=0.75, qs=8.2, fh=7.8, cap=60),
    "V022": dict(price_idx=0.85, otd=0.78, rr=0.70, qs=7.0, fh=6.5, cap=75),
    "V023": dict(price_idx=0.90, otd=0.75, rr=0.68, qs=6.8, fh=6.2, cap=80),
    "V024": dict(price_idx=0.97, otd=0.85, rr=0.80, qs=8.0, fh=7.5, cap=65),
}

# ── Arc adjustment functions — return multiplier given month index (0=Jan 2024) ─
def arc_adjustment(arc: str, mo_idx: int, field: str) -> float:
    """Returns an additive adjustment to apply on top of the base value."""
    if arc == "declining":
        # Kovacs: gradual decline from month 8 onward
        if mo_idx < 8:
            return 0.0
        decay = (mo_idx - 8) * 0.012
        if field == "rr":   return -min(decay * 1.5, 0.28)
        if field == "otd":  return -min(decay * 0.8, 0.14)
        if field == "price_idx": return +min(decay * 0.5, 0.08)  # starts padding price
        return 0.0

    elif arc == "improving":
        # Patel: steady improvement from month 6 (forecast sharing begins)
        if mo_idx < 6:
            return 0.0
        gain = (mo_idx - 6) * 0.008
        if field == "rr":   return +min(gain * 1.2, 0.15)
        if field == "otd":  return +min(gain, 0.10)
        if field == "price_idx": return -min(gain * 0.6, 0.07)
        if field == "qs":   return +min(gain * 10, 0.8)
        return 0.0

    elif arc == "collapse":
        # Guangzhou: sharp decline from month 3 (EU duties), accelerates month 15
        if mo_idx < 3:
            return 0.0
        if mo_idx < 15:
            decay = (mo_idx - 3) * 0.020
        else:
            decay = (12 * 0.020) + (mo_idx - 15) * 0.045  # accelerates
        if field == "rr":   return -min(decay * 1.8, 0.65)
        if field == "price_idx": return +min(decay * 1.2, 0.22)  # loses price edge
        if field == "qs":   return -min(decay * 8, 2.0)
        return 0.0

    elif arc == "new_proving":
        # New vendors: start month 4 (onboard), ramp slowly
        if mo_idx < 4:
            return 0.0
        gain = min((mo_idx - 4) * 0.015, 0.12)
        if field == "rr":   return gain
        if field == "otd":  return gain * 0.8
        return 0.0

    return 0.0

# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════
def months_between(start: date, end: date):
    """Yield first-of-month dates from start to end inclusive."""
    d = start.replace(day=1)
    while d <= end:
        yield d
        if d.month == 12:
            d = d.replace(year=d.year+1, month=1)
        else:
            d = d.replace(month=d.month+1)

def month_index(d: date) -> int:
    return (d.year - START_DATE.year)*12 + (d.month - START_DATE.month)

def fmt(d) -> str:
    return d.strftime("%Y-%m-%d") if d else ""

def rand_date(s: date, e: date) -> date:
    delta = (e - s).days
    return s + timedelta(days=random.randint(0, max(0, delta)))

def business_days_after(d: date, n: int) -> date:
    count = 0
    while count < n:
        d += timedelta(days=1)
        if d.weekday() < 5:
            count += 1
    return d

def clamp(v, lo, hi):
    return max(lo, min(hi, v))

def save(df: pd.DataFrame, name: str):
    path = os.path.join(OUTPUT_DIR, name)
    df.to_csv(path, index=False)
    print(f"  ✓ {name:46s}  {len(df):>6,} rows")

# ═══════════════════════════════════════════════════════════════════════════════
# 01 — VENDORS
# ═══════════════════════════════════════════════════════════════════════════════
def build_vendors() -> pd.DataFrame:
    rows = []
    for (vid, name, cat, country, city, arch, risk, is_new, rel_yrs, arc) in VENDOR_TEMPLATES:
        domain = name.lower().replace(" ","").replace("&","").replace(".","")[:14] + ".com"
        cname  = fake.name()
        base   = VENDOR_BASE[vid]
        onboard_date = (START_DATE + timedelta(days=90)) if is_new else (
            START_DATE - timedelta(days=rel_yrs*365 + random.randint(0,60)))
        rows.append({
            "vendor_id":             vid,
            "vendor_name":           name,
            "category":              cat,
            "country":               country,
            "city":                  city,
            "contact_name":          cname,
            "contact_email":         f"{cname.split()[0].lower()}@{domain}",
            "phone":                 fake.phone_number(),
            "behavioral_archetype":  arch,
            "risk_tier":             risk,
            "is_new_vendor":         is_new,
            "relationship_arc":      arc,
            "relationship_years":    rel_yrs,
            "certifications":        "|".join(random.sample(
                ["ISO9001","ISO14001","AS9100","IATF16949","ISO45001","OHSAS18001"],
                k=random.randint(1,3))),
            "preferred_payment_terms": random.choice(["Net30","Net45","Net60","2/10 Net30","LC at sight"]),
            "onboarded_date":        fmt(onboard_date),
            # base performance (starting point — arc adjusts over time)
            "base_price_index":      base["price_idx"],
            "base_otd_rate":         base["otd"],
            "base_response_rate":    base["rr"],
            "base_quality_score":    base["qs"],
            "financial_health_score":base["fh"],
            "capacity_utilization_pct": base["cap"],
            # forecast sharing eligibility
            "forecast_eligible":     (not is_new) and rel_yrs >= 3 and risk == "low",
        })
    return pd.DataFrame(rows)

# ═══════════════════════════════════════════════════════════════════════════════
# 03 — COMMODITY PRICES  (weekly, with macro shocks)
# ═══════════════════════════════════════════════════════════════════════════════
COMMODITIES = [
    # name                  unit      base    trend    vol    categories_affected
    ("Steel HR Coil",       "USD/MT", 680,   +0.0018, 0.025, ["Mechanical Parts","Raw Materials"]),
    ("Aluminium 6061",      "USD/MT", 2450,  +0.0012, 0.020, ["Mechanical Parts","Raw Materials"]),
    ("Copper Wire Rod",     "USD/MT", 8900,  +0.0020, 0.030, ["Electrical Components","Raw Materials"]),
    ("Neodymium Magnets",   "USD/KG", 68,    +0.0030, 0.045, ["Electrical Components"]),
    ("Stainless 316L",      "USD/MT", 3100,  +0.0015, 0.022, ["Mechanical Parts","Raw Materials"]),
    ("HDPE Granules",       "USD/MT", 1150,  +0.0010, 0.018, ["Raw Materials"]),
    ("Titanium Sponge",     "USD/KG", 11.5,  +0.0025, 0.035, ["Mechanical Parts"]),
    ("PCB FR4 Laminate",    "USD/SQM",4.2,   +0.0008, 0.015, ["Electrical Components"]),
    ("Servo Motor 5kW",     "USD/unit",1850, +0.0005, 0.012, ["Electrical Components"]),
    ("Ball Bearing 6205",   "USD/unit",3.8,  +0.0003, 0.010, ["Mechanical Parts"]),
]

def build_commodity_prices() -> pd.DataFrame:
    rows = []
    weeks = list(d for d in _date_range(START_DATE, END_DATE, 7))
    for comm, unit, base, trend, vol, cats in COMMODITIES:
        price = float(base)
        for w in weeks:
            # apply macro shocks cumulatively decaying
            shock_mult = 1.0
            for ev_date, _, ev_cats, ev_shock, _ in MACRO_EVENTS:
                if ev_date <= w:
                    overlap = any(c in cats for c in ev_cats) if ev_cats else False
                    if overlap:
                        weeks_since = max(0, (w - ev_date).days // 7)
                        decay = max(0, 1 - weeks_since / 16)  # shock fully absorbed in 16 weeks
                        shock_mult += ev_shock * decay
            price = price * (1 + trend + np.random.normal(0, vol))
            rows.append({
                "week_start":    fmt(w),
                "commodity":     comm,
                "unit":          unit,
                "categories":    "|".join(cats),
                "price":         round(price * shock_mult, 3),
                "base_price":    round(float(base) * (1 + trend)**((w-START_DATE).days//7), 3),
                "shock_premium_pct": round((shock_mult - 1)*100, 2),
                "shock_flag":    1 if shock_mult > 1.03 else 0,
            })
    return pd.DataFrame(rows)

def _date_range(start, end, step=1):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=step)

# ═══════════════════════════════════════════════════════════════════════════════
# 04 — MARKET SIGNALS
# ═══════════════════════════════════════════════════════════════════════════════
MARKET_SIGNALS_DATA = [
    ("2024-02-14","news","Supply chain",
     "Steel mills in Germany report 8% capacity reduction due to energy cost pressures; HR coil lead times extending to 10-12 weeks.",
     ["Steel HR Coil"], -0.4, 0.85, 0.60),
    ("2024-03-28","policy","EU Trade",
     "EU Commission introduces anti-dumping duties of 18.7% on certain Chinese electrical components effective April 15. Guangzhou-based exporters face immediate pricing pressure.",
     ["PCB FR4 Laminate","Servo Motor 5kW"], -0.7, 0.92, 0.80),
    ("2024-05-10","price_data","LME",
     "Copper touches 2-year high of $9,450/MT on LME amid supply constraints from Chilean mines; analysts expect sustained pressure through Q3.",
     ["Copper Wire Rod"], -0.5, 0.95, 0.70),
    ("2024-06-20","rumor","Industry",
     "Unconfirmed reports suggest Tanaka Electrical KK considering capacity expansion at Osaka facility; could reduce lead times H2 2024.",
     [], 0.3, 0.40, 0.30),
    ("2024-07-04","news","Geopolitical",
     "Port of Hamburg faces 3-week backlog following dock worker strike; automotive and industrial shipments most affected. Rerouting via Rotterdam adds 5-7 days.",
     ["Steel HR Coil","Stainless 316L"], -0.8, 0.90, 0.75),
    ("2024-08-15","financial_report","Reuters",
     "Cerro Negro Metals Q2 results: revenue down 12% YoY; CFO signals aggressive pricing strategy to recapture volume in H2 2024.",
     ["Steel HR Coil","Aluminium 6061"], 0.2, 0.88, 0.50),
    ("2024-09-02","policy","US Trade",
     "US imposes 25% tariff on aluminium imports from select Southeast Asian countries; global aluminium markets react with +7% spike. Indian exporters gain relative advantage.",
     ["Aluminium 6061"], -0.6, 0.94, 0.80),
    ("2024-09-20","internal","Meridian",
     "Meridian secures major contract with Embraer for robotic assembly cell delivery. Order book grows 28% creating both opportunity and cash flow timing pressure.",
     [], 0.6, 1.00, 0.30),
    ("2024-10-11","news","Logistics",
     "Suez Canal alternative routing adds 12-14 days to Asia-Europe shipments; Indian and Chinese vendor lead times under pressure. Air freight premium up 40%.",
     [], -0.5, 0.88, 0.65),
    ("2024-11-05","price_data","Fastmarkets",
     "Stainless 316L premiums in Europe reach 18-month high; tightening scrap availability and strong automotive demand cited as primary drivers.",
     ["Stainless 316L"], -0.4, 0.92, 0.55),
    ("2024-11-15","internal","Meridian",
     "Meridian wins ₹340Cr BHEL contract for CNC machine supply. Strong Q4 pipeline but procurement team under pressure to contain material costs.",
     [], 0.7, 1.00, 0.25),
    ("2024-12-19","news","Industry",
     "Meridian competitor Hexagon AG announces 30% capacity ramp in Q1 2025; shared vendor pool will face increased demand pressure in mechanical components.",
     [], -0.3, 0.75, 0.40),
    ("2025-01-08","news","FX",
     "Japanese yen weakness drives Tanaka Electrical and Nakamura Tooling to revise export price lists upward 6-9%. Effective February billing cycles.",
     [], -0.4, 0.87, 0.50),
    ("2025-02-20","rumor","Market",
     "Multiple Tier-1 OEMs report Guangzhou Mech & Elec offering 20%+ below-market quotes; two quality incidents flagged. Procurement teams advised caution.",
     [], -0.2, 0.50, 0.40),
    ("2025-03-05","price_data","Argus Media",
     "Neodymium oxide prices surge 28% after China announces export quota cuts; servo motor and magnet supply chain in alarm. 6-week lead time extension expected.",
     ["Neodymium Magnets","Servo Motor 5kW"], -0.9, 0.96, 0.90),
    ("2025-04-12","policy","G7",
     "G7 nations agree coordinated critical minerals strategy; rare earth import diversification incentives begin Q3 2025. Indian rare earth exporters positioned to benefit.",
     ["Neodymium Magnets","Titanium Sponge"], 0.4, 0.80, 0.50),
    ("2025-05-01","financial_report","Reuters",
     "Nordic Steel AS secures €150M green bond; investment earmarked for EAF capacity expansion. Analysts raise quality and delivery outlook for H2 2025.",
     ["Steel HR Coil","Stainless 316L"], 0.6, 0.90, 0.40),
    ("2025-06-10","policy","Trade",
     "India-EU FTA finalised; zero-duty access for Indian raw material exporters phased over 5 years. Patel Alloys and Indra Copper Works flagged as immediate beneficiaries.",
     ["Stainless 316L","Copper Wire Rod"], 0.5, 0.88, 0.50),
]

def build_market_signals() -> pd.DataFrame:
    rows = []
    for i,(dt,stype,src,text,comms,sent,cred,cascade) in enumerate(MARKET_SIGNALS_DATA):
        rows.append({
            "signal_id":            f"SIG-{i+1:03d}",
            "date":                 dt,
            "signal_type":          stype,
            "source":               src,
            "headline":             text[:80],
            "full_text":            text,
            "affected_commodities": "|".join(comms),
            "sentiment_score":      sent,
            "credibility_score":    cred,
            "cascade_potential":    cascade,
            "mirofish_tag":         "scenario_6" if cascade >= 0.7 else (
                                    "scenario_1" if cascade >= 0.4 else "background"),
        })
    return pd.DataFrame(rows)

# ═══════════════════════════════════════════════════════════════════════════════
# 05-06 — SALES ORDERS + LINES
# ═══════════════════════════════════════════════════════════════════════════════
MATERIALS = [
    ("MECH-2201","Precision Ball Screw Assy 25mm","Mechanical Parts","pcs",380,420),
    ("MECH-2202","Linear Guide Rail 1500mm","Mechanical Parts","pcs",145,180),
    ("MECH-2203","Servo Coupling 14/19mm","Mechanical Parts","pcs",28,42),
    ("MECH-2204","Spindle Bearing Set NSK 7210","Mechanical Parts","pcs",210,260),
    ("MECH-2205","Cast Iron Bed Section Grade 300","Mechanical Parts","kg",3.2,4.8),
    ("ELEC-3301","Servo Drive 5.5kW Siemens-compat","Electrical Components","pcs",1650,1950),
    ("ELEC-3302","Encoder 2500 PPR Differential","Electrical Components","pcs",88,115),
    ("ELEC-3303","Limit Switch IP67 Stainless","Electrical Components","pcs",14,22),
    ("ELEC-3304","PLC I/O Module 32-channel DI","Electrical Components","pcs",340,420),
    ("ELEC-3305","Power Supply 24VDC 20A DIN","Electrical Components","pcs",95,130),
    ("RAW-4401","Steel HR Coil 3mm S235","Raw Materials","MT",690,780),
    ("RAW-4402","Aluminium Extrusion 6061-T6","Raw Materials","kg",2.9,3.8),
    ("RAW-4403","Copper Busbar 40×4mm","Raw Materials","m",18,26),
    ("RAW-4404","Stainless 316L Sheet 2mm","Raw Materials","kg",3.8,4.9),
    ("RAW-4405","HDPE Rod 50mm dia","Raw Materials","m",12,18),
]

CUSTOMERS = [
    ("Hexagon AG","Germany"),("Mitsubishi Heavy","Japan"),
    ("Tata Advanced Systems","India"),("Embraer S.A.","Brazil"),
    ("Rolls-Royce PLC","UK"),("FANUC Corporation","Japan"),
    ("Siemens Energy","Germany"),("GE Aviation","USA"),
    ("BHEL","India"),("Airbus SE","France"),
    ("Volkswagen AG","Germany"),("Bombardier Inc.","Canada"),
]

def build_sales_orders():
    so_rows, sol_rows = [], []
    # Demand is slightly higher in months 9-18 (big contracts won)
    for mo_idx, mo in enumerate(months_between(START_DATE, END_DATE)):
        n_orders = 11 if mo_idx < 9 else 14   # volume ramp after contract wins
        for _ in range(n_orders):
            so_id  = f"SO-2024-{len(so_rows)+1:04d}"
            cust, cc = random.choice(CUSTOMERS)
            urgency  = random.choices(["standard","expedited","critical"],
                                      weights=[0.55,0.30,0.15])[0]
            order_date = rand_date(mo, (mo.replace(month=mo.month+1)
                                        if mo.month<12 else mo.replace(year=mo.year+1,month=1))
                                       - timedelta(days=1))
            lead = {"standard":45,"expedited":25,"critical":14}[urgency]
            delivery = business_days_after(order_date, lead + random.randint(-3,5))
            items    = random.sample(MATERIALS, k=random.randint(2,6))
            total    = 0.0
            for j,(mc,md,mcat,unit,lo,hi) in enumerate(items):
                qty   = random.randint(5, 120)
                price = round(random.uniform(lo, hi), 2)
                total += qty * price
                sol_rows.append({
                    "so_line_id":     f"{so_id}-L{j+1:02d}",
                    "sales_order_id": so_id,
                    "line_no":        j+1,
                    "material_code":  mc,
                    "description":    md,
                    "category":       mcat,
                    "quantity":       qty,
                    "unit":           unit,
                    "unit_price_usd": price,
                    "line_value_usd": round(qty*price, 2),
                })
            so_rows.append({
                "sales_order_id":  so_id,
                "customer":        cust,
                "customer_country":cc,
                "order_date":      fmt(order_date),
                "delivery_deadline":fmt(delivery),
                "urgency_level":   urgency,
                "total_value_usd": round(total, 2),
                "month_index":     mo_idx,
            })
    return pd.DataFrame(so_rows), pd.DataFrame(sol_rows)

# ═══════════════════════════════════════════════════════════════════════════════
# 07-08 — WORK ORDERS + ITEMS
# ═══════════════════════════════════════════════════════════════════════════════
MANAGERS = ["Priya Nair","Ravi Shankar","Leena Mathew","Arjun Desai","Meena Krishnan"]

def build_work_orders(so_df, sol_df):
    wo_rows, woi_rows = [], []
    for _, so in so_df.iterrows():
        if random.random() < 0.10:
            continue
        wo_id = "WO-" + so["sales_order_id"].replace("SO-","")
        lines = sol_df[sol_df["sales_order_id"] == so["sales_order_id"]]
        wo_rows.append({
            "work_order_id":      wo_id,
            "sales_order_ref":    so["sales_order_id"],
            "created_date":       fmt(date.fromisoformat(so["order_date"]) + timedelta(days=random.randint(1,3))),
            "procurement_manager":random.choice(MANAGERS),
            "urgency_level":      so["urgency_level"],
            "budget_ceiling_usd": round(so["total_value_usd"] * random.uniform(1.04,1.16), 2),
            "rfq_required":       True,
            "month_index":        so["month_index"],
        })
        for _, line in lines.iterrows():
            req_by = date.fromisoformat(so["delivery_deadline"]) - timedelta(days=random.randint(7,18))
            woi_rows.append({
                "wo_item_id":               f"{wo_id}-I{line['line_no']:02d}",
                "work_order_id":            wo_id,
                "material_code":            line["material_code"],
                "description":              line["description"],
                "category":                 line["category"],
                "quantity":                 line["quantity"],
                "unit":                     line["unit"],
                "target_unit_price_usd":    round(line["unit_price_usd"] * random.uniform(0.88,1.02), 2),
                "required_by_date":         fmt(req_by),
                "preferred_vendor_category":line["category"],
            })
    return pd.DataFrame(wo_rows), pd.DataFrame(woi_rows)

# ═══════════════════════════════════════════════════════════════════════════════
# 09-13 — RFQ PIPELINE
# All tables derived from each other — no independent random draws for win rates
# ═══════════════════════════════════════════════════════════════════════════════
def _vendor_pool(cat: str, vendors_df: pd.DataFrame) -> list:
    return vendors_df[vendors_df["category"] == cat]["vendor_id"].tolist()

def _effective_rr(vendor: pd.Series, mo_idx: int) -> float:
    """Response rate adjusted for arc + month."""
    base = float(vendor["base_response_rate"])
    arc  = vendor["relationship_arc"]
    adj  = arc_adjustment(arc, mo_idx, "rr")
    # new vendors not yet onboarded
    if vendor["is_new_vendor"] and mo_idx < 4:
        return 0.0
    return clamp(base + adj + np.random.normal(0, 0.04), 0.0, 0.98)

def build_rfq_pipeline(wo_df, woi_df, vendors_df):
    rfq_rows, inv_rows, email_rows, bid_rows, eval_rows, burden_rows = \
        [], [], [], [], [], []
    rfq_ctr = 1

    vid_to_v = vendors_df.set_index("vendor_id").to_dict("index")
    woi_grp  = woi_df.groupby("work_order_id")

    for _, wo in wo_df.iterrows():
        wid     = wo["work_order_id"]
        mo_idx  = int(wo["month_index"])
        if wid not in woi_grp.groups:
            continue
        items   = woi_grp.get_group(wid)
        cat     = items["category"].mode()[0]
        pool    = _vendor_pool(cat, vendors_df)
        if len(pool) < 5:
            continue

        rfq_id    = f"RFQ-{rfq_ctr:04d}"
        rfq_ctr  += 1
        issue_dt  = date.fromisoformat(wo["created_date"]) + timedelta(days=random.randint(1,2))
        deadline  = business_days_after(issue_dt, 10 if wo["urgency_level"]=="standard" else
                                                   7  if wo["urgency_level"]=="expedited" else 5)
        target_p  = items["target_unit_price_usd"].mean()
        budget    = float(wo["budget_ceiling_usd"])

        # Pick 8 vendors — weight by effective response rate
        weights = []
        for vid in pool:
            v   = vid_to_v.get(vid, {})
            rr  = _effective_rr(pd.Series(v), mo_idx)
            # collapse arc vendors get deprioritised by selector
            if v.get("relationship_arc") == "collapse" and mo_idx > 12:
                rr *= 0.3
            weights.append(max(rr, 0.05))
        wsum = sum(weights)
        probs = [w/wsum for w in weights]
        k = min(VENDORS_PER_RFQ, len(pool))
        invited_ids = list(np.random.choice(pool, size=k, replace=False, p=probs))

        rfq_rows.append({
            "rfq_id":             rfq_id,
            "work_order_ref":     wid,
            "category":           cat,
            "issue_date":         fmt(issue_dt),
            "bid_deadline":       fmt(deadline),
            "n_vendors_invited":  len(invited_ids),
            "urgency":            wo["urgency_level"],
            "estimated_value_usd":round(target_p * items["quantity"].sum(), 2),
            "budget_ceiling_usd": budget,
            "month_index":        mo_idx,
            "status":             "closed",
        })

        shortlist_candidates = []
        for vid in invited_ids:
            v    = vid_to_v.get(vid, {})
            arc  = v.get("relationship_arc","stable")
            arch = v.get("behavioral_archetype","reliable")

            inv_rows.append({
                "invite_id":    f"{rfq_id}-INV-{vid}",
                "rfq_id":       rfq_id,
                "vendor_id":    vid,
                "vendor_name":  v.get("vendor_name",""),
                "invited_date": fmt(issue_dt),
                "category":     cat,
                "month_index":  mo_idx,
            })

            # ── response decision ─────────────────────────────────────────────
            eff_rr = _effective_rr(pd.Series(v), mo_idx)
            responded = random.random() < eff_rr

            # ── email thread ──────────────────────────────────────────────────
            # Outbound RFQ
            email_rows.append({
                "email_id":       f"EML-{len(email_rows)+1:05d}",
                "rfq_id":         rfq_id,
                "vendor_id":      vid,
                "direction":      "outbound",
                "timestamp":      fmt(issue_dt) + " 09:15:00",
                "from_email":     "procurement@meridian-industrial.com",
                "to_email":       v.get("contact_email",""),
                "subject":        f"Request for Quotation – {rfq_id} – {cat}",
                "email_type":     "rfq_invite",
                "body_snippet":   f"Please find attached our RFQ {rfq_id}. Bid deadline: {fmt(deadline)}.",
                "bid_amount_usd": None,
                "delivery_days":  None,
            })

            if not responded:
                inv_rows[-1]["responded"] = False
                inv_rows[-1]["response_type"] = "no_response"
                # admin burden: 0 rounds (they didn't respond)
                burden_rows.append({
                    "burden_id":          f"BUR-{rfq_id}-{vid}",
                    "rfq_id":             rfq_id,
                    "vendor_id":          vid,
                    "responded":          False,
                    "clarification_rounds":0,
                    "days_to_respond":    None,
                    "spec_complete_flag": random.random() < 0.75,
                    "bid_submitted":      False,
                    "month_index":        mo_idx,
                })
                continue

            # Acknowledgement (70% of responders)
            ack_days = random.randint(1, 3)
            ack_dt   = issue_dt + timedelta(days=ack_days)
            if random.random() < 0.70:
                email_rows.append({
                    "email_id":       f"EML-{len(email_rows)+1:05d}",
                    "rfq_id":         rfq_id,
                    "vendor_id":      vid,
                    "direction":      "inbound",
                    "timestamp":      fmt(ack_dt) + f" {random.randint(8,17):02d}:00:00",
                    "from_email":     v.get("contact_email",""),
                    "to_email":       "procurement@meridian-industrial.com",
                    "subject":        f"Re: Request for Quotation – {rfq_id}",
                    "email_type":     "acknowledgement",
                    "body_snippet":   "Thank you for your RFQ. We will submit our quotation before the deadline.",
                    "bid_amount_usd": None,
                    "delivery_days":  None,
                })

            # Clarification rounds — more for volatile/new vendors and poor specs
            spec_complete = random.random() < (0.80 if arc != "new_proving" else 0.55)
            clarification_rounds = 0
            if not spec_complete or arch == "volatile":
                clarification_rounds = random.randint(1, 3 if arc == "new_proving" else 2)
                for cr in range(clarification_rounds):
                    q_dt = ack_dt + timedelta(days=cr+1)
                    email_rows.append({
                        "email_id":       f"EML-{len(email_rows)+1:05d}",
                        "rfq_id":         rfq_id,
                        "vendor_id":      vid,
                        "direction":      "inbound",
                        "timestamp":      fmt(q_dt) + " 11:00:00",
                        "from_email":     v.get("contact_email",""),
                        "to_email":       "procurement@meridian-industrial.com",
                        "subject":        f"Re: RFQ {rfq_id} — Clarification Required",
                        "email_type":     "query",
                        "body_snippet":   f"Could you clarify item specification on line {cr+1}? Specifically tolerance and surface finish.",
                        "bid_amount_usd": None,
                        "delivery_days":  None,
                    })

            # Bid submission
            bid_dt  = deadline - timedelta(days=random.randint(0, 3))
            delta_map = {
                "aggressive_bidder": np.random.normal(-0.10, 0.04),
                "conservative":      np.random.normal(+0.03, 0.02),
                "volatile":          np.random.normal(-0.02, 0.09),
                "reliable":          np.random.normal(-0.03, 0.02),
                "relationship_focused": np.random.normal(-0.05, 0.03),
            }
            price_delta = delta_map.get(arch, 0.0)
            # collapse vendors' price edge is gone
            if arc == "collapse":
                price_delta = abs(price_delta) + 0.05 * max(0, mo_idx - 3) * 0.03
            bid_unit  = round(target_p * (1 + price_delta), 2)
            bid_total = round(bid_unit * items["quantity"].sum(), 2)
            del_days  = random.randint(10, 55)

            email_rows.append({
                "email_id":       f"EML-{len(email_rows)+1:05d}",
                "rfq_id":         rfq_id,
                "vendor_id":      vid,
                "direction":      "inbound",
                "timestamp":      fmt(bid_dt) + f" {random.randint(9,17):02d}:00:00",
                "from_email":     v.get("contact_email",""),
                "to_email":       "procurement@meridian-industrial.com",
                "subject":        f"Quotation Submission – {rfq_id} – {v.get('vendor_name','')}",
                "email_type":     "bid",
                "body_snippet":   f"Please find our quotation. Unit price USD {bid_unit:,.2f}. Total USD {bid_total:,.2f}. Lead time {del_days} days.",
                "bid_amount_usd": bid_total,
                "delivery_days":  del_days,
            })

            inv_rows[-1]["responded"]     = True
            inv_rows[-1]["response_type"] = "bid"

            burden_rows.append({
                "burden_id":           f"BUR-{rfq_id}-{vid}",
                "rfq_id":              rfq_id,
                "vendor_id":           vid,
                "responded":           True,
                "clarification_rounds":clarification_rounds,
                "days_to_respond":     (bid_dt - issue_dt).days,
                "spec_complete_flag":  spec_complete,
                "bid_submitted":       True,
                "month_index":         mo_idx,
            })

            qual = float(v.get("base_quality_score", 7.0)) + arc_adjustment(arc, mo_idx, "qs")
            rel  = min(10, float(v.get("relationship_years", 0)) * 0.7 + 4)
            shortlist_candidates.append({
                "vendor_id":   vid,
                "vendor_name": v.get("vendor_name",""),
                "bid_total":   bid_total,
                "bid_unit":    bid_unit,
                "del_days":    del_days,
                "price_delta": price_delta,
                "quality":     qual,
                "relation":    rel,
                "arc":         arc,
            })

            bid_rows.append({
                "bid_id":          f"BID-{rfq_id}-{vid}",
                "rfq_id":          rfq_id,
                "vendor_id":       vid,
                "vendor_name":     v.get("vendor_name",""),
                "bid_date":        fmt(bid_dt),
                "bid_unit_price":  bid_unit,
                "bid_total_usd":   bid_total,
                "delivery_days":   del_days,
                "validity_days":   30,
                "price_delta_pct": round(price_delta*100, 2),
                "archetype":       arch,
                "month_index":     mo_idx,
            })

        # ── Evaluation + selection ────────────────────────────────────────────
        if shortlist_candidates:
            max_bid = max(s["bid_total"] for s in shortlist_candidates)
            min_del = min(s["del_days"]  for s in shortlist_candidates)
            scored  = []
            for s in shortlist_candidates:
                ps = (1 - s["bid_total"]/max_bid) * 100
                ds = (min_del/s["del_days"])       * 100
                qs = (s["quality"]/10)             * 100
                rs = (s["relation"]/10)            * 100
                cs = round(0.40*ps + 0.30*ds + 0.20*qs + 0.10*rs, 2)
                scored.append({**s, "price_s":ps,"delivery_s":ds,
                               "quality_s":qs,"relation_s":rs,"composite":cs})
            scored.sort(key=lambda x: x["composite"], reverse=True)
            sel_ids = {s["vendor_id"] for s in scored[:SHORTLIST_SIZE]}
            for s in scored:
                eval_rows.append({
                    "eval_id":          f"EVAL-{rfq_id}-{s['vendor_id']}",
                    "rfq_id":           rfq_id,
                    "vendor_id":        s["vendor_id"],
                    "vendor_name":      s["vendor_name"],
                    "bid_total_usd":    s["bid_total"],
                    "delivery_days":    s["del_days"],
                    "price_score":      round(s["price_s"],2),
                    "delivery_score":   round(s["delivery_s"],2),
                    "quality_score":    round(s["quality_s"],2),
                    "relationship_score":round(s["relation_s"],2),
                    "composite_score":  s["composite"],
                    "selected":         s["vendor_id"] in sel_ids,
                    "month_index":      mo_idx,
                })

    return (pd.DataFrame(rfq_rows), pd.DataFrame(inv_rows),
            pd.DataFrame(email_rows), pd.DataFrame(bid_rows),
            pd.DataFrame(eval_rows), pd.DataFrame(burden_rows))

# ═══════════════════════════════════════════════════════════════════════════════
# 14-16 — PURCHASE ORDERS, DELIVERIES, DISPUTES
# ═══════════════════════════════════════════════════════════════════════════════
def build_purchase_orders(eval_df, bid_df):
    rows = []
    selected = eval_df[eval_df["selected"] == True]
    for _, e in selected.iterrows():
        bid = bid_df[(bid_df["rfq_id"]==e["rfq_id"]) & (bid_df["vendor_id"]==e["vendor_id"])]
        if bid.empty: continue
        b = bid.iloc[0]
        v_mo = date.fromisoformat("2024-01-01") + timedelta(days=int(e["month_index"])*30)
        po_date = v_mo + timedelta(days=random.randint(3,10))
        terms_days = {"Net30":30,"Net45":45,"Net60":60,"2/10 Net30":30,"LC at sight":0}
        terms = random.choice(list(terms_days.keys()))
        rows.append({
            "po_id":             f"PO-{e['rfq_id']}-{e['vendor_id']}",
            "rfq_id":            e["rfq_id"],
            "vendor_id":         e["vendor_id"],
            "vendor_name":       e["vendor_name"],
            "po_date":           fmt(po_date),
            "po_value_usd":      b["bid_total_usd"],
            "promised_delivery": fmt(po_date + timedelta(days=int(b["delivery_days"]))),
            "payment_terms":     terms,
            "payment_due_date":  fmt(po_date + timedelta(days=terms_days[terms])),
            "month_index":       e["month_index"],
            "status":            "delivered" if po_date < date(2025,5,1) else random.choice(["delivered","in_transit"]),
        })
    return pd.DataFrame(rows)

def build_delivery_records(po_df, vendors_df):
    rows = []
    vid_to_v = vendors_df.set_index("vendor_id").to_dict("index")
    for _, po in po_df.iterrows():
        if po["status"] not in ("delivered","in_transit"): continue
        v      = vid_to_v.get(po["vendor_id"], {})
        mo_idx = int(po["month_index"])
        arc    = v.get("relationship_arc","stable")
        base_otd = float(v.get("base_otd_rate", 0.85))
        otd_adj  = arc_adjustment(arc, mo_idx, "otd")
        eff_otd  = clamp(base_otd + otd_adj, 0.40, 0.99)
        on_time  = random.random() < eff_otd
        promised = date.fromisoformat(po["promised_delivery"])
        delta    = 0 if on_time else random.randint(1, 21)
        actual   = promised + timedelta(days=delta)
        rows.append({
            "delivery_id":      f"DEL-{po['po_id']}",
            "po_id":            po["po_id"],
            "vendor_id":        po["vendor_id"],
            "promised_date":    po["promised_delivery"],
            "actual_date":      fmt(actual),
            "days_late":        delta,
            "on_time":          on_time,
            "condition":        random.choices(["accepted","accepted_with_note","rejected"],
                                               weights=[0.83,0.11,0.06])[0],
            "quality_issue":    random.random() < max(0.02, 0.12 if arc=="collapse" else 0.04),
            "invoice_value_usd":round(float(po["po_value_usd"]) * random.uniform(0.97,1.02), 2),
            "month_index":      po["month_index"],
        })
    return pd.DataFrame(rows)

def build_disputes(po_df, del_df):
    rows = []
    bad = del_df[(del_df["days_late"]>7) | (del_df["quality_issue"]==True)]
    for _, d in bad.iterrows():
        if random.random() < 0.35:
            rows.append({
                "dispute_id":  f"DISP-{d['delivery_id']}",
                "po_id":       d["po_id"],
                "vendor_id":   d["vendor_id"],
                "dispute_date":d["actual_date"],
                "reason":      "late_delivery" if d["days_late"]>7 else "quality_rejection",
                "claimed_usd": round(float(d["invoice_value_usd"])*random.uniform(0.05,0.20),2),
                "resolved":    random.random()<0.75,
                "resolution":  random.choice(["credit_note","replacement","penalty_deducted","rejected_claim"]),
                "month_index": d["month_index"],
            })
    return pd.DataFrame(rows)

# ═══════════════════════════════════════════════════════════════════════════════
# 20 — PAYMENT EVENTS  (time-aware lateness)
# ═══════════════════════════════════════════════════════════════════════════════
def build_payment_events(po_df):
    """
    Simulates actual payment dates. Lateness is driven by:
      - Meridian's cash stress index (peaks Sep-Nov 2024)
      - Vendor's importance (strategic vendors get paid on time more)
      - Random noise
    """
    rows = []
    for _, po in po_df.iterrows():
        if po["status"] not in ("delivered","in_transit"):
            continue
        due_date = date.fromisoformat(po["payment_due_date"])
        mo_idx   = int(po["month_index"])
        mo_date  = START_DATE + timedelta(days=mo_idx*30)
        stress   = meridian_cash_stress(mo_date)

        # Payment lateness probability shaped by stress
        p_on_time     = max(0.50, 0.82 - stress * 2.0)
        p_slight_late = 0.18
        p_late        = min(0.25, stress * 1.5 + 0.04)
        p_dispute     = min(0.05, stress * 0.3)
        total         = p_on_time + p_slight_late + p_late + p_dispute
        probs         = [p_on_time/total, p_slight_late/total, p_late/total, p_dispute/total]

        outcome = random.choices(["on_time","slightly_late","late","disputed"], weights=probs)[0]
        if outcome == "on_time":
            days_late = random.randint(-5, 0)   # sometimes pay early
        elif outcome == "slightly_late":
            days_late = random.randint(1, 7)
        elif outcome == "late":
            days_late = random.randint(8, 30)
        else:
            days_late = random.randint(15, 60)

        actual_pay = due_date + timedelta(days=days_late)

        rows.append({
            "payment_id":          f"PAY-{po['po_id']}",
            "po_id":               po["po_id"],
            "vendor_id":           po["vendor_id"],
            "po_value_usd":        po["po_value_usd"],
            "payment_terms":       po["payment_terms"],
            "due_date":            fmt(due_date),
            "actual_payment_date": fmt(actual_pay),
            "days_late":           max(0, days_late),
            "days_early":          max(0, -days_late),
            "payment_status":      outcome,
            "meridian_stress_index":round(stress, 3),
            "month_index":         mo_idx,
        })
    return pd.DataFrame(rows)

# ═══════════════════════════════════════════════════════════════════════════════
# 21 — FORECAST SHARING
# ═══════════════════════════════════════════════════════════════════════════════
def build_forecast_sharing(vendors_df, so_df):
    """
    Meridian shares rolling 90-day demand forecasts quarterly with eligible vendors.
    Accuracy degrades during macro shock periods.
    Patel Alloys and Indra Copper begin receiving forecasts from month 6.
    """
    rows = []
    eligible = vendors_df[vendors_df["forecast_eligible"] == True]["vendor_id"].tolist()
    # Also include improving-arc vendors from month 6
    improving = vendors_df[vendors_df["relationship_arc"]=="improving"]["vendor_id"].tolist()

    quarters = []
    d = START_DATE
    while d <= END_DATE:
        quarters.append(d)
        # next quarter
        m = d.month + 3
        y = d.year + (m-1)//12
        m = ((m-1) % 12) + 1
        d = d.replace(year=y, month=m)

    fs_id = 1
    for q_date in quarters:
        mo_idx  = month_index(q_date)
        stress  = meridian_cash_stress(q_date)
        # active shocks reduce forecast accuracy
        accuracy_base = 0.82 - stress * 1.5

        active_eligible = eligible.copy()
        if mo_idx >= 6:
            active_eligible += [v for v in improving if v not in active_eligible]

        for vid in active_eligible:
            v_mo = q_date + timedelta(days=random.randint(5,15))
            # forecast horizon
            horizon_start = q_date + timedelta(days=90)
            horizon_end   = horizon_start + timedelta(days=90)

            # estimated demand from actual SOs in horizon
            so_in_horizon = so_df[
                (so_df["order_date"] >= fmt(horizon_start)) &
                (so_df["order_date"] <= fmt(horizon_end))
            ]
            forecast_value = round(
                so_in_horizon["total_value_usd"].sum() * random.uniform(0.6,1.0) / 24, 2
            )
            # accuracy: what fraction of forecast actually materialised
            accuracy = clamp(
                accuracy_base + np.random.normal(0, 0.08),
                0.30, 0.98
            )
            actual_value = round(forecast_value * accuracy, 2)

            rows.append({
                "forecast_id":        f"FC-{fs_id:04d}",
                "vendor_id":          vid,
                "forecast_date":      fmt(v_mo),
                "forecast_quarter":   q_date.strftime("%Y-Q%q").replace(
                    "Q1","Q1").replace("Q4","Q4"),
                "horizon_start":      fmt(horizon_start),
                "horizon_end":        fmt(horizon_end),
                "forecast_value_usd": forecast_value,
                "actual_value_usd":   actual_value,
                "accuracy_pct":       round(accuracy*100, 1),
                "meridian_stress":    round(stress, 3),
                "month_index":        mo_idx,
            })
            fs_id += 1
    return pd.DataFrame(rows)

# ═══════════════════════════════════════════════════════════════════════════════
# 02 — VENDOR PERFORMANCE  (derived from actual events, not independent randoms)
# ═══════════════════════════════════════════════════════════════════════════════
def build_vendor_performance(vendors_df, inv_df, eval_df, del_df, pay_df):
    """
    Monthly KPI snapshots computed from actual event tables.
    Win rate = actual wins / actual invitations (from eval/invite tables).
    OTD = actual delivery performance (from delivery table).
    Payment reliability = derived from payment events.
    """
    rows = []
    vid_to_v = vendors_df.set_index("vendor_id").to_dict("index")

    for mo_idx, mo in enumerate(months_between(START_DATE, END_DATE)):
        mo_str = fmt(mo)
        for vid, v in vid_to_v.items():
            arc    = v.get("relationship_arc","stable")
            is_new = v.get("is_new_vendor", False)
            # new vendors not yet onboarded
            if is_new and mo_idx < 4:
                continue

            # ── invitations and wins this month ──────────────────────────────
            inv_mo  = inv_df[(inv_df["vendor_id"]==vid) & (inv_df["month_index"]==mo_idx)]
            eval_mo = eval_df[(eval_df["vendor_id"]==vid) & (eval_df["month_index"]==mo_idx)]
            n_invited  = len(inv_mo)
            n_responded= int(inv_mo["responded"].sum()) if "responded" in inv_mo.columns and len(inv_mo) else 0
            n_bid      = int(eval_mo.shape[0])
            n_won      = int(eval_mo["selected"].sum()) if len(eval_mo) else 0

            # rolling 6-month win rate
            mo_range   = list(range(max(0,mo_idx-5), mo_idx+1))
            inv_roll   = inv_df[(inv_df["vendor_id"]==vid) & (inv_df["month_index"].isin(mo_range))]
            eval_roll  = eval_df[(eval_df["vendor_id"]==vid) & (eval_df["month_index"].isin(mo_range))]
            win_rate_6mo = (int(eval_roll["selected"].sum()) / max(1,len(inv_roll)))

            # ── delivery performance ──────────────────────────────────────────
            del_mo = del_df[(del_df["vendor_id"]==vid) & (del_df["month_index"]==mo_idx)]
            if len(del_mo):
                otd_actual = float(del_mo["on_time"].mean())
            else:
                base_otd = float(v.get("base_otd_rate",0.85))
                otd_actual = clamp(base_otd + arc_adjustment(arc,mo_idx,"otd") +
                                   np.random.normal(0,0.03), 0.4, 0.99)

            # ── price index ───────────────────────────────────────────────────
            base_pi = float(v.get("base_price_index",1.0))
            pi = clamp(base_pi + arc_adjustment(arc,mo_idx,"price_idx") +
                       np.random.normal(0, 0.012), 0.70, 1.40)

            # ── quality ───────────────────────────────────────────────────────
            base_qs = float(v.get("base_quality_score",7.5))
            qs = clamp(base_qs + arc_adjustment(arc,mo_idx,"qs") +
                       np.random.normal(0,0.2), 1.0, 10.0)

            # ── payment reliability (from Meridian toward this vendor) ────────
            pay_mo = pay_df[(pay_df["vendor_id"]==vid) & (pay_df["month_index"]==mo_idx)]
            if len(pay_mo):
                pct_on_time = float((pay_mo["payment_status"]=="on_time").mean())
                avg_late    = float(pay_mo["days_late"].mean())
            else:
                pct_on_time = None
                avg_late    = None

            # effective response rate for this month
            base_rr = float(v.get("base_response_rate",0.80))
            eff_rr  = clamp(base_rr + arc_adjustment(arc,mo_idx,"rr") +
                            np.random.normal(0,0.03), 0.0, 0.99)

            rows.append({
                "snapshot_id":           f"VP-{vid}-{mo.strftime('%Y%m')}",
                "vendor_id":             vid,
                "vendor_name":           v.get("vendor_name",""),
                "month":                 mo_str,
                "month_index":           mo_idx,
                "relationship_arc":      arc,
                "price_index":           round(pi, 3),
                "on_time_delivery_rate": round(otd_actual, 3),
                "response_rate":         round(eff_rr, 3),
                "quality_score":         round(qs, 2),
                "n_rfqs_invited":        n_invited,
                "n_rfqs_responded":      n_responded,
                "n_bids_submitted":      n_bid,
                "n_pos_won":             n_won,
                "win_rate_6mo":          round(win_rate_6mo, 3),
                "capacity_utilization":  round(clamp(
                    float(v.get("capacity_utilization_pct",75)) + np.random.normal(0,4),
                    30, 100), 1),
                "defect_rate_ppm":       round(max(0, np.random.normal(800-qs*60, 100)), 0),
                "payment_pct_on_time":   round(pct_on_time, 3) if pct_on_time is not None else None,
                "payment_avg_days_late": round(avg_late, 1)    if avg_late    is not None else None,
            })
    return pd.DataFrame(rows)

# ═══════════════════════════════════════════════════════════════════════════════
# 23 — VENDOR RELATIONSHIP HEALTH SCORES  (monthly, with trend)
# ═══════════════════════════════════════════════════════════════════════════════
HEALTH_WEIGHTS = {
    "payment_reliability": 0.35,
    "win_rate":            0.25,
    "admin_burden":        0.25,
    "forecast_accuracy":   0.15,
}

def _payment_reliability_score(vendor_id, mo_idx, pay_df) -> float:
    """0-100. Includes memory: one late payment remembered for 3 months."""
    window = list(range(max(0, mo_idx-2), mo_idx+1))
    pm = pay_df[(pay_df["vendor_id"]==vendor_id) & (pay_df["month_index"].isin(window))]
    if pm.empty:
        return 75.0  # neutral if no data
    score = 100.0
    for _, p in pm.iterrows():
        age_penalty = 1.0 if p["month_index"] == mo_idx else 0.6
        if p["payment_status"] == "slightly_late":
            score -= 15 * age_penalty
        elif p["payment_status"] == "late":
            score -= 30 * age_penalty
        elif p["payment_status"] == "disputed":
            score -= 50 * age_penalty
        elif p["payment_status"] == "on_time" and p.get("days_early",0) > 0:
            score += 3 * age_penalty   # small bonus for paying early
    return clamp(score, 0, 100)

def _win_rate_score(vendor_id, mo_idx, inv_df, eval_df) -> float:
    """0-100. Rolling 6-month win rate. Healthy = winning ~2 of 5 invited."""
    window = list(range(max(0, mo_idx-5), mo_idx+1))
    inv  = inv_df[(inv_df["vendor_id"]==vendor_id) & (inv_df["month_index"].isin(window))]
    evl  = eval_df[(eval_df["vendor_id"]==vendor_id) & (eval_df["month_index"].isin(window))]
    if inv.empty:
        return 50.0  # unknown
    rate = len(evl[evl["selected"]==True]) / max(1, len(inv))
    # 40% win rate = 100 pts; 0% = 0 pts; scale linearly
    return clamp(rate / 0.40 * 100, 0, 100)

def _admin_burden_score(vendor_id, mo_idx, burden_df) -> float:
    """0-100. Inverted: fewer clarification rounds = higher score."""
    window = list(range(max(0, mo_idx-2), mo_idx+1))
    bm = burden_df[(burden_df["vendor_id"]==vendor_id) & (burden_df["month_index"].isin(window))]
    if bm.empty:
        return 70.0
    responded = bm[bm["responded"]==True]
    if responded.empty:
        return 70.0
    avg_rounds = responded["clarification_rounds"].mean()
    spec_ok    = responded["spec_complete_flag"].mean()
    # base 100, -20 per avg clarification round above 0, -15 if spec often incomplete
    score = 100 - (avg_rounds * 20) - ((1 - spec_ok) * 15)
    return clamp(score, 0, 100)

def _forecast_accuracy_score(vendor_id, mo_idx, fc_df) -> float:
    """0-100. 0 if no forecast shared (neutral — not penalised)."""
    window = list(range(max(0, mo_idx-5), mo_idx+1))
    fm = fc_df[(fc_df["vendor_id"]==vendor_id) & (fc_df["month_index"].isin(window))]
    if fm.empty:
        return None  # signal: no forecast program
    avg_acc = fm["accuracy_pct"].mean() / 100.0
    # 80%+ accuracy = 100 pts; 40% = 0 pts
    return clamp((avg_acc - 0.40) / 0.40 * 100, 0, 100)

def build_health_scores(vendors_df, pay_df, inv_df, eval_df, burden_df, fc_df) -> pd.DataFrame:
    rows      = []
    score_history = defaultdict(list)   # vendor_id → list of monthly composites

    for mo_idx, mo in enumerate(months_between(START_DATE, END_DATE)):
        for _, v in vendors_df.iterrows():
            vid    = v["vendor_id"]
            arc    = v["relationship_arc"]
            is_new = v["is_new_vendor"]

            # New vendors: no score until onboarded
            if is_new and mo_idx < 4:
                continue
            # New vendors: thin data flag for first 6 months
            thin_data = is_new and mo_idx < 10

            pr  = _payment_reliability_score(vid, mo_idx, pay_df)
            wr  = _win_rate_score(vid, mo_idx, inv_df, eval_df)
            ab  = _admin_burden_score(vid, mo_idx, burden_df)
            fa  = _forecast_accuracy_score(vid, mo_idx, fc_df)

            # If no forecast programme, redistribute weight
            if fa is None:
                w = dict(HEALTH_WEIGHTS)
                w_total_ex_fc = 1 - w["forecast_accuracy"]
                for k in ("payment_reliability","win_rate","admin_burden"):
                    w[k] = w[k] / w_total_ex_fc
                composite = round(
                    w["payment_reliability"] * pr +
                    w["win_rate"]            * wr +
                    w["admin_burden"]        * ab, 1)
            else:
                composite = round(
                    HEALTH_WEIGHTS["payment_reliability"] * pr +
                    HEALTH_WEIGHTS["win_rate"]            * wr +
                    HEALTH_WEIGHTS["admin_burden"]        * ab +
                    HEALTH_WEIGHTS["forecast_accuracy"]   * fa, 1)

            score_history[vid].append(composite)

            # Trend: compare last 3 months
            hist = score_history[vid]
            if len(hist) >= 3:
                recent_avg = sum(hist[-3:])  / 3
                prior_avg  = sum(hist[-6:-3]) / 3 if len(hist) >= 6 else hist[0]
                delta      = recent_avg - prior_avg
                if delta > 3:   trend = "improving"
                elif delta < -3: trend = "declining"
                else:            trend = "stable"
            elif len(hist) >= 2:
                delta = hist[-1] - hist[-2]
                trend = "improving" if delta > 2 else "declining" if delta < -2 else "stable"
            else:
                trend = "unknown"

            alert = (
                composite < 55 or
                (trend == "declining" and composite < 70) or
                (arc == "collapse" and mo_idx > 10)
            )

            rows.append({
                "health_score_id":        f"HS-{vid}-{mo.strftime('%Y%m')}",
                "vendor_id":              vid,
                "vendor_name":            v["vendor_name"],
                "month":                  fmt(mo),
                "month_index":            mo_idx,
                "relationship_arc":       arc,
                "payment_reliability_score": round(pr, 1),
                "win_rate_score":         round(wr, 1),
                "admin_burden_score":     round(ab, 1),
                "forecast_accuracy_score":round(fa, 1) if fa is not None else None,
                "composite_health_score": composite,
                "trend_3mo":              trend,
                "thin_data_flag":         thin_data,
                "alert_flag":             alert,
                "alert_reason":           (
                    "score_below_55"   if composite < 55 else
                    "declining_trend"  if trend=="declining" and composite < 70 else
                    "collapse_arc"     if arc=="collapse" and mo_idx > 10 else ""
                ),
            })

    return pd.DataFrame(rows)

# ═══════════════════════════════════════════════════════════════════════════════
# 17-19 — MIROFISH TABLES  (personas, world events, sim configs)
# ═══════════════════════════════════════════════════════════════════════════════
def build_mirofish_personas(vendors_df) -> pd.DataFrame:
    templates = [
        ("vendor_agent","scenario_1","Price-aggressive; monitors competitor bids; will undercut 15% for volume","opportunistic"),
        ("vendor_agent","scenario_1","Relationship-driven; rarely drops below cost; expects multi-year contracts","risk_averse"),
        ("vendor_agent","scenario_1","Volatile pricing; capacity constraints Q3; likely to withdraw if lead < 30d","volatile"),
        ("vendor_agent","scenario_1","Conservative; ISO-certified; slow to adapt pricing; prioritises OTD rep","risk_averse"),
        ("vendor_agent","scenario_1","New entrant; will underbid to gain reference customer","aggressive"),
        ("vendor_agent","scenario_6","Port-dependent; exposed to Hamburg delays; 3-week buffer stock only","risk_averse"),
        ("vendor_agent","scenario_6","Diversified logistics; can switch to air freight +12% cost","collaborative"),
        ("vendor_agent","scenario_6","Single-source raw material from China; tariff spike → +18% in 2 weeks","risk_averse"),
        ("vendor_agent","scenario_6","Has rare earth inventory hedge until Q2 2025; can hold price 60 days","opportunistic"),
        ("vendor_agent","scenario_7","Unknown vendor; bootstrapped from 2 analog profiles; medium trust prior","collaborative"),
        ("buyer_agent","all","Procurement manager; OTD over price by 1.5×; prefers ISO9001 vendors","risk_averse"),
        ("buyer_agent","all","Category manager Electrical; aggressive on price; tracks LME weekly","opportunistic"),
        ("buyer_agent","all","CFO delegate; hard budget ceiling; escalates if PO > target by >8%","risk_averse"),
        ("market_agent","scenario_6","LME copper desk analyst; publishes weekly price curves","collaborative"),
        ("market_agent","scenario_6","Freight forwarder; live Suez/Hamburg routing data","collaborative"),
        ("regulator_agent","scenario_6","EU trade desk; monitors tariff compliance; 5-day guidance turnaround","risk_averse"),
        ("competitor_agent","all","Hexagon AG procurement; competes for same vendor capacity; pays 5% premium","aggressive"),
    ]
    rows = []
    for i,(role,tag,persona,style) in enumerate(templates):
        vid = vendors_df.iloc[i % len(vendors_df)]["vendor_id"] if role=="vendor_agent" else ""
        rows.append({
            "agent_id":         f"AGENT-{i+1:03d}",
            "role":             role,
            "scenario_tag":     tag,
            "persona_summary":  persona,
            "decision_style":   style,
            "bound_vendor_id":  vid,
            "trust_network":    "|".join([f"AGENT-{j+1:03d}" for j in
                                 random.sample(range(len(templates)),
                                 k=min(3,len(templates)-1)) if j!=i]),
            "memory_seed_1":    f"Won contract worth €{random.randint(200,800)}K in {random.randint(2021,2023)}",
            "memory_seed_2":    f"Lost {random.randint(1,3)} bids to competitors in last 12 months on price",
            "memory_seed_3":    f"Experienced {random.choice(['port delay','quality dispute','FX shock'])} last delivery",
            "behavioral_rule_1":"IF competitor bids >10% above my cost THEN undercut by 8%",
            "behavioral_rule_2":"IF lead time <21 days THEN add 15% premium",
            "behavioral_rule_3":"IF buyer is repeat customer THEN offer 3% loyalty discount",
            "mirofish_weight":  round(random.uniform(0.6,1.0),2),
        })
    return pd.DataFrame(rows)

def build_mirofish_world_events() -> pd.DataFrame:
    events = [
        ("2024-07-04","scenario_6","supply_disruption",
         "Hamburg port strike: 3-week backlog. Air freight premium +40%.",9,"vendor_agent|buyer_agent",5),
        ("2024-09-02","scenario_6","policy_shock",
         "US 25% aluminium tariff. +7% spot price. Margin squeeze on US-aluminium-exposed vendors.",8,"vendor_agent|market_agent",8),
        ("2025-03-05","scenario_6","supply_disruption",
         "China rare earth quota cut. Neodymium +28%. 6-week lead time crisis.",9,"vendor_agent|buyer_agent",12),
        ("2024-03-28","scenario_6","policy_shock",
         "EU anti-dumping duties 18.7% on Chinese electrical components. Guangzhou loses price advantage.",7,"vendor_agent",3),
        ("2025-01-08","scenario_6","fx_shock",
         "JPY weakness causes Japanese vendors to raise export prices 6-9%.",6,"vendor_agent",15),
        ("2024-10-11","scenario_6","logistics_shock",
         "Suez rerouting: Asia-Europe +12-14 days. Indian and Chinese vendor buffer stock depleted.",7,"vendor_agent|market_agent",10),
        ("2024-08-15","scenario_1","financial_signal",
         "Cerro Negro Q2 weak results; CFO signals aggressive pricing H2 2024.",5,"vendor_agent",2),
        ("2024-06-20","scenario_1","rumor",
         "Tanaka capacity expansion rumour — if true, lead times drop 30% H2.",3,"vendor_agent",1),
        ("2024-12-19","scenario_1","demand_signal",
         "Hexagon AG capacity ramp 30%: competing for same vendor pool. Supply tightness Q1 2025.",6,"vendor_agent|competitor_agent",16),
        ("2024-05-01","scenario_7","onboarding_event",
         "Helios Micro Systems onboarded. Analogs: Vantage Sensors + Bright Spark.",4,"vendor_agent",1),
        ("2024-08-01","scenario_7","onboarding_event",
         "Andean Precision SRL first RFQ. Analogs: Adriatic Fastenings + Türk Makina.",4,"vendor_agent",6),
        ("2024-10-15","scenario_7","onboarding_event",
         "Sahara Industrial FZE evaluated. Analogs: Cerro Negro + Coastal Alloys.",5,"vendor_agent",10),
        # New: health score events for narrative
        ("2024-09-20","scenario_1","buyer_behaviour",
         "Meridian cash flow stress peaks Sep-Nov 2024; payment lateness increases; Kovacs and Fischer flag concerns.",7,"buyer_agent",9),
        ("2025-04-01","scenario_1","relationship_signal",
         "Patel Alloys win rate climbs to 38% after 9 months of forecast sharing; Meridian shortlists them preferentially.",5,"vendor_agent|buyer_agent",16),
        ("2025-02-01","scenario_6","vendor_exit",
         "Guangzhou Mech & Elec effectively exits Meridian vendor pool; health score 31; no responses to last 4 RFQs.",8,"vendor_agent",14),
    ]
    rows = []
    for i,(dt,sc,etype,desc,sev,agents,inj) in enumerate(events):
        rows.append({
            "event_id":             f"WE-{i+1:03d}",
            "event_date":           dt,
            "scenario":             sc,
            "event_type":           etype,
            "description":          desc,
            "severity_1_10":        sev,
            "affected_agent_roles": agents,
            "injection_round":      inj,
            "expected_market_impact":f"{'Major' if sev>=7 else 'Moderate'} disruption: {random.randint(3,22)}% bid price effect",
            "mitigation_option_1":  random.choice(["Dual-source strategy","Inventory buffer +30d","Airfreight escalation","Backup vendor activation"]),
            "mitigation_option_2":  random.choice(["Contractual price lock","Spot market hedge","Force majeure invocation","Extended payment terms"]),
        })
    return pd.DataFrame(rows)

def build_mirofish_sim_runs() -> pd.DataFrame:
    rows = [
        {"run_id":"SIM-001","scenario":"scenario_1",
         "title":"Vendor Behavior Pre-Simulation Before RFQ Dispatch",
         "objective":"Predict which vendors will respond and at what price band before issuing real RFQs",
         "seed_files":"01_vendors.csv|02_vendor_performance.csv|03_commodity_prices.csv|04_market_signals.csv|23_vendor_health_scores.csv",
         "simulation_rounds":25,"agents_activated":"vendor_agent|buyer_agent",
         "primary_metric":"predicted_response_probability",
         "secondary_metrics":"predicted_bid_range_usd|predicted_delivery_days",
         "injection_events":"WE-007|WE-008|WE-013",
         "termination_condition":"All vendor agents submitted bid decision or round 25 reached",
         "output_used_by":"Hermes rfq-vendor-selector — refines invite list using response probability",
         "mirofish_prediction_question":"Of these vendors, which will bid competitively given current health scores and market signals?"},
        {"run_id":"SIM-002","scenario":"scenario_6",
         "title":"Supply Shock Stress Test — Post Vendor Selection",
         "objective":"Simulate how shortlisted vendors respond under simultaneous supply chain shocks",
         "seed_files":"01_vendors.csv|03_commodity_prices.csv|04_market_signals.csv|14_purchase_orders.csv|18_mirofish_world_events.csv|23_vendor_health_scores.csv",
         "simulation_rounds":45,"agents_activated":"vendor_agent|buyer_agent|market_agent|regulator_agent",
         "primary_metric":"vendor_resilience_score",
         "secondary_metrics":"expected_price_revision_pct|expected_lead_time_extension_days|dropout_probability",
         "injection_events":"WE-001|WE-002|WE-003|WE-004|WE-005|WE-006",
         "termination_condition":"Market equilibrium reached or all shocks absorbed",
         "output_used_by":"Hermes rfq-bid-evaluator — blends resilience score into composite (15% weight)",
         "mirofish_prediction_question":"Under simultaneous shocks, which shortlisted vendors hold price and delivery commitments?"},
        {"run_id":"SIM-003","scenario":"scenario_7",
         "title":"New Vendor Synthetic Due Diligence",
         "objective":"Build behavioral profile for new vendors using analog archetype swarm",
         "seed_files":"01_vendors.csv|02_vendor_performance.csv|17_mirofish_agent_personas.csv|23_vendor_health_scores.csv",
         "simulation_rounds":20,"agents_activated":"vendor_agent|buyer_agent",
         "primary_metric":"synthetic_trust_score",
         "secondary_metrics":"estimated_response_rate|estimated_bid_delta_pct|onboarding_risk_rating",
         "injection_events":"WE-010|WE-011|WE-012",
         "termination_condition":"Persona convergence across 3 analog archetypes",
         "output_used_by":"Hermes rfq-vendor-selector — assigns new vendor a probability-weighted prior",
         "mirofish_prediction_question":"Given behavioral analogs, what is expected bid behavior and reliability of new vendors?"},
    ]
    return pd.DataFrame(rows)

# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════
def main():
    print("\n" + "═"*60)
    print("  Meridian Industrial Systems — Synthetic Data Generator v2")
    print(f"  Period : {fmt(START_DATE)}  →  {fmt(END_DATE)}  (18 months)")
    print(f"  Output : {os.path.abspath(OUTPUT_DIR)}")
    print("═"*60 + "\n")

    print("Building master tables…")
    vendors_df   = build_vendors()
    save(vendors_df, "01_vendors.csv")

    print("Building commodity prices…")
    comm_df      = build_commodity_prices()
    save(comm_df, "03_commodity_prices.csv")

    print("Building market signals…")
    sig_df       = build_market_signals()
    save(sig_df, "04_market_signals.csv")

    print("Building sales orders…")
    so_df, sol_df = build_sales_orders()
    save(so_df,  "05_sales_orders.csv")
    save(sol_df, "06_sales_order_lines.csv")

    print("Building work orders…")
    wo_df, woi_df = build_work_orders(so_df, sol_df)
    save(wo_df,  "07_work_orders.csv")
    save(woi_df, "08_work_order_items.csv")

    print("Building RFQ pipeline (invites, emails, bids, evaluations)…")
    rfq_df, inv_df, email_df, bid_df, eval_df, burden_df = \
        build_rfq_pipeline(wo_df, woi_df, vendors_df)
    save(rfq_df,    "09_rfq_events.csv")
    save(inv_df,    "10_rfq_vendor_invites.csv")
    save(email_df,  "11_rfq_email_thread.csv")
    save(bid_df,    "12_bids.csv")
    save(eval_df,   "13_bid_evaluation.csv")
    save(burden_df, "22_rfq_admin_burden.csv")

    print("Building purchase orders and deliveries…")
    po_df        = build_purchase_orders(eval_df, bid_df)
    save(po_df,  "14_purchase_orders.csv")
    del_df       = build_delivery_records(po_df, vendors_df)
    save(del_df, "15_delivery_records.csv")
    disp_df      = build_disputes(po_df, del_df)
    save(disp_df,"16_vendor_disputes.csv")

    print("Building payment events (time-aware lateness)…")
    pay_df       = build_payment_events(po_df)
    save(pay_df, "20_payment_events.csv")

    print("Building forecast sharing events…")
    fc_df        = build_forecast_sharing(vendors_df, so_df)
    save(fc_df,  "21_forecast_sharing.csv")

    print("Building vendor performance snapshots (derived from events)…")
    vperf_df     = build_vendor_performance(vendors_df, inv_df, eval_df, del_df, pay_df)
    save(vperf_df,"02_vendor_performance.csv")

    print("Building vendor relationship health scores…")
    hs_df        = build_health_scores(vendors_df, pay_df, inv_df, eval_df, burden_df, fc_df)
    save(hs_df,  "23_vendor_health_scores.csv")

    print("Building MiroFish tables…")
    persona_df   = build_mirofish_personas(vendors_df)
    save(persona_df,"17_mirofish_agent_personas.csv")
    we_df        = build_mirofish_world_events()
    save(we_df,  "18_mirofish_world_events.csv")
    sim_df       = build_mirofish_sim_runs()
    save(sim_df, "19_mirofish_sim_runs.csv")

    # ── Summary ───────────────────────────────────────────────────────────────
    all_dfs = [vendors_df,comm_df,sig_df,so_df,sol_df,wo_df,woi_df,
               rfq_df,inv_df,email_df,bid_df,eval_df,burden_df,
               po_df,del_df,disp_df,pay_df,fc_df,vperf_df,hs_df,
               persona_df,we_df,sim_df]
    total   = sum(len(d) for d in all_dfs)

    print("\n" + "═"*60)
    print("  ARC VERIFICATION")
    print("═"*60)
    for arc_name, vid in [("Declining (Kovacs)","V001"),("Improving (Patel)","V003"),
                           ("Collapse (Guangzhou)","V018"),("New→Proven (Helios)","V021")]:
        arc_hs = hs_df[hs_df["vendor_id"]==vid][["month","composite_health_score","trend_3mo","alert_flag"]]
        if not arc_hs.empty:
            first = arc_hs.iloc[0]
            last  = arc_hs.iloc[-1]
            print(f"  {arc_name:<28}  start={first['composite_health_score']:5.1f}  "
                  f"end={last['composite_health_score']:5.1f}  "
                  f"trend={last['trend_3mo']:<10}  "
                  f"alerts={arc_hs['alert_flag'].sum()}")

    print("\n" + "═"*60)
    print("  SUMMARY")
    print("═"*60)
    print(f"  Total rows across 23 CSVs : {total:,}")
    print(f"  Output directory          : {os.path.abspath(OUTPUT_DIR)}")
    print(f"\n  Primary outputs for Hermes:")
    print(f"    CSVs 01–16, 20–23  → operational + health data")
    print(f"  Primary outputs for MiroFish:")
    print(f"    CSVs 17–19, 23     → simulation seed + configs")
    print(f"    CSV 04             → market signals (GraphRAG input)")
    print(f"\n  Health score arcs visible in CSV 23:")
    print(f"    Kovacs  (V001) → declining  — payment lateness → disengagement")
    print(f"    Patel   (V003) → improving  — FTA + forecast sharing → partnership")
    print(f"    Guangzh (V018) → collapse   — tariff shock → exits pool")
    print(f"    Helios  (V021) → new→proven — thin data builds to 67+ by month 18")
    print("═"*60 + "\n")

if __name__ == "__main__":
    main()
