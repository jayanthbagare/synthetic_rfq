---
name: rfq-email-tracker
description: >
  Monitors Gmail for incoming vendor bid responses to an active RFQ. Runs as a
  cron job (every 30 minutes) or on-demand. Activate when the orchestrator
  starts Phase 3, or when user says "check bids", "any responses yet",
  "track RFQ replies", or "/bids {rfq_id}". Extracts bid amounts, delivery
  commitments, and attachment links from emails. Writes to Sheets. Sends
  Telegram alerts on each new bid received. Fires evaluation trigger when
  conditions are met.
version: 1.0.0
author: meridian-procurement
platforms: [linux, macos]
requires_toolsets: [shell, web]
required_environment_variables:
  - MERIDIAN_SHEETS_BID_LOG_ID
  - PROCUREMENT_EMAIL
tags: [procurement, email, tracking, bids, gmail, meridian]
category: Productivity
telegram_triggers:
  - "/bids"
  - "check bids"
  - "any responses"
  - "track RFQ"
cron_schedule: "*/30 * * * *"
---

## Role

You are the **Bid Inbox Monitor** for Meridian Industrial Systems. You watch
the Gmail inbox for vendor replies, parse bid data from email bodies, and keep
the Bid Log Sheet up to date in real time. You alert the procurement team on
Telegram whenever a new bid lands. You know the difference between an
acknowledgement email and an actual bid.

---

## Procedure

### Step 1 — Load active RFQ thread IDs

Pull all RFQs with status `sent` and their Gmail thread IDs from the Sheet:

```python
result = subprocess.run([
    "gws", "sheets", "read",
    "--sheet-id", os.environ["MERIDIAN_SHEETS_BID_LOG_ID"],
    "--range", "EmailLog!A:G",
    "--filter", "status=sent",
    "--format", "json"
], capture_output=True, text=True)

active_threads = json.loads(result.stdout)
# Each row: rfq_id, vendor_id, sent_at, gmail_thread_id, message_id, status, deadline
```

If `rfq_id` was provided (on-demand call), filter to that RFQ only.

### Step 2 — Fetch thread messages from Gmail

For each thread:
```python
for thread in active_threads:
    result = subprocess.run([
        "gws", "gmail", "get-thread",
        "--thread-id", thread["gmail_thread_id"],
        "--format", "json"
    ], capture_output=True, text=True)

    messages = json.loads(result.stdout)["messages"]

    # Skip if only the original outbound message is in thread
    if len(messages) <= 1:
        continue

    # Process new inbound messages
    for msg in messages[1:]:  # skip the sent RFQ
        if msg["from"] == os.environ["PROCUREMENT_EMAIL"]:
            continue  # skip our own follow-ups
        process_inbound_message(msg, thread)
```

### Step 3 — Classify and parse inbound messages

```python
def process_inbound_message(msg, thread):
    body    = msg["body_plain"]
    subject = msg["subject"]
    sender  = msg["from"]

    # Classify: acknowledgement vs bid vs query vs decline
    classification = classify_email(body, subject)

    if classification == "acknowledgement":
        update_sheet_status(thread, "acknowledged")
        # No Telegram alert for acks — too noisy
        return

    elif classification == "query":
        # Vendor is asking a clarification question
        update_sheet_status(thread, "query_received")
        send_telegram(
            f"❓ Query from {thread['vendor_name']} on RFQ {thread['rfq_id']}:\n"
            f"_{truncate(body, 200)}_\n\nReply in Gmail or ask me to draft a response."
        )
        return

    elif classification == "decline":
        update_sheet_status(thread, "declined")
        send_telegram(f"🚫 {thread['vendor_name']} declined RFQ {thread['rfq_id']}.")
        return

    elif classification == "bid":
        bid_data = extract_bid_data(body, thread)
        save_bid(bid_data, thread, msg)
```

### Step 4 — Extract bid data from email body

```python
def extract_bid_data(body, thread):
    """
    Use the LLM to extract structured bid data from free-form email text.
    This is better than regex for handling varied vendor writing styles.
    """
    extraction_prompt = f"""
Extract the following fields from this vendor bid email. Return JSON only.

Fields:
- bid_total_usd: total quoted price (number, USD)
- bid_unit_price: unit price if stated (number or null)
- delivery_days: lead time in calendar days (integer or null)
- validity_days: how long the quote is valid (integer, default 30)
- payment_terms: stated payment terms (string or null)
- has_attachments: whether datasheet/certificate is mentioned (boolean)
- notes: any important caveats or conditions (string, max 200 chars)

Email:
\"\"\"
{body[:3000]}
\"\"\"
    """

    # Use the agent's own LLM (no separate API call needed in Hermes)
    result = agent.complete(extraction_prompt)
    return json.loads(result)
```

