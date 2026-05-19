"""
generate_rfq_data.py
====================
Synthetic data generator for Hermes + MiroFish RFQ training program.
Company: Meridian Industrial Systems (CNC machines & robotic assembly cells)
Period:  18 months (configurable via START_DATE / END_DATE)

Outputs (all CSV, written to ./output/):
  01_vendors.csv                — master vendor registry (static)
  02_vendor_performance.csv     — monthly vendor KPI snapshots (18 × vendors)
  03_commodity_prices.csv       — weekly commodity price index (18 months)
  04_market_signals.csv         — news/signal events injested as MiroFish seeds
  05_sales_orders.csv           — SO header records
  06_sales_order_lines.csv      — SO line items
  07_work_orders.csv            — WO derived from SOs
  08_work_order_items.csv       — WO procurement line items
  09_rfq_events.csv             — one row per RFQ issued
  10_rfq_vendor_invites.csv     — one row per vendor invited per RFQ
  11_rfq_email_thread.csv       — full email conversation log
  12_bids.csv                   — vendor bid records
  13_bid_evaluation.csv         — scored / ranked bids per RFQ
  14_purchase_orders.csv        — POs raised from winning bids
  15_delivery_records.csv       — actual delivery vs promised
  16_vendor_disputes.csv        — dispute log over 18 months
  17_mirofish_agent_personas.csv— agent config rows for MiroFish
  18_mirofish_world_events.csv  — shock/signal events for simulation
  19_mirofish_sim_runs.csv      — simulation run metadata (scenarios 1,6,7)

Run:
  python3 generate_rfq_data.py

Requirements:
  pip install pandas numpy faker
"""

import os, random, math, hashlib
from datetime import date, timedelta, datetime
from collections import defaultdict

import numpy as np
import pandas as pd
from faker import Faker

# ── Configuration ────────────────────────────────────────────────────────────
random.seed(42)
np.random.seed(42)
fake = Faker()
Faker.seed(42)

START_DATE  = date(2024, 1, 1)
END_DATE    = date(2025, 6, 30)
OUTPUT_DIR  = "./output"
os.makedirs(OUTPUT_DIR, exist_ok=True)

N_VENDORS          = 24
N_SALES_ORDERS     = 210   # ~12/month × 18 months
N_RFQS             = 180   # most SOs trigger an RFQ
VENDORS_PER_RFQ    = 8     # invited
SHORTLIST_PER_RFQ  = 5     # finalized

# ── Helpers ──────────────────────────────────────────────────────────────────
def date_range(start, end, step_days=1):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=step_days)

def rand_date(start, end):
    delta = (end - start).days
    return start + timedelta(days=random.randint(0, delta))

def business_days_after(d, n):
    count = 0
    while count < n:
        d += timedelta(days=1)
        if d.weekday() < 5:
            count += 1
    return d

def fmt(d):
    return d.strftime("%Y-%m-%d")

def save(df, name):
    path = os.path.join(OUTPUT_DIR, name)
    df.to_csv(path, index=False)
    print(f"  ✓ {name:45s}  {len(df):>6,} rows")

# ── 1. VENDORS ────────────────────────────────────────────────────────────────
VENDOR_TEMPLATES = [
    # (name, category, country, city, behavioral_archetype, risk_tier, is_new)
    ("Kovacs Precision GmbH",         "Mechanical Parts",      "Germany",     "Stuttgart",  "reliable",           "low",    False),
    ("Tanaka Electrical KK",          "Electrical Components", "Japan",       "Osaka",      "conservative",       "low",    False),
    ("Patel Alloys Pvt Ltd",          "Raw Materials",         "India",       "Ahmedabad",  "relationship_focused","low",   False),
    ("Strömberg Hydraulics AB",       "Mechanical Parts",      "Sweden",      "Gothenburg", "reliable",           "low",    False),
    ("Cerro Negro Metals SA",         "Raw Materials",         "Chile",       "Santiago",   "aggressive_bidder",  "medium", False),
    ("Bright Spark Electronics Ltd",  "Electrical Components", "UK",          "Birmingham", "volatile",           "medium", False),
    ("Nakamura Tooling Co.",          "Mechanical Parts",      "Japan",       "Nagoya",     "conservative",       "low",    False),
    ("Delta Composites Inc.",         "Raw Materials",         "USA",         "Houston",    "aggressive_bidder",  "medium", False),
    ("Fischer & Söhne KG",            "Mechanical Parts",      "Germany",     "Munich",     "relationship_focused","low",   False),
    ("Adriatic Fastenings d.o.o.",    "Mechanical Parts",      "Croatia",     "Split",      "aggressive_bidder",  "medium", False),
    ("Solaris Power Components",      "Electrical Components", "Spain",       "Barcelona",  "volatile",           "medium", False),
    ("Indra Copper Works",            "Raw Materials",         "India",       "Mumbai",     "reliable",           "low",    False),
    ("Vantage Sensors GmbH",          "Electrical Components", "Germany",     "Dresden",    "conservative",       "low",    False),
    ("Coastal Alloys Pty Ltd",        "Raw Materials",         "Australia",   "Perth",      "relationship_focused","medium",False),
    ("Nordic Steel AS",               "Raw Materials",         "Norway",      "Bergen",     "reliable",           "low",    False),
    ("Precision Arc Systems",         "Electrical Components", "USA",         "Detroit",    "volatile",           "high",   False),
    ("Türk Makina A.Ş.",              "Mechanical Parts",      "Turkey",      "Bursa",      "aggressive_bidder",  "medium", False),
    ("Guangzhou Mech & Elec Co.",     "Electrical Components", "China",       "Guangzhou",  "aggressive_bidder",  "high",   False),
    ("Emerald Isle Castings Ltd",     "Mechanical Parts",      "Ireland",     "Cork",       "conservative",       "low",    False),
    ("Rajasthan Rare Earths Ltd",     "Raw Materials",         "India",       "Jaipur",     "relationship_focused","medium",False),
    # 4 new vendors (limited history)
    ("Helios Micro Systems",          "Electrical Components", "Israel",      "Tel Aviv",   "conservative",       "medium", True),
    ("Andean Precision SRL",          "Mechanical Parts",      "Argentina",   "Córdoba",    "aggressive_bidder",  "high",   True),
    ("Sahara Industrial FZE",         "Raw Materials",         "UAE",         "Dubai",      "volatile",           "high",   True),
    ("BalticTech UAB",                "Mechanical Parts",      "Lithuania",   "Vilnius",    "reliable",           "medium", True),
]

