#!/usr/bin/env python3
"""Build review-only outreach task payloads."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List


ROOT = Path(__file__).resolve().parents[1]
PROMPT_BY_CHANNEL = {
    "Email": ROOT / "prompts" / "outreach" / "cold-email-v1.md",
    "LinkedIn": ROOT / "prompts" / "outreach" / "linkedin-message-v1.md",
    "WhatsApp": ROOT / "prompts" / "outreach" / "whatsapp-message-v1.md",
    "Website Form": ROOT / "prompts" / "outreach" / "website-contact-form-v1.md",
}


def prompt_path_for_channel(channel: str) -> Path:
    if channel not in PROMPT_BY_CHANNEL:
        raise ValueError("unsupported outreach channel: %s" % channel)
    return PROMPT_BY_CHANNEL[channel]


def build_outreach_task(
    lead: Dict[str, Any],
    contact: Dict[str, Any],
    channel: str,
    ai_draft: str,
    owner: str = "",
    message_type: str = "First Touch",
) -> Dict[str, Any]:
    if not ai_draft.strip():
        raise ValueError("ai_draft is required")
    return {
        "Lead ID": lead.get("Lead ID") or lead.get("lead_id") or "",
        "Contact ID": contact.get("Contact ID") or contact.get("contact_id") or "",
        "Owner": owner,
        "Channel": channel,
        "Message Type": message_type,
        "AI Draft": ai_draft,
        "Human Edited Version": "",
        "Approval Status": "Pending Review",
        "Send Status": "Not Sent",
        "Result": "No Response",
        "Notes": "AI draft only. Human review is required before sending.",
    }


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(description="Show prompt path for an outreach channel")
    parser.add_argument("--channel", required=True, choices=sorted(PROMPT_BY_CHANNEL))
    args = parser.parse_args(argv)
    payload = {
        "channel": args.channel,
        "prompt_path": str(prompt_path_for_channel(args.channel)),
        "safety": "draft-only; human review required",
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

