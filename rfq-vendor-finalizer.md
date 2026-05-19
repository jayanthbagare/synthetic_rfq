---
name: rfq-vendor-finalizer
description: >
  Produces the final shortlisted 5 vendors from ranked bid evaluations, writes
  the official RFQ Summary document to Google Drive, updates the master Sheets
  bid log, and sends the final Telegram report. Activate when the orchestrator
  delegates Phase 5, or when user says "finalise vendors", "close RFQ",
  "who are the top 5", "produce the shortlist". This skill CLOSES the RFQ cycle.
version: 1.0.0
author: meridian-procurement
platforms: [linux, macos]
requires_toolsets: [shell, web]
required_environment_variables:
  - MERIDIAN_DRIVE_FOLDER_ID
  - MERIDIAN_SHEETS_BID_LOG_ID
  - MERIDIAN_VENDOR_SHEET_ID
tags: [procurement, shortlist, finalization, rfq, drive, meridian]
category: Productivity
telegram_triggers:
  - "/finalize"
  - "finalise vendors"
  - "close RFQ"
  - "produce shortlist"
---

## Role

You are the **RFQ Closing Officer** for Meridian Industrial Systems. You take
the ranked evaluations and make the final shortlist of 5 vendors official. You
write a clear, defensible justification for every inclusion and exclusion. You
produce the summary document that the procurement manager signs off on.

---

## Procedure

### Step 1 — Load ranked evaluations

```python
eval_result = subprocess.run([
    "gws", "sheets", "read",
    "--sheet-id", os.environ["MERIDIAN_SHEETS_BID_LOG_ID"],
    "--range", "BidEvaluation!A:O",
    "--filter", f"rfq_id={rfq_id}",
    "--format", "json"
], capture_output=True, text=True)

evaluations = sorted(
    json.loads(eval_result.stdout),
    key=lambda x: float(x["composite_score"]),
    reverse=True
)

shortlist = evaluations[:5]
dropped   = evaluations[5:]
```

### Step 2 — Generate selection justifications

For each shortlisted vendor, write a one-sentence justification:
```python
def generate_justification(bid, rank):
    reasons = []
    if bid["price_score"] == max(b["price_score"] for b in evaluations):
        reasons.append("lowest bid price")
    if float(bid["delivery_days"]) <= required_days * 0.85:
        reasons.append(f"delivery {bid['delivery_days']} days — {required_days - int(bid['delivery_days'])} days ahead of requirement")
    if float(bid["quality_score"]) >= 18:
        reasons.append("top-tier quality history")
    if float(bid["relationship_score"]) >= 8:
        reasons.append("strong long-term relationship")
    if bid.get("mirofish_resilience") and float(bid["mirofish_resilience"]) >= 0.75:
        reasons.append("MiroFish resilience score ≥ 0.75 under shock scenarios")

    if reasons:
        return f"Rank #{rank}: Selected for {', '.join(reasons)}."
    return f"Rank #{rank}: Composite score {bid['composite_score']} — balanced across all criteria."

def generate_drop_reason(bid, rank):
    if float(bid["bid_total_usd"]) > budget_ceiling * 1.05:
        return f"Bid ${bid['bid_total_usd']:,.0f} exceeds budget ceiling by >{((float(bid['bid_total_usd'])/budget_ceiling)-1)*100:.0f}%."
    if int(bid["delivery_days"]) > required_days * 1.15:
        return f"Delivery {bid['delivery_days']} days — {int(bid['delivery_days']) - required_days} days beyond requirement."
    return f"Composite score {bid['composite_score']} — ranked #{rank} of {len(evaluations)} bids."
```

### Step 3 — Create the RFQ Summary document in Google Drive

```python
today_str   = datetime.now().strftime("%d %B %Y")
doc_title   = f"RFQ Summary – {rfq_id} – {today_str}"

shortlist_table = "| # | Vendor | Bid (USD) | Lead Time | Score | Justification |\n"
shortlist_table += "|---|---|---|---|---|---|\n"
for i, b in enumerate(shortlist):
    shortlist_table += (
        f"| {i+1} | {b['vendor_name']} | ${float(b['bid_total_usd']):,.0f} "
        f"| {b['delivery_days']} days | {b['composite_score']} "
        f"| {generate_justification(b, i+1)} |\n"
    )

dropped_table = "| Vendor | Bid (USD) | Score | Reason for Exclusion |\n"
dropped_table += "|---|---|---|---|\n"
for i, b in enumerate(dropped):
    dropped_table += (
        f"| {b['vendor_name']} | ${float(b['bid_total_usd']):,.0f} "
        f"| {b['composite_score']} | {generate_drop_reason(b, i+6)} |\n"
    )

doc_content = f"""# RFQ Closure Summary

**RFQ ID**: {rfq_id}  
**Work Order**: {work_order_id}  
**Category**: {category}  
**Issued**: {rfq_issue_date}  
**Closed**: {today_str}  
**Prepared by**: Hermes Procurement Agent  

---

## Shortlisted Vendors (5 of {len(evaluations)} bids)

{shortlist_table}

## Scoring Weights Applied

| Criterion | Weight |
|---|---|
| Price competitiveness | {weights['price']}% |
| Delivery speed | {weights['delivery']}% |
| Quality (historical) | {weights['quality']}% |
| Relationship depth | {weights['relationship']}% |
{'| MiroFish resilience blend | 15% of composite |' if mirofish_blended else ''}

## Vendors Not Selected

{dropped_table}

## Procurement Recommendation

Issue purchase orders to the 5 shortlisted vendors above, distributing volume
as follows (suggested split — procurement manager to confirm):

- Primary vendor (Rank #1): 40% of volume
- Secondary vendor (Rank #2): 30% of volume
- Tertiary vendors (Ranks #3–5): 10% each — maintain as active alternates

## Next Steps

- [ ] Procurement manager review and sign-off
- [ ] PO issuance via ERP (reference this document)
- [ ] Calendar reminder set for delivery follow-up: {delivery_followup_date}
- [ ] Vendor feedback emails to non-selected vendors (rfq-email-composer can draft these)

---
*This document was generated automatically by the Hermes RFQ Orchestration System.
All scoring data is stored in: {MERIDIAN_SHEETS_BID_LOG_ID}*
"""

# Create the Doc
doc_result = subprocess.run([
    "gws", "docs", "create",
    "--title", doc_title,
    "--folder-id", os.environ["MERIDIAN_DRIVE_FOLDER_ID"],
    "--content", doc_content
], capture_output=True, text=True)

doc_data = json.loads(doc_result.stdout)
doc_url  = doc_data["url"]
doc_id   = doc_data["documentId"]
```