def build_vendors():
    rows = []
    for i, (name, cat, country, city, archetype, risk, is_new) in enumerate(VENDOR_TEMPLATES):
        vid = f"V{i+1:03d}"
        domain = name.lower().replace(" ","").replace("&","").replace(".","")[:12] + ".com"
        cname  = fake.name()
        rows.append({
            "vendor_id":               vid,
            "vendor_name":             name,
            "category":                cat,
            "country":                 country,
            "city":                    city,
            "contact_name":            cname,
            "contact_email":           f"{cname.split()[0].lower()}@{domain}",
            "phone":                   fake.phone_number(),
            "behavioral_archetype":    archetype,
            "risk_tier":               risk,
            "is_new_vendor":           is_new,
            "relationship_years":      0 if is_new else random.randint(2, 12),
            "certifications":          "|".join(random.sample(["ISO9001","ISO14001","AS9100","IATF16949","ISO45001","OHSAS18001"], k=random.randint(1,3))),
            "preferred_payment_terms": random.choice(["Net30","Net45","Net60","2/10 Net30","LC at sight"]),
            "base_price_index":        round(random.uniform(0.82, 1.18), 3),  # vs market
            "base_response_rate":      0.0 if is_new else round(random.uniform(0.55, 0.97), 2),
            "base_otd_rate":           0.0 if is_new else round(random.uniform(0.70, 0.98), 2),
            "base_quality_score":      0.0 if is_new else round(random.uniform(6.0, 9.8), 1),
            "financial_health_score":  round(random.uniform(5.5, 9.5), 1),
            "capacity_utilization_pct":round(random.uniform(55, 92), 1),
            "onboarded_date":          fmt(rand_date(date(2024,4,1), date(2024,10,1))) if is_new else fmt(rand_date(date(2012,1,1), date(2022,1,1))),
        })
    return pd.DataFrame(rows)

# ── 2. VENDOR PERFORMANCE (monthly) ──────────────────────────────────────────
def build_vendor_performance(vendors_df):
    rows = []
    months = []
    d = START_DATE.replace(day=1)
    while d <= END_DATE:
        months.append(d)
        # next month
        if d.month == 12:
            d = d.replace(year=d.year+1, month=1)
        else:
            d = d.replace(month=d.month+1)

    for _, v in vendors_df.iterrows():
        is_new  = v["is_new_vendor"]
        archetype = v["behavioral_archetype"]
        # trend multipliers to create realistic drift
        price_trend  = np.random.uniform(-0.002, 0.003)   # monthly drift in price index
        otd_trend    = np.random.uniform(-0.001, 0.001)
        for mo_idx, mo in enumerate(months):
            # new vendors get data only from their onboard month
            onboard = date.fromisoformat(v["onboarded_date"])
            if is_new and mo < onboard.replace(day=1):
                continue
            # base values with trend + noise
            pi = v["base_price_index"] + price_trend * mo_idx + np.random.normal(0, 0.012)
            pi = round(max(0.70, min(1.35, pi)), 3)

            # archetype-specific volatility
            vol_map = {"volatile":0.06,"aggressive_bidder":0.04,"conservative":0.01,"reliable":0.015,"relationship_focused":0.02}
            noise   = vol_map.get(archetype, 0.02)

            otd = v["base_otd_rate"] + otd_trend * mo_idx + np.random.normal(0, noise)
            otd = round(max(0.40, min(1.0, otd)), 2)
            rr  = v["base_response_rate"] + np.random.normal(0, 0.05)
            rr  = round(max(0.0, min(1.0, rr)), 2)
            qs  = v["base_quality_score"] + np.random.normal(0, 0.3)
            qs  = round(max(1.0, min(10.0, qs)), 1)
            bids_won   = random.randint(0, 4)
            bids_lost  = random.randint(0, 6)
            disputes   = 1 if random.random() < 0.04 else 0
            cap_util   = round(v["capacity_utilization_pct"] + np.random.normal(0, 4), 1)
            cap_util   = max(30, min(100, cap_util))

            rows.append({
                "snapshot_id":          f"VP-{v['vendor_id']}-{mo.strftime('%Y%m')}",
                "vendor_id":            v["vendor_id"],
                "vendor_name":          v["vendor_name"],
                "month":                fmt(mo),
                "price_index":          pi,
                "on_time_delivery_rate":otd,
                "response_rate":        rr,
                "quality_score":        qs,
                "bids_won":             bids_won,
                "bids_lost":            bids_lost,
                "disputes_raised":      disputes,
                "capacity_utilization": cap_util,
                "lead_time_days_avg":   round(random.uniform(7, 45) * (1.1 if archetype=="volatile" else 1.0), 1),
                "defect_rate_ppm":      round(max(0, np.random.normal(800 - qs*60, 120)), 0),
            })
    return pd.DataFrame(rows)

# ── 3. COMMODITY PRICES (weekly) ──────────────────────────────────────────────
COMMODITIES = [
    ("Steel HR Coil",       "USD/MT",  680,  0.0018, 0.025),
    ("Aluminium 6061",      "USD/MT",  2450, 0.0012, 0.020),
    ("Copper Wire Rod",     "USD/MT",  8900, 0.0020, 0.030),
    ("Neodymium Magnets",   "USD/KG",  68,   0.0030, 0.045),
    ("Stainless 316L",      "USD/MT",  3100, 0.0015, 0.022),
    ("HDPE Granules",       "USD/MT",  1150, 0.0010, 0.018),
    ("Titanium Sponge",     "USD/KG",  11.5, 0.0025, 0.035),
    ("PCB FR4 Laminate",    "USD/SQM", 4.2,  0.0008, 0.015),
    ("Servo Motor 5kW",     "USD/unit",1850, 0.0005, 0.012),
    ("Ball Bearing 6205",   "USD/unit",3.8,  0.0003, 0.010),
]

def build_commodity_prices():
    rows = []
    weeks = list(date_range(START_DATE, END_DATE, step_days=7))
    for comm, unit, base, trend, vol in COMMODITIES:
        price = base
        for w in weeks:
            # shock events baked in
            shock = 1.0
            # simulate tariff shock in month 9 (Sep 2024) on metals
            if comm in ("Steel HR Coil","Aluminium 6061") and date(2024,9,1) <= w <= date(2024,11,30):
                shock = 1.12
            # rare earth spike in month 14 (Mar 2025)
            if comm == "Neodymium Magnets" and date(2025,3,1) <= w <= date(2025,5,31):
                shock = 1.28
            price = price * (1 + trend + np.random.normal(0, vol)) * shock
            rows.append({
                "week_start":   fmt(w),
                "commodity":    comm,
                "unit":         unit,
                "price":        round(price, 3),
                "yoy_change_pct": None,   # filled later
                "shock_flag":   1 if shock > 1.0 else 0,
            })
    df = pd.DataFrame(rows)
    # fill yoy
    df["yoy_change_pct"] = None
    return df

