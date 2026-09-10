"""
Places one outbound call to the target number for a given scenario, with
recording enabled. Run with the server (server.py, exposed via ngrok) already
running, since Twilio will call back into it immediately once the target
answers.

Usage:
    python -m app.place_call simple_scheduling
    python -m app.place_call --list
"""
import argparse
import sys

from twilio.rest import Client

from app.config import (
    TWILIO_ACCOUNT_SID,
    TWILIO_AUTH_TOKEN,
    TWILIO_FROM_NUMBER,
    TARGET_NUMBER,
    PUBLIC_BASE_URL,
)
from app.scenarios import get_scenario, list_scenarios


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario_id", nargs="?", help="Scenario id to run (see --list)")
    parser.add_argument("--list", action="store_true", help="List available scenarios and exit")
    args = parser.parse_args()

    if args.list or not args.scenario_id:
        print("Available scenarios:\n")
        for s in list_scenarios():
            print(f"  {s.id:<28} [{s.category}] {s.title}")
        if not args.scenario_id:
            sys.exit(0 if args.list else 1)

    scenario = get_scenario(args.scenario_id)  # raises KeyError with a helpful message if invalid

    client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

    call = client.calls.create(
        to=TARGET_NUMBER,
        from_=TWILIO_FROM_NUMBER,
        url=f"{PUBLIC_BASE_URL}/twiml?scenario={scenario.id}",
        method="POST",
        record=True,
        recording_status_callback=f"{PUBLIC_BASE_URL}/recording-status",
        recording_status_callback_event=["completed"],
        status_callback=f"{PUBLIC_BASE_URL}/call-status",
        status_callback_event=["initiated", "ringing", "answered", "completed"],
    )

    print(f"Call placed: SID={call.sid}  scenario={scenario.id} ({scenario.title})")
    print("Watch the server logs for progress. Transcript + recording will land in")
    print("transcripts/ and recordings/ once the call ends.")


if __name__ == "__main__":
    main()
