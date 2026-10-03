#!/usr/bin/env python3
"""
Missed-appointment follow-up bot.

Flow:
  1. Look up the patient in patients.csv
  2. Claude classifies the patient's reply into ONE barrier category
  3. Claude drafts an SMS reply and decides which tools (tools.py) to call, e.g. directions
  4. Prints JSON: classification, tools used, reply, escalation flag

Usage:
  export ANTHROPIC_API_KEY=...
  export GOOGLE_MAPS_API_KEY=...        # optional; without it you still get a Maps link

  python missed_appointment_bot.py --patient-id P00008 \
      --message "I have no money for matatu" \
      --hospital-name "Kenyatta National Hospital" \
      --hospital-address "Hospital Road, Upper Hill, Nairobi"

pip install anthropic
"""

import argparse
import csv
import json
import os
import sys
from datetime import datetime

from tools import TOOLS, make_classify_tool, run_tool

# ───────────────────────── CONFIG (edit these) ─────────────────────────
PATIENTS_CSV_PATH = "patients.csv"
CSV_COLUMNS = ["patient_id", "name", "phone", "address", "appointment_datetime", "attended"]
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = "claude-sonnet-4-6"
MAX_TOOL_ROUNDS = 2
# ────────────────────────────────────────────────────────────────────────

BARRIERS = {
    "transport": "can't get there (fare, distance, no matatu, no one to take them)",
    "cost": "worried about fees, insurance (NHIF/SHA), lab or drug costs",
    "wrong_facility": "the facility doesn't offer the service, or the wrong place",
    "missing_documents": "lacks referral letter, ID, insurance card, clinic book or lab results",
    "scheduling": "can't get or doesn't know the appointment; timing clashes with work",
    "clinic_closed": "went and the facility was shut",
    "turned_away": "facility was open but sent them home (queue full, 'come back Monday')",
    "language": "didn't understand messages or staff because of language",
    "fear_confusion": "scared, confused about why they were referred, stigma",
    "clinical_symptom": "mentions any symptom, pain, bleeding, fever, or feeling worse",
    "plan_ack": "no barrier - an acknowledgement or a stated plan ('ok thanks', 'I'll go Monday')",
    "unknown": "unclear, off-topic, or you are not sure",
}

# What the reply should do for each barrier (tools are chosen by Claude, not hard-coded).
BARRIER_GUIDANCE = {
    "transport": "Call get_directions from the patient's address to the hospital and give simple matatu/route steps plus the Maps link.",
    "cost": "Say SHA/NHIF status can be checked at the facility or by dialing *147#, and offer to connect them with clinic staff about fees.",
    "wrong_facility": "Call find_nearby_facilities near the patient's address for the service they need; also mention the original hospital.",
    "missing_documents": "Tell them to bring ID, any referral letter, clinic book and lab results if they have them, and to come anyway if something is missing.",
    "scheduling": "Remind them of the original appointment time and offer to rebook at a time that avoids work clashes.",
    "clinic_closed": "Apologise, say staff will confirm opening hours and rebook.",
    "turned_away": "Apologise, say staff will arrange a firm slot.",
    "language": "Offer to continue in Swahili or their preferred language; keep wording very simple.",
    "fear_confusion": "Reassure kindly and confidentially; offer a call from a nurse to explain the referral.",
    "clinical_symptom": "Urge them to go to the nearest facility now (emergency services if severe) and say a nurse will call. You may call get_directions.",
    "plan_ack": "Short friendly confirmation; remind them of the appointment/plan.",
    "unknown": "Ask one gentle clarifying question about what is making it hard to attend.",
}

# Categories a human should look at regardless of what the bot replies.
ESCALATE = {"clinical_symptom", "turned_away", "clinic_closed", "unknown"}


# ───────────────────────────── Patient data ─────────────────────────────
def load_patient(patient_id: str, csv_path: str) -> dict:
    """patients.csv always has a header row and exactly CSV_COLUMNS."""
    with open(csv_path, newline="", encoding="utf-8") as f:
        next(f)  # skip header
        for row in csv.DictReader(f, fieldnames=CSV_COLUMNS):
            if row["patient_id"].strip() == patient_id:
                return row
    raise SystemExit(f"Patient {patient_id} not found in {csv_path}")


