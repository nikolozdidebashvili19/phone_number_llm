"""Shared Georgian-assistant core: Gemini brain + edge-tts voice.

Imported by both the Telegram bot (bot.py) and the phone webhook (call.py) so the
prompt, model, and voice stay in one place. `respond()` mutates a history list you
own, so each caller keeps its own conversation memory.
"""

import os
import uuid
import asyncio

import requests
import edge_tts

try:
    from dotenv import load_dotenv
    load_dotenv()                 # read GEMINI_API_KEY etc. from .env
except ImportError:
    pass                          # dotenv is optional; env vars still work if exported

KEY = os.environ["GEMINI_API_KEY"]
MODEL = "gemini-3.6-flash"        # smartest model on this key's free tier (thinking + audio)
# Live captioning fires a request per phrase, so it needs a high requests-per-minute
# limit more than deep reasoning. The "lite" model has a much higher free-tier RPM.
TRANSCRIBE_MODEL = "gemini-flash-lite-latest"
VOICE = "ka-GE-EkaNeural"         # female; ka-GE-GiorgiNeural for male

# Base persona/rules, shared by every channel.
SYSTEM = """შენ ხარ ხმოვანი ასისტენტი ხანდაზმული და შშმ მომხმარებლებისთვის.
1. უპასუხე მხოლოდ ქართულად.
2. მარტივი სიტყვები. ციფრები დაწერე სიტყვებით (მაგ: "ოცი" და არა "20").
3. არასდროს გამოიყენო ემოჯი, მარკდაუნი ან ვარსკვლავები. ნაბიჯებს ჩამოთვალე სიტყვებით (მაგ: "პირველი", "მეორე").
4. თუ შეტყობინება გაუგებარია, თავაზიანად სთხოვე გამეორება.
5. სამედიცინო ან იურიდიულ კითხვაზე ურჩიე სპეციალისტთან მისვლა."""

# Per-channel answer length. Telegram can afford long, detailed replies; a live
# phone call cannot — long silences and minute-long spoken answers feel terrible.
DETAILED_STYLE = "უპასუხე სრულად, დეტალურად და გასაგებად. ახსენი საკითხი ბოლომდე, საჭიროების შემთხვევაში ნაბიჯ-ნაბიჯ."
BRIEF_STYLE = "ეს ცოცხალი სატელეფონო საუბარია. უპასუხე მოკლედ, ბუნებრივად და გასაგებად, მაქსიმუმ ორი-სამი წინადადებით."


def respond(history, parts, style=DETAILED_STYLE, max_output=4096):
    """Append a user turn to `history`, call Gemini, store + return the reply text.

    `parts` is a Gemini `parts` list (text and/or inline audio). `style` tunes answer
    length per channel. This is a "thinking" model: reasoning tokens are drawn from
    max_output, so the cap must cover thinking AND the answer or the reply comes back
    empty; thinkingLevel "low" keeps latency down.
    """
    system = SYSTEM + "\n" + style if style else SYSTEM
    history.append({"role": "user", "parts": parts})
    r = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={KEY}",
        json={
            "system_instruction": {"parts": [{"text": system}]},
            "contents": history[-8:],
            "generationConfig": {
                "maxOutputTokens": max_output,
                "temperature": 0.4,
                "thinkingConfig": {"thinkingLevel": "low"},
            },
        },
        timeout=60,
    )
    r.raise_for_status()
    data = r.json()
    try:
        out = data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except (KeyError, IndexError):
        history.pop()             # drop the bad user turn so history stays valid
        raise RuntimeError(f"Gemini returned no text: {data}")
    history.append({"role": "model", "parts": [{"text": out}]})
    return out


def synthesize(text, path=None, rate="-10%"):
    """Render Georgian text to an MP3 file and return its path."""
    path = path or f"{uuid.uuid4().hex}.mp3"
    asyncio.run(edge_tts.Communicate(text, VOICE, rate=rate).save(path))
    return path


TRANSCRIBE_SYSTEM = """შენ ხარ ქართული მეტყველების ზუსტი ტრანსკრიბატორი.
დააბრუნე მხოლოდ ის ტექსტი, რაც აუდიოში ითქვა, ქართულ ენაზე.
არ დაამატო ახსნა, კომენტარი, ემოჯი ან ბრჭყალები.
თუ აუდიოში მეტყველება არ ისმის ან გაუგებარია, დააბრუნე ცარიელი პასუხი."""


def transcribe(audio_b64, mime="audio/wav"):
    """Transcribe a short Georgian audio clip to text (for live captioning).
    Returns "" when there's no clear speech."""
    r = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{TRANSCRIBE_MODEL}:generateContent?key={KEY}",
        json={
            "system_instruction": {"parts": [{"text": TRANSCRIBE_SYSTEM}]},
            "contents": [{"role": "user", "parts": [
                {"inline_data": {"mime_type": mime, "data": audio_b64}},
                {"text": "ჩაწერე ტექსტად ის, რაც ითქვა."},
            ]}],
            # Transcription needs no reasoning — keep it fast and literal.
            "generationConfig": {"maxOutputTokens": 400, "temperature": 0.0},
        },
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except (KeyError, IndexError):
        return ""
    # Guard against the model narrating "no speech" instead of staying silent.
    if text in ("", "-", "—") or text.startswith("(") or text.startswith("["):
        return ""
    return text