# ── 4. MARKET SIGNALS ────────────────────────────────────────────────────────
MARKET_SIGNALS = [
    ("2024-02-14","news",       "Supply chain","Steel mills in Germany report 8% capacity reduction due to energy cost pressures; lead times for HR coil extending to 10-12 weeks.",   ["Steel HR Coil"],                -0.4, 0.85, 0.6),
    ("2024-03-28","policy",     "EU Trade",    "EU Commission introduces anti-dumping duties of 18.7% on certain Chinese electrical components effective April 15.",                  ["PCB FR4 Laminate","Servo Motor 5kW"], -0.7, 0.92, 0.8),
    ("2024-05-10","price_data", "LME",         "Copper touches 2-year high of $9,450/MT on LME amid supply constraints from Chilean mines; analysts expect sustained pressure.",      ["Copper Wire Rod"],               -0.5, 0.95, 0.7),
    ("2024-06-20","rumor",      "Industry",    "Unconfirmed reports suggest Tanaka Electrical considering capacity expansion; could reduce lead times H2 2024.",                      [],                                 0.3, 0.40, 0.3),
    ("2024-07-04","news",       "Geopolitical","Port of Hamburg faces 3-week backlog following dock worker strike; automotive and industrial shipments most affected.",                ["Steel HR Coil","Stainless 316L"],  -0.8, 0.90, 0.75),
    ("2024-08-15","financial_report","Reuters","Cerro Negro Metals Q2 results: revenue down 12% YoY; CFO hints at aggressive pricing to recapture market share.",                   ["Steel HR Coil","Aluminium 6061"],   0.2, 0.88, 0.5),
    ("2024-09-02","policy",     "US Trade",    "US imposes 25% tariff on aluminium imports from select Southeast Asian countries; global aluminium markets react with +7% spike.",   ["Aluminium 6061"],                -0.6, 0.94, 0.8),
    ("2024-10-11","news",       "Logistics",   "Suez Canal alternative routing adds 12-14 days to Asia-Europe shipments; Indian and Chinese vendor lead times under pressure.",       [],                                -0.5, 0.88, 0.65),
    ("2024-11-05","price_data", "Fastmarkets", "Stainless 316L premiums in Europe reach 18-month high; tightening scrap availability cited as primary driver.",                      ["Stainless 316L"],                -0.4, 0.92, 0.55),
    ("2024-12-19","news",       "Industry",    "Meridian competitor Hexagon AG announces 30% capacity ramp in Q1 2025; potential demand uplift for common vendor pool.",             [],                                -0.3, 0.75, 0.4),
    ("2025-01-08","news",       "Supply chain","Japanese yen weakness drives Tanaka Electrical and Nakamura Tooling to revise export price lists upward by 6-9%.",                   [],                                -0.4, 0.87, 0.5),
    ("2025-02-20","rumor",      "Market",      "Multiple buyers report Guangzhou Mech & Elec offering 20% below-market quotes; quality concerns flagged by two Tier-1 OEMs.",       [],                                -0.2, 0.50, 0.4),
    ("2025-03-05","price_data", "Argus Media", "Neodymium oxide prices surge 28% after China announces export quota cuts; servo motor and magnet supply chain in alarm.",            ["Neodymium Magnets","Servo Motor 5kW"], -0.9, 0.96, 0.9),
    ("2025-04-12","policy",     "G7",          "G7 nations agree on coordinated critical minerals strategy; rare earth import diversification incentives to begin Q3 2025.",         ["Neodymium Magnets","Titanium Sponge"],0.4, 0.80, 0.5),
    ("2025-05-01","news",       "Financial",   "Nordic Steel AS secures €150M green bond; investment earmarked for EAF capacity; analysts raise quality and delivery outlook.",       ["Steel HR Coil","Stainless 316L"],  0.6, 0.90, 0.4),
    ("2025-06-10","news",       "Geopolitical","India-EU FTA finalised; zero-duty access for Indian raw material exporters phased in over 5 years; Patel Alloys and Indra Copper to benefit.", ["Stainless 316L","Copper Wire Rod"],0.5, 0.88, 0.5),
]

def build_market_signals():
    rows = []
    for i, (dt, stype, src, text, comms, sent, cred, cascade) in enumerate(MARKET_SIGNALS):
        rows.append({
            "signal_id":           f"SIG-{i+1:03d}",
            "date":                dt,
            "signal_type":         stype,
            "source":              src,
            "headline":            text[:80],
            "full_text":           text,
            "affected_commodities":"|".join(comms),
            "sentiment_score":     sent,
            "credibility_score":   cred,
            "cascade_potential":   cascade,
            "mirofish_tag":        "scenario_6" if cascade >= 0.7 else ("scenario_1" if cascade >= 0.4 else "background"),
        })
    return pd.DataFrame(rows)

# ── 5 & 6. SALES ORDERS + LINES ──────────────────────────────────────────────
MATERIALS = [
    ("MECH-2201","Precision Ball Screw Assy 25mm",    "Mechanical Parts",   "pcs",  380,  420),
    ("MECH-2202","Linear Guide Rail 1500mm",          "Mechanical Parts",   "pcs",  145,  180),
    ("MECH-2203","Servo Coupling 14/19mm",            "Mechanical Parts",   "pcs",   28,   42),
    ("MECH-2204","Spindle Bearing Set NSK 7210",      "Mechanical Parts",   "pcs",  210,  260),
    ("MECH-2205","Cast Iron Bed Section Grade 300",   "Mechanical Parts",   "kg",    3.2,   4.8),
    ("ELEC-3301","Servo Drive 5.5kW Siemens-compat",  "Electrical Components","pcs",1650, 1950),
    ("ELEC-3302","Encoder 2500 PPR Differential",     "Electrical Components","pcs",  88,  115),
    ("ELEC-3303","Limit Switch IP67 Stainless",       "Electrical Components","pcs",  14,   22),
    ("ELEC-3304","PLC I/O Module 32-channel DI",      "Electrical Components","pcs", 340,  420),
    ("ELEC-3305","Power Supply 24VDC 20A DIN",        "Electrical Components","pcs",  95,  130),
    ("RAW-4401", "Steel HR Coil 3mm S235",            "Raw Materials",       "MT",  690,  780),
    ("RAW-4402", "Aluminium Extrusion 6061-T6",       "Raw Materials",       "kg",   2.9,   3.8),
    ("RAW-4403", "Copper Busbar 40×4mm",              "Raw Materials",       "m",    18,    26),
    ("RAW-4404", "Stainless 316L Sheet 2mm",          "Raw Materials",       "kg",   3.8,   4.9),
    ("RAW-4405", "HDPE Rod 50mm dia",                 "Raw Materials",       "m",    12,    18),
]

