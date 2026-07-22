"""Georgian voice assistant — SignalWire phone line.

When someone calls your SignalWire number, the AI answers, listens, and speaks back
in Georgian. Each turn is a short recording that we send to Gemini (same clean-audio
pipeline as the Telegram bot), so understanding stays Gemini-grade — not phone-STT.

Turn loop:
    call comes in  -> /incoming : play greeting, then <Record>
    caller speaks  -> /handle   : download recording -> Gemini -> edge-tts -> <Play> -> <Record> again

Setup:
    1. Fill SIGNALWIRE_PROJECT_ID and SIGNALWIRE_API_TOKEN in .env
       (SignalWire Space -> API -> your Project ID + a new API Token).
       These are needed to download the call recordings.
    2. Run this server:            python call.py
    3. Expose it publicly:         cloudflared tunnel --url http://localhost:5000
       Put the https URL it prints into PUBLIC_URL in .env, then restart this server.
    4. In your SignalWire number's Voice settings, set "when a call comes in" to:
       <PUBLIC_URL>/incoming   (HTTP POST)
    5. On a trial Space, add your own phone as a Verified Caller ID, then call the number.
"""

import os
import time
import base64
import threading

import requests
from flask import Flask, request, Response, send_from_directory

from assistant import respond, synthesize, BRIEF_STYLE  # loads .env on import

PROJECT = os.environ.get("SIGNALWIRE_PROJECT_ID")
TOKEN = os.environ.get("SIGNALWIRE_API_TOKEN")
PUBLIC_URL = os.environ.get("PUBLIC_URL", "").rstrip("/")

AUDIO_DIR = os.path.join(os.path.dirname(__file__), "call_audio")
os.makedirs(AUDIO_DIR, exist_ok=True)

app = Flask(__name__)

# Per-call conversation history: {CallSid: [ {role, parts}, ... ] }
calls = {}

GREETING = ("გამარჯობა. მე ვარ თქვენი ხმოვანი დამხმარე. "
            "სიგნალის შემდეგ დამისვით კითხვა.")
REPROMPT = "ბოდიში, ვერ გავიგე. გთხოვთ, გაიმეოროთ."


def base_url():
    """Public base for building <Play>/action URLs (behind cloudflared)."""
    return PUBLIC_URL or request.host_url.rstrip("/")


def laml(inner):
    """Wrap verbs in a LaML (Twilio-compatible) document."""
    xml = f'<?xml version="1.0" encoding="UTF-8"?><Response>{inner}</Response>'
    return Response(xml, mimetype="text/xml")


def record_verb():
    """Record the caller's next utterance and POST it to /handle when they pause."""
    action = f"{base_url()}/handle"
    return (f'<Record action="{action}" method="POST" maxLength="30" timeout="3" '
            f'playBeep="true" trim="trim-silence" finishOnKey="#"/>')


def speak(text):
    """TTS `text` to a file served under /audio, and return a <Play> verb for it."""
    fn = synthesize(text, path=os.path.join(AUDIO_DIR, f"{os.urandom(8).hex()}.mp3"))
    return f'<Play>{base_url()}/audio/{os.path.basename(fn)}</Play>'


def download_recording(recording_url):
    """Fetch a SignalWire recording. Media needs Project ID / API Token auth and can
    lag a beat after the call, so retry briefly. Tries mp3 then wav."""
    if not (PROJECT and TOKEN):
        raise RuntimeError("SIGNALWIRE_PROJECT_ID / SIGNALWIRE_API_TOKEN not set — "
                           "needed to download call recordings.")
    for ext in (".mp3", ".wav"):
        for _ in range(6):
            r = requests.get(recording_url + ext, auth=(PROJECT, TOKEN), timeout=15)
            if r.status_code == 200 and r.content:
                mime = "audio/mp3" if ext == ".mp3" else "audio/wav"
                return r.content, mime
            time.sleep(0.5)
    raise RuntimeError(f"could not download recording: {recording_url}")


@app.route("/incoming", methods=["POST"])
def incoming():
    """A call came in: reset memory, greet, then start recording."""
    sid = request.form.get("CallSid", "unknown")
    calls[sid] = []
    print(f"📞 incoming call {sid} from {request.form.get('From')}")
    return laml(speak(GREETING) + record_verb())


@app.route("/handle", methods=["POST"])
def handle():
    """Caller finished speaking: transcribe+answer with Gemini, speak, record again."""
    sid = request.form.get("CallSid", "unknown")
    recording_url = request.form.get("RecordingUrl")
    history = calls.setdefault(sid, [])

    if not recording_url:
        return laml(speak(REPROMPT) + record_verb())

    try:
        audio, mime = download_recording(recording_url)
        parts = [
            {"inline_data": {"mime_type": mime, "data": base64.b64encode(audio).decode()}},
            {"text": "მოისმინე ეს ხმოვანი შეტყობინება და უპასუხე ქართულად."},
        ]
        answer = respond(history, parts, style=BRIEF_STYLE, max_output=1500)
        print(f"📞 {sid}\n🤖 {answer}\n")
    except Exception as e:
        print("ERR:", e)
        answer = REPROMPT

    return laml(speak(answer) + record_verb())


@app.route("/audio/<name>")
def audio(name):
    """Serve a generated MP3 so SignalWire's <Play> can fetch it."""
    return send_from_directory(AUDIO_DIR, name, mimetype="audio/mpeg")


@app.route("/health")
def health():
    return "ok"


def _cleanup_loop():
    """Delete generated turn-audio older than 5 minutes so call_audio/ doesn't grow."""
    while True:
        time.sleep(120)
        cutoff = time.time() - 300
        for name in os.listdir(AUDIO_DIR):
            path = os.path.join(AUDIO_DIR, name)
            try:
                if os.path.getmtime(path) < cutoff:
                    os.remove(path)
            except OSError:
                pass


threading.Thread(target=_cleanup_loop, daemon=True).start()


if __name__ == "__main__":
    if not PUBLIC_URL:
        print("⚠️  PUBLIC_URL not set — run cloudflared and put its https URL in .env.")
    if not (PROJECT and TOKEN):
        print("⚠️  SIGNALWIRE_PROJECT_ID / SIGNALWIRE_API_TOKEN not set — "
              "the call will answer but can't understand replies until you add them.")
    print("Phone server on http://localhost:5000  (point your SignalWire number at <PUBLIC_URL>/incoming)")
    app.run(host="0.0.0.0", port=5000)
