"""
Places one outbound call for a given scenario by explicitly dispatching a job
to the running agent worker (app/agent.py). Run the worker first (it must be
running and connected to LiveKit before dispatching), then run this.

Usage:
    python -m app.agent start &            # start the worker once, leave it running
    python -m app.dispatch_call simple_scheduling
    python -m app.dispatch_call --list
"""
import argparse
import asyncio
import sys
import time

from livekit import api

from app.config import AGENT_NAME, LIVEKIT_API_KEY, LIVEKIT_API_SECRET, LIVEKIT_URL
from app.scenarios import get_scenario, list_scenarios


async def dispatch(scenario_id: str) -> str:
    scenario = get_scenario(scenario_id)  # raises KeyError with a helpful message if invalid
    room_name = f"pgai-{scenario_id}-{int(time.time())}"

    lkapi = api.LiveKitAPI(url=LIVEKIT_URL, api_key=LIVEKIT_API_KEY, api_secret=LIVEKIT_API_SECRET)
    try:
        await lkapi.agent_dispatch.create_dispatch(
            api.CreateAgentDispatchRequest(
                agent_name=AGENT_NAME,
                room=room_name,
                metadata=scenario_id,
            )
        )
    finally:
        await lkapi.aclose()

    print(f"Dispatched: room={room_name}  scenario={scenario.id} ({scenario.title})")
    print("Watch the worker's logs for progress. Transcript + recording will land in")
    print("transcripts/ and recordings/ once the call ends (call_id == room name).")
    return room_name


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

    asyncio.run(dispatch(args.scenario_id))


if __name__ == "__main__":
    main()