CUSTOMERS = [
    ("Hexagon AG","Germany"),("Mitsubishi Heavy",  "Japan"), ("Tata Advanced Systems","India"),
    ("Embraer S.A.","Brazil"),("Rolls-Royce PLC",  "UK"),   ("FANUC Corporation",    "Japan"),
    ("Siemens Energy","Germany"),("GE Aviation",    "USA"),  ("BHEL","India"),
    ("Airbus SE","France"),   ("Volkswagen AG",     "Germany"),("Bombardier Inc.","Canada"),
]

URGENCY_WEIGHTS = {"standard":0.55, "expedited":0.30, "critical":0.15}

def build_sales_orders(n=N_SALES_ORDERS):
    so_rows, sol_rows = [], []
    so_counter = 1
    for _ in range(n):
        so_id     = f"SO-2024-{so_counter:04d}"
        so_counter += 1
        cust, cust_country = random.choice(CUSTOMERS)
        urgency   = random.choices(list(URGENCY_WEIGHTS), weights=list(URGENCY_WEIGHTS.values()))[0]
        order_date= rand_date(START_DATE, END_DATE - timedelta(days=60))
        lead_days = {"standard":45,"expedited":25,"critical":14}[urgency]
        delivery  = business_days_after(order_date, lead_days + random.randint(-3,5))
        n_lines   = random.randint(2, 6)
        items     = random.sample(MATERIALS, k=min(n_lines, len(MATERIALS)))
        total     = 0
        for j, (mcode, mdesc, mcat, unit, lo, hi) in enumerate(items):
            qty   = random.randint(5, 120)
            price = round(random.uniform(lo, hi), 2)
            total += qty * price
            sol_rows.append({
                "so_line_id":     f"{so_id}-L{j+1:02d}",
                "sales_order_id": so_id,
                "line_no":        j+1,
                "material_code":  mcode,
                "description":    mdesc,
                "category":       mcat,
                "quantity":       qty,
                "unit":           unit,
                "unit_price_usd": price,
                "line_value_usd": round(qty * price, 2),
            })
        so_rows.append({
            "sales_order_id":  so_id,
            "customer":        cust,
            "customer_country":cust_country,
            "order_date":      fmt(order_date),
            "delivery_deadline":fmt(delivery),
            "urgency_level":   urgency,
            "total_value_usd": round(total, 2),
            "order_status":    "closed" if delivery < date.today() - timedelta(days=30) else "active",
        })
    return pd.DataFrame(so_rows), pd.DataFrame(sol_rows)

# ── 7 & 8. WORK ORDERS + ITEMS ────────────────────────────────────────────────
def build_work_orders(so_df, sol_df):
    wo_rows, woi_rows = [], []
    managers = ["Priya Nair", "Ravi Shankar", "Leena Mathew", "Arjun Desai", "Meena Krishnan"]
    for _, so in so_df.iterrows():
        if random.random() < 0.12:  # ~12% SOs don't trigger WO
            continue
        wo_id = "WO-" + so["sales_order_id"].replace("SO-","")
        lines = sol_df[sol_df["sales_order_id"] == so["sales_order_id"]]
        wo_rows.append({
            "work_order_id":     wo_id,
            "sales_order_ref":   so["sales_order_id"],
            "created_date":      fmt(date.fromisoformat(so["order_date"]) + timedelta(days=random.randint(1,3))),
            "procurement_manager": random.choice(managers),
            "urgency_level":     so["urgency_level"],
            "budget_ceiling_usd":round(so["total_value_usd"] * random.uniform(1.05, 1.18), 2),
            "rfq_required":      True,
            "status":            random.choice(["completed","in_progress","pending"]) if so["order_status"]=="active" else "completed",
        })
        for _, line in lines.iterrows():
            target = round(line["unit_price_usd"] * random.uniform(0.88, 1.02), 2)
            req_by = date.fromisoformat(so["delivery_deadline"]) - timedelta(days=random.randint(7,18))
            woi_rows.append({
                "wo_item_id":          f"{wo_id}-I{line['line_no']:02d}",
                "work_order_id":       wo_id,
                "material_code":       line["material_code"],
                "description":         line["description"],
                "category":            line["category"],
                "quantity":            line["quantity"],
                "unit":                line["unit"],
                "target_unit_price_usd":target,
                "required_by_date":    fmt(req_by),
                "preferred_vendor_category": line["category"],
            })
    return pd.DataFrame(wo_rows), pd.DataFrame(woi_rows)

# ── 9–13. RFQ EVENTS, INVITES, EMAILS, BIDS, EVALUATION ─────────────────────
VENDOR_INVITE_LOGIC = {
    "Mechanical Parts":      [v[0] for v in VENDOR_TEMPLATES if v[1]=="Mechanical Parts"],
    "Electrical Components": [v[0] for v in VENDOR_TEMPLATES if v[1]=="Electrical Components"],
    "Raw Materials":         [v[0] for v in VENDOR_TEMPLATES if v[1]=="Raw Materials"],
}

def vendor_id_by_name(vendors_df, name):
    row = vendors_df[vendors_df["vendor_name"]==name]
    return row["vendor_id"].values[0] if len(row) else None

