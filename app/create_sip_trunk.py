"""
One-time setup script: creates the LiveKit outbound SIP trunk that points at
a Twilio Elastic SIP Trunk, so the agent can dial real phone numbers. Run this
once after creating the Twilio trunk (see README.md for the Twilio-side
steps); re-running it creates a duplicate trunk rather than updating one, so
only run it again if you intentionally want a fresh trunk.

Usage:
    python -m app.create_sip_trunk
"""
import asyncio

from livekit import api

from app.config import LIVEKIT_API_KEY, LIVEKIT_API_SECRET, LIVEKIT_URL
import os


async def main():
    address = os.environ["SIP_TRUNK_ADDRESS"]
    from_number = os.environ["SIP_TRUNK_FROM_NUMBER"]
    username = os.environ["SIP_TRUNK_USERNAME"]
    password = os.environ["SIP_TRUNK_PASSWORD"]

    lkapi = api.LiveKitAPI(url=LIVEKIT_URL, api_key=LIVEKIT_API_KEY, api_secret=LIVEKIT_API_SECRET)
    trunk = api.SIPOutboundTrunkInfo(
        name="pgai-voicebot-twilio",
        address=address,
        numbers=[from_number],
        auth_username=username,
        auth_password=password,
    )
    result = await lkapi.sip.create_sip_outbound_trunk(api.CreateSIPOutboundTrunkRequest(trunk=trunk))
    await lkapi.aclose()
    print("Created trunk:", result.sip_trunk_id)
    print("Add this to your .env / Colab secrets as SIP_TRUNK_ID")


if __name__ == "__main__":
    asyncio.run(main())
