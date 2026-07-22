"""Georgian live captioner for the deaf.

The phone listens to a conversation and shows huge live Georgian captions on screen,
so a deaf or hard-of-hearing person can follow what hearing people are saying.
The browser detects each spoken phrase (on natural pauses) and sends it here; Gemini
transcribes it and the caption appears. No TTS, no chat — just fast transcription.

Run:
    python caption.py
Then open  http://localhost:5001  (mic works on localhost; use cloudflared for a phone).
"""

import os
import base64

from flask import Flask, request, jsonify, send_file

from assistant import transcribe  # loads .env on import
import speakers

app = Flask(__name__)
HERE = os.path.dirname(__file__)


@app.route("/")
def index():
    return send_file(os.path.join(HERE, "captioner.html"))


@app.route("/caption", methods=["POST"])
def caption():
    """Receive one spoken phrase (WAV) and return its Georgian transcription."""
    if "audio" not in request.files:
        return jsonify(text=""), 400
    f = request.files["audio"]
    audio = f.read()
    mime = f.mimetype or "audio/wav"
    sid = request.form.get("sid", "anon")
    try:
        text = transcribe(base64.b64encode(audio).decode(), mime)
    except Exception as e:
        print("ERR:", e)
        text = ""
    if not text:
        return jsonify(text="", speaker="")
    speaker = speakers.identify(sid, audio)   # who said it (by voice pitch)
    print(f"📝 {speaker}: {text}")
    return jsonify(text=text, speaker=speaker)


@app.route("/reset", methods=["POST"])
def reset():
    speakers.reset(request.form.get("sid", "anon"))
    return jsonify(ok=True)


@app.route("/health")
def health():
    return "ok"


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    print(f"Georgian captioner on http://localhost:{port}  (open it in your browser)")
    app.run(host="0.0.0.0", port=port)