def build_rfq_data(wo_df, woi_df, vendors_df):
    rfq_rows, inv_rows, email_rows, bid_rows, eval_rows = [], [], [], [], []
    rfq_counter = 1

    vname_to_id = dict(zip(vendors_df["vendor_name"], vendors_df["vendor_id"]))
    vid_to_v    = vendors_df.set_index("vendor_id").to_dict("index")

    # Build lookup: work_order_id → list of item rows
    woi_grouped = woi_df.groupby("work_order_id")

    for _, wo in wo_df.iterrows():
        wo_id = wo["work_order_id"]
        if wo_id not in woi_grouped.groups:
            continue
        items = woi_grouped.get_group(wo_id)
        # determine dominant category
        cat = items["category"].mode()[0]
        pool_names = VENDOR_INVITE_LOGIC.get(cat, [])
        if len(pool_names) < 5:
            continue

        rfq_id   = f"RFQ-{rfq_counter:04d}"
        rfq_counter += 1
        issue_dt = date.fromisoformat(wo["created_date"]) + timedelta(days=random.randint(1,2))
        deadline = business_days_after(issue_dt, random.randint(7,14))
        target_p = items["target_unit_price_usd"].mean()

        # select vendors to invite
        invited_names = random.sample(pool_names, k=min(VENDORS_PER_RFQ, len(pool_names)))
        invited_ids   = [vname_to_id[n] for n in invited_names if n in vname_to_id]

        # MiroFish scenario 1 flag
        mf_flag = "scenario_1" if random.random() < 0.15 else ""

        rfq_rows.append({
            "rfq_id":               rfq_id,
            "work_order_ref":       wo["work_order_id"],
            "category":             cat,
            "issue_date":           fmt(issue_dt),
            "bid_deadline":         fmt(deadline),
            "n_vendors_invited":    len(invited_ids),
            "urgency":              wo["urgency_level"],
            "estimated_value_usd":  round(target_p * items["quantity"].sum(), 2),
            "mirofish_flag":        mf_flag,
            "status":               "closed",
        })

        # invites + email thread + bids
        shortlist = []
        for vid in invited_ids:
            v = vid_to_v.get(vid, {})
            arch = v.get("behavioral_archetype","reliable")
            inv_rows.append({
                "invite_id":   f"{rfq_id}-INV-{vid}",
                "rfq_id":      rfq_id,
                "vendor_id":   vid,
                "vendor_name": v.get("vendor_name",""),
                "invited_date":fmt(issue_dt),
                "responded":   None,  # set later
            })

            # response probability by archetype
            rp_map = {"aggressive_bidder":0.82,"conservative":0.68,"reliable":0.88,"volatile":0.60,"relationship_focused":0.78}
            responded = random.random() < rp_map.get(arch, 0.75)

            # outbound RFQ email
            thread_base = len(email_rows)
            email_rows.append({
                "email_id":     f"EML-{len(email_rows)+1:05d}",
                "rfq_id":       rfq_id,
                "vendor_id":    vid,
                "direction":    "outbound",
                "timestamp":    fmt(issue_dt) + " 09:15:00",
                "from_email":   "procurement@meridian-industrial.com",
                "to_email":     v.get("contact_email",""),
                "subject":      f"Request for Quotation – {rfq_id} – {cat}",
                "body_snippet": f"Dear {v.get('contact_name','').split()[0]}, please find attached our RFQ {rfq_id} for {cat} components. Bid deadline: {fmt(deadline)}. Target delivery: {fmt(deadline + timedelta(days=random.randint(14,30)))}. Please confirm receipt.",
                "bid_amount_usd":None,
                "delivery_days": None,
            })

            # acknowledgement (sometimes)
            if responded and random.random() < 0.70:
                ack_dt = issue_dt + timedelta(days=random.randint(1,2))
                email_rows.append({
                    "email_id":     f"EML-{len(email_rows)+1:05d}",
                    "rfq_id":       rfq_id,
                    "vendor_id":    vid,
                    "direction":    "inbound",
                    "timestamp":    fmt(ack_dt) + " " + f"{random.randint(8,17):02d}:{random.randint(0,59):02d}:00",
                    "from_email":   v.get("contact_email",""),
                    "to_email":     "procurement@meridian-industrial.com",
                    "subject":      f"Re: Request for Quotation – {rfq_id}",
                    "body_snippet": f"Thank you for your RFQ. We confirm receipt and will submit our competitive quotation before {fmt(deadline)}. We are pleased to support Meridian's requirements.",
                    "bid_amount_usd":None,
                    "delivery_days": None,
                })

            # update invite responded
            inv_rows[-1]["responded"] = responded

            if not responded:
                continue

            # bid email
            bid_dt = deadline - timedelta(days=random.randint(0,3))
            price_delta = {"aggressive_bidder": random.uniform(-0.14,-0.05),
                           "conservative":      random.uniform(-0.02, 0.06),
                           "volatile":          random.uniform(-0.18, 0.15),
                           "reliable":          random.uniform(-0.05, 0.03),
                           "relationship_focused": random.uniform(-0.07, 0.02)}[arch]
            bid_unit  = round(target_p * (1 + price_delta), 2)
            bid_total = round(bid_unit * items["quantity"].sum(), 2)
            del_days  = random.randint(10, 55)

            email_rows.append({
                "email_id":     f"EML-{len(email_rows)+1:05d}",
                "rfq_id":       rfq_id,
                "vendor_id":    vid,
                "direction":    "inbound",
                "timestamp":    fmt(bid_dt) + " " + f"{random.randint(8,17):02d}:{random.randint(0,59):02d}:00",
                "from_email":   v.get("contact_email",""),
                "to_email":     "procurement@meridian-industrial.com",
                "subject":      f"Quotation Submission – {rfq_id} – {v.get('vendor_name','')}",
                "body_snippet": f"Dear Procurement Team, please find our quotation for {rfq_id}. Unit price: USD {bid_unit:,.2f}. Total: USD {bid_total:,.2f}. Lead time: {del_days} days. Valid 30 days. We look forward to your favourable consideration.",
                "bid_amount_usd": bid_total,
                "delivery_days": del_days,
            })

            # quality + relationship score for evaluation
            qual = v.get("base_quality_score", 7.0)
            rel  = min(10, v.get("relationship_years", 0) * 0.7 + 4)

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
                "price_delta_pct": round(price_delta * 100, 2),
                "archetype":       arch,
            })

            shortlist.append({
                "vendor_id":    vid,
                "vendor_name":  v.get("vendor_name",""),
                "bid_total":    bid_total,
                "delivery_days":del_days,
                "quality_score":qual,
                "relationship": rel,
                "price_delta":  price_delta,
            })

        # evaluation + ranking
        if shortlist:
            # weighted score: price 40%, delivery 30%, quality 20%, relationship 10%
            max_bid = max(s["bid_total"] for s in shortlist)
            min_del = min(s["delivery_days"] for s in shortlist)
            rfq_evals = []
            for s in shortlist:
                price_score = (1 - s["bid_total"] / max_bid) * 100
                del_score   = (min_del / s["delivery_days"]) * 100
                qual_score  = s["quality_score"] * 10
                rel_score   = s["relationship"] * 10
                composite   = round(0.40*price_score + 0.30*del_score + 0.20*qual_score + 0.10*rel_score, 2)
                rfq_evals.append({
                    "eval_id":            f"EVAL-{rfq_id}-{s['vendor_id']}",
                    "rfq_id":             rfq_id,
                    "vendor_id":          s["vendor_id"],
                    "vendor_name":        s["vendor_name"],
                    "price_score":        round(price_score, 2),
                    "delivery_score":     round(del_score, 2),
                    "quality_score":      round(qual_score, 2),
                    "relationship_score": round(rel_score, 2),
                    "composite_score":    composite,
                    "selected":           False,
                })
            # mark top 5
            rfq_evals.sort(key=lambda x: x["composite_score"], reverse=True)
            for e in rfq_evals[:SHORTLIST_PER_RFQ]:
                e["selected"] = True
            eval_rows.extend(rfq_evals)

    return (pd.DataFrame(rfq_rows), pd.DataFrame(inv_rows),
            pd.DataFrame(email_rows), pd.DataFrame(bid_rows),
            pd.DataFrame(eval_rows))

