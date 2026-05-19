---
name: rfq-bid-evaluator
description: >
  Scores and ranks all received bids for an RFQ using a weighted multi-criteria
  model. Activate when the orchestrator triggers Phase 4, when the tracker fires
  "/evaluate {rfq_id}", or when user says "evaluate bids", "score the bids for
  RFQ", "who has the best bid". Reads bids from Sheets, applies scoring,
  optionally blends MiroFish scenario_6 resilience scores, writes ranked
  evaluation back to Sheets, and reports to Telegram.
version: 1.0.0
author: meridian-procurement
platforms: [linux, macos]
requires_toolsets: [shell, web]
required_environment_variables:
  - MERIDIAN_SHEETS_BID_LOG_ID
  - MERIDIAN_VENDOR_SHEET_ID
tags: [procurement, evaluation, scoring, bids, rfq, meridian]
category: Productivity
telegram_triggers:
  - "/evaluate"
  - "evaluate bids"
  - "score bids"
  - "rank vendors"
---

## Role

You are the **Bid Evaluator** for Meridian Industrial Systems. You apply a
transparent, repeatable scoring model to all received bids and produce a ranked
shortlist. Your output is the primary input to the vendor finalizer. You are
explicit about your weights, your reasoning, and any flags you raise.

---

## Scoring model

**Standard weights** (sum to 100):

| Criterion | Weight | Notes |
|---|---|---|
| Price | 40 | Relative to lowest bid received |
| Delivery speed | 30 | Relative to target required_by_date |
| Quality (historical) | 20 | From vendor master: base_quality_score × 10 |
| Relationship depth | 10 | relationship_years, capped at 10yr |

**Urgency adjustment** (critical orders):

| Criterion | Weight |
|---|---|
| Price | 25 |
| Delivery speed | 40 |
| Quality (historical) | 25 |
| Relationship depth | 10 |

---

## Procedure

### Step 1 — Load bids for this RFQ

```python
bids_result = subprocess.run([
    "gws", "sheets", "read",
    "--sheet-id", os.environ["MERIDIAN_SHEETS_BID_LOG_ID"],
    "--range", "Bids!A:N",
    "--filter", f"rfq_id={rfq_id},status=received",
    "--format", "json"
], capture_output=True, text=True)

bids = json.loads(bids_result.stdout)

if len(bids) == 0:
    send_telegram(f"⚠️ No bids found for RFQ {rfq_id}. Cannot evaluate.")
    return
```

### Step 2 — Load vendor performance context

```python
vendors_result = subprocess.run([
    "gws", "sheets", "read",
    "--sheet-id", os.environ["MERIDIAN_VENDOR_SHEET_ID"],
    "--range", "Vendors!A:R",
    "--format", "json"
], capture_output=True, text=True)

vendor_master = {v["vendor_id"]: v for v in json.loads(vendors_result.stdout)}
```

### Step 3 — Compute base scores

```python
def evaluate_bids(bids, vendor_master, rfq, weights):
    min_bid   = min(b["bid_total_usd"] for b in bids)
    target_dt = datetime.fromisoformat(rfq["required_by_date"])
    today     = datetime.now()
    max_avail_days = (target_dt - today).days  # days available

    scored = []
    for bid in bids:
        v = vendor_master.get(bid["vendor_id"], {})

        # Price score (40 pts): lowest bid gets full marks
        if bid["bid_total_usd"] > 0:
            price_score = weights["price"] * (min_bid / bid["bid_total_usd"])
        else:
            price_score = 0

        # Delivery score (30 pts): fewer days vs available = better
        del_days = bid.get("delivery_days") or 30
        if del_days <= max_avail_days:
            # On time: score based on how much buffer is left
            buffer = max_avail_days - del_days
            delivery_score = weights["delivery"] * min(1.0, 0.7 + 0.3 * (buffer / max_avail_days))
        else:
            # Late: penalty proportional to how late
            lateness_ratio = del_days / max_avail_days
            delivery_score = weights["delivery"] * max(0, 1 - (lateness_ratio - 1))

        # Quality score (20 pts)
        quality_raw = float(v.get("base_quality_score", 7.0))
        quality_score = weights["quality"] * (quality_raw / 10)

        # Relationship score (10 pts)
        rel_years = int(v.get("relationship_years", 0))
        rel_score = weights["relationship"] * min(rel_years, 10) / 10

        # Archetype flags
        archetype = v.get("behavioral_archetype", "unknown")
        archetype_note = ""
        if archetype == "volatile":
            archetype_note = "⚠️ Volatile archetype — monitor closely post-award"
        elif archetype == "aggressive_bidder" and price_score > weights["price"] * 0.9:
            archetype_note = "ℹ️ Aggressive bidder — verify capacity before awarding"

        composite = round(price_score + delivery_score + quality_score + rel_score, 2)

        scored.append({
            "rfq_id":             rfq_id,
            "vendor_id":          bid["vendor_id"],
            "vendor_name":        bid["vendor_name"],
            "bid_total_usd":      bid["bid_total_usd"],
            "delivery_days":      del_days,
            "price_score":        round(price_score, 2),
            "delivery_score":     round(delivery_score, 2),
            "quality_score":      round(quality_score, 2),
            "relationship_score": round(rel_score, 2),
            "composite_score":    composite,
            "archetype":          archetype,
            "archetype_note":     archetype_note,
            "price_delta_vs_lowest": round((bid["bid_total_usd"] - min_bid) / min_bid * 100, 1),
        })

    scored.sort(key=lambda x: x["composite_score"], reverse=True)
    return scored
```