# ───────────────────────────── Claude calls ─────────────────────────────
def get_client():
    import anthropic
    if not ANTHROPIC_API_KEY:
        raise SystemExit("Set ANTHROPIC_API_KEY")
    return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def classify(client, message: str) -> dict:
    """Force a structured tool call so the output is always a valid category."""
    barrier_list = "\n".join(f"- {k}: {v}" for k, v in BARRIERS.items())
    resp = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=300,
        system=(
            "You triage replies from patients who missed a clinic appointment in Kenya. "
            "Messages may be in English, Swahili or Sheng. Pick the single best `barrier`:\n"
            f"{barrier_list}\n"
            "If any symptom is mentioned, prefer clinical_symptom. If unsure, use unknown."
        ),
        tools=[make_classify_tool(list(BARRIERS))],
        tool_choice={"type": "tool", "name": "record_barrier"},
        messages=[{"role": "user", "content": message}],
    )
    for block in resp.content:
        if block.type == "tool_use":
            result = dict(block.input)
            if result.get("barrier") not in BARRIERS:
                result["barrier"] = "unknown"
            return result
    return {"barrier": "unknown", "confidence": 0.0, "reason": "no tool output"}


def draft_reply(client, patient: dict, message: str, barrier: str,
                hospital_name: str, hospital_address: str) -> tuple[str, list]:
    """Let Claude call tools from tools.py until it produces the final SMS."""
    system = (
        "You write SMS replies for a clinic to patients who missed an appointment. "
        "Be warm, plain-language, under 480 characters, no jargon, no blame. "
        "Use ONLY facts from the context or tool results; never invent fees, hours, routes or policies. "
        "Offer to help rebook. Reply in the same language the patient used. "
        f"For this patient (barrier: {barrier}): {BARRIER_GUIDANCE[barrier]} "
        "Output only the SMS text."
    )
    context = {
        "patient_first_name": patient["name"].split()[0],
        "patient_address": patient["address"],
        "appointment": patient["appointment_datetime"],
        "hospital_name": hospital_name,
        "hospital_address": hospital_address,
        "patient_message": message,
    }
    messages = [{"role": "user", "content": json.dumps(context)}]
    tools_called = []

    resp = None
    for _ in range(MAX_TOOL_ROUNDS):
        resp = client.messages.create(
            model=CLAUDE_MODEL, max_tokens=800, system=system, tools=TOOLS, messages=messages
        )
        if resp.stop_reason != "tool_use":
            break
        messages.append({"role": "assistant", "content": resp.content})
        results = []
        for block in resp.content:
            if block.type == "tool_use":
                tools_called.append({"name": block.name, "input": block.input})
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": run_tool(block.name, block.input),
                })
        messages.append({"role": "user", "content": results})

    text = "".join(b.text for b in resp.content if b.type == "text").strip() if resp else ""
    return text, tools_called


def main():
    ap = argparse.ArgumentParser(description="Tailored response for a patient who missed an appointment")
    ap.add_argument("--patient-id", required=True)
    ap.add_argument("--message", required=True, help="The patient's reply text")
    ap.add_argument("--hospital-name", required=True)
    ap.add_argument("--hospital-address", required=True)
    ap.add_argument("--csv", default=PATIENTS_CSV_PATH)
    args = ap.parse_args()

    patient = load_patient(args.patient_id, args.csv)
    client = get_client()

    cls = classify(client, args.message)
    barrier = cls["barrier"]

    try:
        reply, tools_called = draft_reply(
            client, patient, args.message, barrier, args.hospital_name, args.hospital_address
        )
    except Exception as e:
        reply, tools_called = "", []
        print(f"[warn] reply drafting failed: {e}", file=sys.stderr)
    if not reply:
        reply = "Hello, we missed you at your appointment. Please reply and we will help you rebook."

    print(json.dumps({
        "patient_id": patient["patient_id"],
        "patient_name": patient["name"],
        "classification": cls,
        "escalate_to_human": barrier in ESCALATE,
        "tools_called": tools_called,
        "reply_sms": reply,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()