# ── 14. PURCHASE ORDERS ───────────────────────────────────────────────────────
def build_purchase_orders(eval_df, bid_df):
    rows = []
    selected = eval_df[eval_df["selected"] == True]
    for _, e in selected.iterrows():
        bid = bid_df[(bid_df["rfq_id"]==e["rfq_id"]) & (bid_df["vendor_id"]==e["vendor_id"])]
        if bid.empty:
            continue
        b = bid.iloc[0]
        po_date = date.today() - timedelta(days=random.randint(10, 300))
        rows.append({
            "po_id":            f"PO-{e['rfq_id']}-{e['vendor_id']}",
            "rfq_id":           e["rfq_id"],
            "vendor_id":        e["vendor_id"],
            "vendor_name":      e["vendor_name"],
            "po_date":          fmt(po_date),
            "po_value_usd":     b["bid_total_usd"],
            "promised_delivery":fmt(po_date + timedelta(days=int(b["delivery_days"]))),
            "payment_terms":    random.choice(["Net30","Net45","Net60"]),
            "status":           random.choice(["delivered","in_transit","pending","cancelled"]),
        })
    return pd.DataFrame(rows)

# ── 15. DELIVERY RECORDS ──────────────────────────────────────────────────────
def build_delivery_records(po_df, vendors_df):
    rows = []
    vid_to_otd = dict(zip(vendors_df["vendor_id"], vendors_df["base_otd_rate"]))
    for _, po in po_df.iterrows():
        if po["status"] in ("pending","cancelled"):
            continue
        otd = vid_to_otd.get(po["vendor_id"], 0.80)
        on_time = random.random() < otd
        promised = date.fromisoformat(po["promised_delivery"])
        delta = 0 if on_time else random.randint(1, 21)
        actual = promised + timedelta(days=delta)
        rows.append({
            "delivery_id":      f"DEL-{po['po_id']}",
            "po_id":            po["po_id"],
            "vendor_id":        po["vendor_id"],
            "promised_date":    po["promised_delivery"],
            "actual_date":      fmt(actual),
            "days_late":        delta,
            "on_time":          on_time,
            "condition":        random.choices(["accepted","accepted_with_note","rejected"],weights=[0.82,0.12,0.06])[0],
            "quality_issue":    random.random() < 0.06,
            "invoice_value_usd":round(po["po_value_usd"] * random.uniform(0.97, 1.02), 2),
        })
    return pd.DataFrame(rows)

# ── 16. DISPUTES ──────────────────────────────────────────────────────────────
def build_disputes(po_df, delivery_df):
    rows = []
    bad = delivery_df[(delivery_df["days_late"] > 7) | (delivery_df["quality_issue"]==True)]
    for _, d in bad.iterrows():
        if random.random() < 0.35:
            rows.append({
                "dispute_id":   f"DISP-{d['delivery_id']}",
                "po_id":        d["po_id"],
                "vendor_id":    d["vendor_id"],
                "dispute_date": d["actual_date"],
                "reason":       "late_delivery" if d["days_late"] > 7 else "quality_rejection",
                "claimed_usd":  round(d["invoice_value_usd"] * random.uniform(0.05, 0.20), 2),
                "resolved":     random.random() < 0.75,
                "resolution":   random.choice(["credit_note","replacement","penalty_deducted","rejected_claim"]),
            })
    return pd.DataFrame(rows)

# ── 17. MIROFISH AGENT PERSONAS ───────────────────────────────────────────────
PERSONA_TEMPLATES = [
    # role, scenario_tag, personality summary, decision_style
    ("vendor_agent",  "scenario_1", "Price-aggressive, monitors competitor bids via industry contacts, willing to undercut 15% to win volume",    "opportunistic"),
    ("vendor_agent",  "scenario_1", "Relationship-driven, rarely drops below cost, expects multi-year contracts, risk averse",                    "risk_averse"),
    ("vendor_agent",  "scenario_1", "Volatile pricing, capacity constraints in Q3, likely to withdraw if lead time < 30 days",                    "volatile"),
    ("vendor_agent",  "scenario_1", "Conservative, ISO-certified, slow to adapt pricing, prioritises on-time reputation",                         "risk_averse"),
    ("vendor_agent",  "scenario_1", "New entrant, unknown to buyer, will underbid to gain reference customer",                                    "aggressive"),
    ("vendor_agent",  "scenario_6", "Port-dependent, highly exposed to Hamburg delays, has 3 weeks buffer stock",                                 "risk_averse"),
    ("vendor_agent",  "scenario_6", "Diversified logistics, can switch to air freight +12% cost, resilient to port disruptions",                  "collaborative"),
    ("vendor_agent",  "scenario_6", "Single-source raw material from China, tariff spike will trigger 18% price increase within 2 weeks",         "risk_averse"),
    ("vendor_agent",  "scenario_6", "Has rare earth inventory hedge until Q2 2025, can hold price for 60 days",                                   "opportunistic"),
    ("vendor_agent",  "scenario_7", "Unknown vendor, bootstrapped from 2 analogous archived vendor profiles, medium trust prior",                 "collaborative"),
    ("buyer_agent",   "all",        "Procurement manager, prioritises OTD over price by 1.5x, prefers suppliers with ISO9001",                    "risk_averse"),
    ("buyer_agent",   "all",        "Category manager Electrical, aggressive on price, tracks LME weekly, benchmarks bids against index",         "opportunistic"),
    ("buyer_agent",   "all",        "CFO delegate, hard budget ceiling, escalates if PO exceeds target by >8%",                                   "risk_averse"),
    ("market_agent",  "scenario_6", "LME copper desk analyst, publishes weekly price curves that vendors reference",                              "collaborative"),
    ("market_agent",  "scenario_6", "Freight forwarder, has live Suez/Hamburg routing data, advises buyer on lead time risk",                     "collaborative"),
    ("regulator_agent","scenario_6","EU trade desk, monitoring tariff compliance, issues guidance within 5 days of policy change",                "risk_averse"),
    ("competitor_agent","all",      "Hexagon AG procurement, competes for same vendor capacity, willing to pay 5% premium for exclusivity",       "aggressive"),
]