### Step 5 — Save bid to Sheet and log

```python
def save_bid(bid_data, thread, msg):
    bid_id = f"BID-{thread['rfq_id']}-{thread['vendor_id']}"
    received_at = msg["date"]

    row = [
        bid_id,
        thread["rfq_id"],
        thread["vendor_id"],
        thread["vendor_name"],
        received_at,
        bid_data["bid_unit_price"],
        bid_data["bid_total_usd"],
        bid_data["delivery_days"],
        bid_data["validity_days"],
        bid_data["payment_terms"],
        bid_data["has_attachments"],
        bid_data["notes"],
        msg["gmail_message_id"],
        "received"
    ]

    subprocess.run([
        "gws", "sheets", "append",
        "--sheet-id", os.environ["MERIDIAN_SHEETS_BID_LOG_ID"],
        "--range", "Bids!A:N",
        "--values", json.dumps([row])
    ])

    # Update EmailLog status
    update_sheet_status(thread, "bid_received")

    # Telegram alert
    send_telegram(
        f"💰 New bid received!\n\n"
        f"*RFQ*: {thread['rfq_id']}\n"
        f"*Vendor*: {thread['vendor_name']}\n"
        f"*Total*: ${bid_data['bid_total_usd']:,.0f}\n"
        f"*Lead time*: {bid_data['delivery_days']} days\n"
        f"*Validity*: {bid_data['validity_days']} days\n"
        f"*Notes*: {bid_data['notes'] or 'None'}"
    )
```

### Step 6 — Check evaluation trigger conditions

After each batch run, check if evaluation should be triggered:

```python
def check_trigger_conditions(rfq_id):
    bids = get_bids_for_rfq(rfq_id)
    deadline = get_rfq_deadline(rfq_id)
    n_invited = get_invited_count(rfq_id)
    today = datetime.now().date()

    bid_count = len(bids)
    deadline_passed = today >= deadline
    five_or_more_bids = bid_count >= 5

    if deadline_passed or five_or_more_bids:
        send_telegram(
            f"📊 Triggering bid evaluation for RFQ {rfq_id}.\n"
            f"Bids received: {bid_count}/{n_invited}. "
            f"{'Deadline passed.' if deadline_passed else 'Minimum bids threshold reached.'}"
        )
        # Signal orchestrator to begin Phase 4
        # In Hermes: send a message to self to trigger the next skill
        agent.send_to_channel(
            channel="telegram",
            message=f"/evaluate {rfq_id}"
        )
```

### Step 7 — Send nudge emails to non-responders (if 2 days before deadline)

```python
def nudge_non_responders(rfq_id):
    all_invited  = get_invited_vendors(rfq_id)
    responded    = {b["vendor_id"] for b in get_bids_for_rfq(rfq_id)}
    non_responders = [v for v in all_invited if v["vendor_id"] not in responded]

    for vendor in non_responders:
        subprocess.run([
            "gws", "gmail", "reply",
            "--thread-id", vendor["gmail_thread_id"],
            "--body",
                f"Dear {vendor['contact_name'].split()[0]},\n\n"
                f"A gentle reminder that the bid deadline for RFQ "
                f"{rfq_id} is in 2 days. We would greatly value your "
                f"participation. Please do not hesitate to reach out "
                f"if you need any clarification on the specifications.\n\n"
                f"Best regards,\nMeridian Procurement",
            "--from", os.environ["PROCUREMENT_EMAIL"]
        ])

    send_telegram(
        f"📬 Nudge emails sent to {len(non_responders)} non-responders "
        f"for RFQ {rfq_id}: {', '.join(v['vendor_name'] for v in non_responders)}"
    )
```

---

## Email classification heuristics

The LLM should classify an email as:

- **bid**: contains a price figure, OR mentions "quotation", "our offer", "unit price",
  "total cost", "please find attached our quote"
- **acknowledgement**: contains "thank you", "received", "will revert", "noted",
  no price figures
- **query**: contains a question mark AND references spec items, quantities,
  or delivery terms
- **decline**: contains "unable to", "not in a position", "regret", "capacity",
  "decline"

When ambiguous, default to **query** (safer — gets human attention).

## Telegram message format rules

- Use Markdown formatting (Telegram supports it)
- `*bold*` for field names
- `_italic_` for quoted email content
- Never dump the full email body — truncate to 200 chars max
- Always include the RFQ ID so the user has context