### Step 4 — Blend MiroFish scenario_6 if available

Check if a shock scenario simulation was run for this RFQ:
```python
mf_result = subprocess.run([
    "gws", "sheets", "read",
    "--sheet-id", os.environ["MERIDIAN_SHEETS_BID_LOG_ID"],
    "--range", "MiroFishPredictions!A:G",
    "--filter", f"rfq_id={rfq_id},scenario=scenario_6",
    "--format", "json"
], capture_output=True, text=True)

mf_predictions = json.loads(mf_result.stdout)

if mf_predictions:
    mf_by_vendor = {p["vendor_id"]: p for p in mf_predictions}
    for bid in scored:
        vid = bid["vendor_id"]
        if vid in mf_by_vendor:
            resilience = float(mf_by_vendor[vid].get("vendor_resilience_score", 0.5))
            # Blend: 85% base model + 15% resilience
            bid["composite_score"] = round(
                0.85 * bid["composite_score"] + 0.15 * resilience * 100, 2
            )
            bid["mirofish_resilience"] = round(resilience, 3)
            bid["mirofish_note"] = mf_by_vendor[vid].get("expected_market_impact", "")
    scored.sort(key=lambda x: x["composite_score"], reverse=True)
```

### Step 5 — Write evaluation to Sheet

```python
eval_rows = [[
    f"EVAL-{b['rfq_id']}-{b['vendor_id']}",
    b["rfq_id"], b["vendor_id"], b["vendor_name"],
    b["bid_total_usd"], b["delivery_days"],
    b["price_score"], b["delivery_score"],
    b["quality_score"], b["relationship_score"],
    b["composite_score"],
    b.get("mirofish_resilience", ""),
    b.get("archetype_note", ""),
    i < 5,  # selected (top 5)
    datetime.now().isoformat()
] for i, b in enumerate(scored)]

subprocess.run([
    "gws", "sheets", "append",
    "--sheet-id", os.environ["MERIDIAN_SHEETS_BID_LOG_ID"],
    "--range", "BidEvaluation!A:O",
    "--values", json.dumps(eval_rows)
])
```

### Step 6 — Send Telegram evaluation report

Format a ranked table:
```python
table_lines = ["*Bid Evaluation — RFQ {rfq_id}*\n"]
table_lines.append(f"{'#':<3} {'Vendor':<28} {'Bid $':>9} {'Days':>5} {'Score':>6}")
table_lines.append("─" * 58)

for i, b in enumerate(scored):
    marker = "✅" if i < 5 else "  "
    line = (f"{i+1:<3} {b['vendor_name'][:27]:<28} "
            f"${b['bid_total_usd']:>8,.0f} {b['delivery_days']:>5} "
            f"{b['composite_score']:>6.1f} {marker}")
    table_lines.append(line)
    if b.get("archetype_note"):
        table_lines.append(f"     {b['archetype_note']}")

table_lines.append(f"\n_Weights: Price {weights['price']}% · Delivery {weights['delivery']}% · Quality {weights['quality']}% · Relationship {weights['relationship']}%_")

send_telegram("```\n" + "\n".join(table_lines) + "\n```")
```

---

## Return to orchestrator

```json
{
  "rfq_id": "RFQ-0042",
  "n_bids_evaluated": 6,
  "ranked_bids": [
    {
      "rank": 1,
      "vendor_id": "V001",
      "vendor_name": "Kovacs Precision GmbH",
      "composite_score": 84.3,
      "bid_total_usd": 38200,
      "delivery_days": 18,
      "archetype_note": ""
    }
  ],
  "mirofish_blended": true,
  "evaluation_sheet_url": "https://docs.google.com/spreadsheets/..."
}
```

## Flags the evaluator raises automatically

- **Late bid** (after deadline): Include but mark `late_bid: true`, deduct 5pts from composite
- **Missing attachments**: Mention in archetype_note; do not penalise score
- **Single bid received**: Flag to Telegram, recommend re-issuing with extended deadline
- **All bids above budget ceiling**: Flag immediately to Telegram before completing evaluation