def build_mirofish_personas(vendors_df):
    rows = []
    for i, (role, tag, persona, style) in enumerate(PERSONA_TEMPLATES):
        pid = f"AGENT-{i+1:03d}"
        # try to bind to a vendor
        vendor_id = ""
        if role == "vendor_agent" and i < len(vendors_df):
            vendor_id = vendors_df.iloc[i % len(vendors_df)]["vendor_id"]
        rows.append({
            "agent_id":          pid,
            "role":              role,
            "scenario_tag":      tag,
            "persona_summary":   persona,
            "decision_style":    style,
            "bound_vendor_id":   vendor_id,
            "trust_network":     "|".join([f"AGENT-{j+1:03d}" for j in random.sample(range(len(PERSONA_TEMPLATES)), k=min(3, len(PERSONA_TEMPLATES)-1)) if j != i]),
            "memory_seed_1":     f"Won contract worth €{random.randint(200,800)}K in {random.randint(2021,2023)} after aggressive bid",
            "memory_seed_2":     f"Lost {random.randint(1,3)} bids to competitors in last 12 months due to price",
            "memory_seed_3":     f"Experienced {random.choice(['port delay','quality dispute','currency shock'])} impacting last delivery",
            "behavioral_rule_1": "IF competitor bids > 10% above my cost THEN undercut by 8%",
            "behavioral_rule_2": "IF lead time requested < 21 days THEN add 15% premium",
            "behavioral_rule_3": "IF buyer is repeat customer THEN offer 3% loyalty discount",
            "mirofish_weight":   round(random.uniform(0.6, 1.0), 2),
        })
    return pd.DataFrame(rows)

# ── 18. MIROFISH WORLD EVENTS ─────────────────────────────────────────────────
def build_mirofish_world_events():
    events = [
        # (date, scenario, event_type, description, severity, affected_agents_hint, injection_round)
        ("2024-07-04","scenario_6","supply_disruption","Hamburg port strike: 3-week backlog. Rerouting adds 12-14 days. Air freight premium +40%.",9,"vendor_agent|buyer_agent",5),
        ("2024-09-02","scenario_6","policy_shock","US 25% aluminium tariff. Immediate +7% spot price. Vendors with US aluminium exposure face margin squeeze.",8,"vendor_agent|market_agent",8),
        ("2025-03-05","scenario_6","supply_disruption","China rare earth export quota cut. Neodymium +28%. Servo motor supply chain in 6-week lead time crisis.",9,"vendor_agent|buyer_agent",12),
        ("2024-03-28","scenario_6","policy_shock","EU anti-dumping duties 18.7% on Chinese electrical components. Guangzhou Mech & Elec loses price advantage.",7,"vendor_agent",3),
        ("2025-01-08","scenario_6","fx_shock","JPY weakness causes Japanese vendors to raise export prices 6-9%. Tanaka and Nakamura revise price lists.",6,"vendor_agent",15),
        ("2024-10-11","scenario_6","logistics_shock","Suez Canal rerouting: Asia-Europe +12-14 days. Indian and Chinese vendors buffer stock depleted.",7,"vendor_agent|market_agent",10),
        # scenario 1: pre-simulation signals
        ("2024-08-15","scenario_1","financial_signal","Cerro Negro Metals Q2 weak results; CFO signals aggressive pricing strategy H2 2024.",5,"vendor_agent",2),
        ("2024-06-20","scenario_1","rumor","Tanaka Electrical capacity expansion rumour. If true, lead times drop 30% H2 2024.",3,"vendor_agent",1),
        ("2024-12-19","scenario_1","demand_signal","Hexagon AG capacity ramp 30%: competing for same vendor pool. Supply tightness expected Q1 2025.",6,"vendor_agent|competitor_agent",16),
        # scenario 7: new vendor onboarding
        ("2024-05-01","scenario_7","onboarding_event","Helios Micro Systems onboarded as Tier-2 candidate. Analog profiles: Vantage Sensors + Bright Spark Electronics.",4,"vendor_agent",1),
        ("2024-08-01","scenario_7","onboarding_event","Andean Precision SRL first RFQ participation. Analogues: Adriatic Fastenings + Türk Makina.",4,"vendor_agent",6),
        ("2024-10-15","scenario_7","onboarding_event","Sahara Industrial FZE evaluated. Analog: Cerro Negro Metals + Coastal Alloys.",5,"vendor_agent",10),
    ]
    rows = []
    for i, (dt, sc, etype, desc, sev, agents, inj_round) in enumerate(events):
        rows.append({
            "event_id":              f"WE-{i+1:03d}",
            "event_date":            dt,
            "scenario":              sc,
            "event_type":            etype,
            "description":           desc,
            "severity_1_10":         sev,
            "affected_agent_roles":  agents,
            "injection_round":       inj_round,
            "expected_market_impact":f"{'Price increase' if sev>=7 else 'Minor disruption'}: {random.randint(3,22)}% effect on bid prices",
            "mitigation_option_1":   random.choice(["Dual-source strategy","Inventory buffer +30 days","Airfreight escalation","Alternative vendor activation"]),
            "mitigation_option_2":   random.choice(["Contractual price lock","Spot market hedge","Expedited onboarding of backup vendor","Force majeure invocation"]),
        })
    return pd.DataFrame(rows)

