"""Georgian voice assistant — browser "call" app.

Open the page, tap the button, speak Georgian, hear the AI answer — a call-like
experience with no phone number, no provider, no region limits. Uses the same
Gemini + edge-tts pipeline as everything else (assistant.py).

Run:
    python web.py
Then open  http://localhost:5000  on this laptop (mic works on localhost).
To use it on your phone, expose it over https with cloudflared (see README).
"""

import os
import base64

from flask import Flask, request, jsonify, send_file

from assistant import respond, synthesize, BRIEF_STYLE  # loads .env on import

app = Flask(__name__)
HERE = os.path.dirname(__file__)

# Per-browser conversation history: {session_id: [ {role, parts}, ... ] }
sessions = {}


@app.route("/")
def index():
    return send_file(os.path.join(HERE, "webcall.html"))


@app.route("/talk", methods=["POST"])
def talk():
    """Receive a WAV utterance, answer with Gemini, return text + spoken MP3."""
    sid = request.form.get("sid", "anon")
    if "audio" not in request.files:
        return jsonify(error="no audio"), 400

    audio = request.files["audio"].read()
    history = sessions.setdefault(sid, [])
    parts = [
        {"inline_data": {"mime_type": "audio/wav", "data": base64.b64encode(audio).decode()}},
        {"text": "მოისმინე ეს ხმოვანი შეტყობინება და უპასუხე ქართულად."},
    ]
    try:
        answer = respond(history, parts, style=BRIEF_STYLE, max_output=1500)
        print(f"🗣️  ({sid})\n🤖 {answer}\n")
    except Exception as e:
        print("ERR:", e)
        answer = "ბოდიში, ვერ გავიგე. გთხოვთ, გაიმეოროთ."

    mp3_path = synthesize(answer)
    try:
        with open(mp3_path, "rb") as f:
            mp3 = f.read()
    finally:
        os.remove(mp3_path)

    return jsonify(text=answer, audio=base64.b64encode(mp3).decode())


@app.route("/reset", methods=["POST"])
def reset():
    sessions.pop(request.form.get("sid", "anon"), None)
    return jsonify(ok=True)


@app.route("/health")
def health():
    return "ok"


if __name__ == "__main__":
    print("Georgian call app on http://localhost:5000  (open it in your browser)")
    app.run(host="0.0.0.0", port=5000)