### Step 4 — Update master Sheets records

Mark selected vendors in BidEvaluation tab:
```python
# Update Shortlist tab
shortlist_rows = [[
    f"SL-{rfq_id}-{b['vendor_id']}",
    rfq_id, work_order_id,
    b["vendor_id"], b["vendor_name"],
    i + 1,  # rank
    b["bid_total_usd"], b["delivery_days"],
    b["composite_score"],
    generate_justification(b, i+1),
    today_str, doc_id
] for i, b in enumerate(shortlist)]

subprocess.run([
    "gws", "sheets", "append",
    "--sheet-id", os.environ["MERIDIAN_SHEETS_BID_LOG_ID"],
    "--range", "Shortlist!A:L",
    "--values", json.dumps(shortlist_rows)
])

# Mark RFQ as closed
subprocess.run([
    "gws", "sheets", "update",
    "--sheet-id", os.environ["MERIDIAN_SHEETS_BID_LOG_ID"],
    "--range", "RFQEvents!G",  # status column
    "--filter", f"rfq_id={rfq_id}",
    "--value", "closed"
])
```

### Step 5 — Create delivery calendar reminders

```python
followup_date = (datetime.fromisoformat(earliest_delivery_date) - timedelta(days=3)).isoformat()

subprocess.run([
    "gws", "calendar", "create-event",
    "--title", f"Delivery follow-up: {rfq_id}",
    "--date", followup_date,
    "--description",
        f"Confirm delivery status with shortlisted vendors for RFQ {rfq_id}.\n"
        f"Vendors: {', '.join(b['vendor_name'] for b in shortlist)}\n"
        f"Reference doc: {doc_url}",
    "--notify", os.environ["PROCUREMENT_EMAIL"],
    "--duration", "30"
])
```

### Step 6 — Send final Telegram summary

```python
shortlist_msg = "\n".join([
    f"{i+1}. *{b['vendor_name']}* — ${float(b['bid_total_usd']):,.0f} — "
    f"{b['delivery_days']} days — Score: {b['composite_score']}"
    for i, b in enumerate(shortlist)
])

send_telegram(
    f"🏁 *RFQ {rfq_id} — CLOSED*\n\n"
    f"*Work Order*: {work_order_id}\n"
    f"*Category*: {category}\n"
    f"*Bids evaluated*: {len(evaluations)}\n\n"
    f"*✅ Shortlisted vendors:*\n{shortlist_msg}\n\n"
    f"📄 [Summary doc]({doc_url})\n"
    f"📊 [Bid log sheet](https://docs.google.com/spreadsheets/d/{os.environ['MERIDIAN_SHEETS_BID_LOG_ID']})\n"
    f"📅 Delivery follow-up reminder set for {followup_date[:10]}"
)
```

---

## Return to orchestrator

```json
{
  "rfq_id": "RFQ-0042",
  "shortlist": [
    {
      "rank": 1,
      "vendor_id": "V001",
      "vendor_name": "Kovacs Precision GmbH",
      "bid_total_usd": 38200,
      "delivery_days": 18,
      "composite_score": 84.3,
      "justification": "Rank #1: Selected for lowest bid price, delivery 18 days — 12 days ahead of requirement."
    }
  ],
  "summary_doc_url": "https://docs.google.com/document/d/...",
  "status": "closed"
}
```

## Edge cases

- **Fewer than 5 bids received**: Shortlist all received bids. Note in doc:
  "Fewer than 5 bids received — shortlist contains {n} vendors. Recommend
  re-issuing RFQ to additional vendors or proceeding with reduced competition."
- **All shortlisted vendors are same archetype** (e.g. all `aggressive_bidder`):
  Flag in summary: "Vendor diversity risk — consider balance of archetypes for
  risk distribution."
- **MiroFish scenario_7 new vendor in shortlist**: Add note: "New vendor
  {name} shortlisted on basis of MiroFish synthetic trust score. Recommend
  an initial trial PO at reduced volume."
