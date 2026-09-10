"""
FastAPI app that Twilio talks to. Run this (via uvicorn) and expose it publicly
with ngrok before placing calls — see README.md.

Routes:
  GET/POST /twiml            -> TwiML telling Twilio to open a bidirectional
                                 media stream back to this server for the call.
  WS       /media-stream     -> the actual audio bridge (see realtime_bridge.py)
  POST     /recording-status -> Twilio callback fired when the call recording
                                 is ready; downloads it into recordings/.
  POST     /call-status      -> Twilio callback for call lifecycle logging.
"""
import logging
from pathlib import Path

import requests
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import Response

from app.config import PUBLIC_BASE_URL, TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN
from app.realtime_bridge import run_bridge

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("server")

app = FastAPI()

RECORDINGS_DIR = Path(__file__).resolve().parent.parent / "recordings"
RECORDINGS_DIR.mkdir(exist_ok=True)


def _ws_base_url() -> str:
    # PUBLIC_BASE_URL is the https ngrok URL; the media stream needs wss://.
    return PUBLIC_BASE_URL.replace("https://", "wss://").replace("http://", "ws://")


@app.api_route("/twiml", methods=["GET", "POST"])
async def twiml(request: Request):
    scenario_id = request.query_params.get("scenario", "simple_scheduling")
    stream_url = f"{_ws_base_url()}/media-stream?scenario={scenario_id}"
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Connect>
    <Stream url="{stream_url}" />
  </Connect>
</Response>"""
    return Response(content=xml, media_type="text/xml")


@app.websocket("/media-stream")
async def media_stream(websocket: WebSocket):
    scenario_id = websocket.query_params.get("scenario", "simple_scheduling")
    await run_bridge(websocket, scenario_id)


@app.post("/recording-status")
async def recording_status(request: Request):
    form = await request.form()
    recording_sid = form.get("RecordingSid")
    call_sid = form.get("CallSid")
    recording_url = form.get("RecordingUrl")  # base URL, no extension

    if recording_url:
        # Twilio recordings are available as .mp3 by appending the extension.
        mp3_url = f"{recording_url}.mp3"
        resp = requests.get(mp3_url, auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN))
        if resp.ok:
            out_path = RECORDINGS_DIR / f"{call_sid}.mp3"
            out_path.write_bytes(resp.content)
            log.info("Recording saved: %s", out_path)
        else:
            log.error("Failed to download recording %s: %s", recording_sid, resp.status_code)

    return Response(status_code=204)


@app.post("/call-status")
async def call_status(request: Request):
    form = await request.form()
    log.info("Call %s status: %s", form.get("CallSid"), form.get("CallStatus"))
    return Response(status_code=204)


@app.get("/")
async def health():
    return {"status": "ok"}