# ── 19. MIROFISH SIMULATION RUNS ──────────────────────────────────────────────
def build_mirofish_sim_runs():
    rows = [
        {
            "run_id":             "SIM-001",
            "scenario":           "scenario_1",
            "title":              "Vendor Behavior Pre-Simulation Before RFQ Dispatch",
            "objective":          "Predict which of 8 invited vendors will respond, at what price band, within what SLA — before issuing real RFQs",
            "seed_files":         "01_vendors.csv|03_commodity_prices.csv|04_market_signals.csv|17_mirofish_agent_personas.csv",
            "simulation_rounds":  30,
            "agents_activated":   "vendor_agent|buyer_agent",
            "primary_metric":     "predicted_response_probability",
            "secondary_metrics":  "predicted_bid_range_usd|predicted_delivery_days",
            "injection_events":   "WE-007|WE-008",
            "termination_condition":"All vendor agents have submitted bid decision or round 30 reached",
            "output_used_by":     "Hermes vendor_selector.skill — narrows invite list from 12 to 8",
            "mirofish_prediction_question":"Of these 12 vendors, which 8 are most likely to bid competitively given current market signals?",
        },
        {
            "run_id":             "SIM-002",
            "scenario":           "scenario_6",
            "title":              "Supply Shock Stress Test — Post Vendor Selection",
            "objective":          "After 5 vendors shortlisted, simulate how each performs under Hamburg port strike + rare earth shock",
            "seed_files":         "01_vendors.csv|03_commodity_prices.csv|04_market_signals.csv|14_purchase_orders.csv|18_mirofish_world_events.csv",
            "simulation_rounds":  50,
            "agents_activated":   "vendor_agent|buyer_agent|market_agent|regulator_agent|logistics_agent",
            "primary_metric":     "vendor_resilience_score",
            "secondary_metrics":  "expected_price_revision_pct|expected_lead_time_extension_days|dropout_probability",
            "injection_events":   "WE-001|WE-002|WE-003|WE-004|WE-005|WE-006",
            "termination_condition":"Market equilibrium reached or all shocks absorbed",
            "output_used_by":     "Hermes bid_evaluator.skill — adds resilience weight to final scoring",
            "mirofish_prediction_question":"Under simultaneous Hamburg disruption + rare earth shock, which of the 5 shortlisted vendors can hold price and delivery commitments?",
        },
        {
            "run_id":             "SIM-003",
            "scenario":           "scenario_7",
            "title":              "New Vendor Synthetic Due Diligence",
            "objective":          "Construct behavioral profile for new vendors with no transaction history using analog archetype swarm",
            "seed_files":         "01_vendors.csv|02_vendor_performance.csv|17_mirofish_agent_personas.csv|18_mirofish_world_events.csv",
            "simulation_rounds":  25,
            "agents_activated":   "vendor_agent|buyer_agent",
            "primary_metric":     "synthetic_trust_score",
            "secondary_metrics":  "estimated_response_rate|estimated_bid_delta_pct|onboarding_risk_rating",
            "injection_events":   "WE-010|WE-011|WE-012",
            "termination_condition":"Persona convergence across 3 analog archetypes",
            "output_used_by":     "Hermes vendor_selector.skill — assigns new vendor a probability-weighted scoring prior",
            "mirofish_prediction_question":"Given behavioral analogs, what is the expected bid behavior and reliability of Helios Micro Systems, Andean Precision, and Sahara Industrial in their first RFQ?",
        },
    ]
    return pd.DataFrame(rows)

# ── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    print("\n" + "═"*55)
    print("  Meridian Industrial Systems — Synthetic Data Generator")
    print(f"  Period: {fmt(START_DATE)}  →  {fmt(END_DATE)}  (18 months)")
    print("═"*55 + "\n")

    print("Building master tables…")
    vendors_df   = build_vendors()
    save(vendors_df, "01_vendors.csv")

    print("Building vendor performance snapshots…")
    vperf_df     = build_vendor_performance(vendors_df)
    save(vperf_df, "02_vendor_performance.csv")

    print("Building commodity price series…")
    comm_df      = build_commodity_prices()
    save(comm_df, "03_commodity_prices.csv")

    print("Building market signals…")
    signals_df   = build_market_signals()
    save(signals_df, "04_market_signals.csv")

    print("Building sales orders…")
    so_df, sol_df = build_sales_orders()
    save(so_df,  "05_sales_orders.csv")
    save(sol_df, "06_sales_order_lines.csv")

    print("Building work orders…")
    wo_df, woi_df = build_work_orders(so_df, sol_df)
    save(wo_df,  "07_work_orders.csv")
    save(woi_df, "08_work_order_items.csv")

    print("Building RFQ data (events, invites, emails, bids, evaluations)…")
    rfq_df, inv_df, email_df, bid_df, eval_df = build_rfq_data(wo_df, woi_df, vendors_df)
    save(rfq_df,   "09_rfq_events.csv")
    save(inv_df,   "10_rfq_vendor_invites.csv")
    save(email_df, "11_rfq_email_thread.csv")
    save(bid_df,   "12_bids.csv")
    save(eval_df,  "13_bid_evaluation.csv")

    print("Building purchase orders and delivery records…")
    po_df        = build_purchase_orders(eval_df, bid_df)
    save(po_df,  "14_purchase_orders.csv")

    del_df       = build_delivery_records(po_df, vendors_df)
    save(del_df, "15_delivery_records.csv")

    disp_df      = build_disputes(po_df, del_df)
    save(disp_df,"16_vendor_disputes.csv")

    print("Building MiroFish tables…")
    persona_df   = build_mirofish_personas(vendors_df)
    save(persona_df, "17_mirofish_agent_personas.csv")

    we_df        = build_mirofish_world_events()
    save(we_df,  "18_mirofish_world_events.csv")

    sim_df       = build_mirofish_sim_runs()
    save(sim_df, "19_mirofish_sim_runs.csv")

    print("\n" + "═"*55)
    print("  Summary")
    print("═"*55)
    print(f"  Vendors:             {len(vendors_df):>6,}  ({vendors_df[vendors_df['is_new_vendor']==True].shape[0]} new)")
    print(f"  Perf snapshots:      {len(vperf_df):>6,}  (monthly × vendor)")
    print(f"  Commodity weeks:     {len(comm_df):>6,}  ({comm_df['commodity'].nunique()} commodities)")
    print(f"  Sales orders:        {len(so_df):>6,}")
    print(f"  SO lines:            {len(sol_df):>6,}")
    print(f"  Work orders:         {len(wo_df):>6,}")
    print(f"  WO items:            {len(woi_df):>6,}")
    print(f"  RFQs issued:         {len(rfq_df):>6,}")
    print(f"  Vendor invites:      {len(inv_df):>6,}")
    print(f"  Email records:       {len(email_df):>6,}")
    print(f"  Bids received:       {len(bid_df):>6,}")
    print(f"  Bid evaluations:     {len(eval_df):>6,}")
    print(f"  Purchase orders:     {len(po_df):>6,}")
    print(f"  Delivery records:    {len(del_df):>6,}")
    print(f"  Disputes:            {len(disp_df):>6,}")
    print(f"  MiroFish personas:   {len(persona_df):>6,}")
    print(f"  World events:        {len(we_df):>6,}")
    print(f"  Sim run configs:     {len(sim_df):>6,}")
    total = (len(vendors_df)+len(vperf_df)+len(comm_df)+len(signals_df)+
             len(so_df)+len(sol_df)+len(wo_df)+len(woi_df)+
             len(rfq_df)+len(inv_df)+len(email_df)+len(bid_df)+len(eval_df)+
             len(po_df)+len(del_df)+len(disp_df)+len(persona_df)+len(we_df)+len(sim_df))
    print(f"\n  Total rows across 19 CSVs: {total:,}")
    print(f"  Output directory:          {os.path.abspath(OUTPUT_DIR)}")
    print("\n  Files are ready for:")
    print("    • Hermes agent training  →  CSVs 01–16")
    print("    • MiroFish seed upload   →  CSVs 17–19 + 01, 03, 04")
    print("    • Scenario 1 (vendor pre-sim)   →  SIM-001")
    print("    • Scenario 6 (supply shock)     →  SIM-002")
    print("    • Scenario 7 (new vendor)       →  SIM-003")
    print("═"*55 + "\n")

if __name__ == "__main__":
    main()
