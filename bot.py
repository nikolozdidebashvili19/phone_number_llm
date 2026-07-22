"""Georgian voice assistant — Telegram bot.

Flow: user sends a voice message (or text) -> Gemini (audio-in, Georgian-out)
-> edge-tts renders Georgian speech -> bot replies with text + a voice bubble.

Run:
    export TELEGRAM_BOT_TOKEN=123456:ABC...
    export GEMINI_API_KEY=AIza...
    python bot.py
"""

import os
import uuid
import base64
import asyncio

import requests
import edge_tts
import telebot

try:
    from dotenv import load_dotenv
    load_dotenv()                 # read TELEGRAM_BOT_TOKEN / GEMINI_API_KEY from .env
except ImportError:
    pass                          # dotenv is optional; env vars still work if exported

BOT = telebot.TeleBot(os.environ["TELEGRAM_BOT_TOKEN"])
KEY = os.environ["GEMINI_API_KEY"]
MODEL = "gemini-3.6-flash"        # smartest model on this key's free tier (thinking + audio)
VOICE = "ka-GE-EkaNeural"         # female; ka-GE-GiorgiNeural for male
MAX_VOICE_SECONDS = 45            # ask for a shorter clip beyond this

SYSTEM = """შენ ხარ ხმოვანი ასისტენტი ხანდაზმული და შშმ მომხმარებლებისთვის Telegram-ში.
1. უპასუხე მხოლოდ ქართულად.
2. უპასუხე სრულად, დეტალურად და გასაგებად. ახსენი საკითხი ბოლომდე, საჭიროების შემთხვევაში ნაბიჯ-ნაბიჯ. ნუ იქნები ზედმეტად მოკლე.
3. მარტივი სიტყვები. ციფრები დაწერე სიტყვებით (მაგ: "ოცი" და არა "20").
4. არასდროს გამოიყენო ემოჯი, მარკდაუნი ან ვარსკვლავები. ნაბიჯებს ჩამოთვალე სიტყვებით (მაგ: "პირველი", "მეორე").
5. თუ ხმოვანი შეტყობინება გაუგებარია, თავაზიანად სთხოვე გამეორება.
6. სამედიცინო ან იურიდიულ კითხვაზე ურჩიე სპეციალისტთან მისვლა."""

# Per-chat conversation history: {chat_id: [ {role, parts}, ... ] }
sessions = {}


def gemini(sid, parts):
    """Append a user turn, call Gemini with recent history, store + return the reply."""
    h = sessions.setdefault(sid, [])
    h.append({"role": "user", "parts": parts})
    r = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={KEY}",
        json={
            "system_instruction": {"parts": [{"text": SYSTEM}]},
            "contents": h[-8:],
            # This is a "thinking" model: reasoning tokens are drawn from maxOutputTokens,
            # so the cap must be high enough to cover thinking AND the spoken answer, or the
            # reply comes back empty/truncated. thinkingLevel "low" keeps latency down.
            "generationConfig": {
                "maxOutputTokens": 4096,
                "temperature": 0.4,
                "thinkingConfig": {"thinkingLevel": "low"},
            },
        },
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    try:
        out = data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except (KeyError, IndexError):
        # No text part — drop the bad user turn so history stays valid, then bubble up.
        h.pop()
        raise RuntimeError(f"Gemini returned no text: {data}")
    h.append({"role": "model", "parts": [{"text": out}]})
    print(f"👤 (chat {sid})\n🤖 {out}\n")
    return out


def tts(text):
    """Render Georgian text to an MP3 file and return its path."""
    fn = f"{uuid.uuid4().hex}.mp3"
    asyncio.run(edge_tts.Communicate(text, VOICE, rate="-10%").save(fn))
    return fn


def reply(m, answer):
    """Send the answer as text (doubles as transcript) and as a voice bubble."""
    BOT.send_message(m.chat.id, answer)
    BOT.send_chat_action(m.chat.id, "record_voice")
    fn = tts(answer)
    try:
        with open(fn, "rb") as f:
            BOT.send_voice(m.chat.id, f)
    finally:
        os.remove(fn)


@BOT.message_handler(commands=["start"])
def start(m):
    sessions.pop(m.chat.id, None)
    reply(m, "გამარჯობა. მე ვარ თქვენი ხმოვანი დამხმარე. "
             "გამომიგზავნეთ ხმოვანი შეტყობინება ან დამისვით კითხვა.")


@BOT.message_handler(content_types=["voice"])
def on_voice(m):
    if m.voice.duration and m.voice.duration > MAX_VOICE_SECONDS:
        reply(m, "გთხოვთ, გამომიგზავნოთ უფრო მოკლე ხმოვანი შეტყობინება.")
        return
    BOT.send_chat_action(m.chat.id, "typing")
    f = BOT.get_file(m.voice.file_id)
    audio = BOT.download_file(f.file_path)       # OGG/Opus bytes
    parts = [
        {"inline_data": {"mime_type": "audio/ogg",
                         "data": base64.b64encode(audio).decode()}},
        {"text": "მოისმინე ეს ხმოვანი შეტყობინება და უპასუხე ქართულად."},
    ]
    try:
        reply(m, gemini(m.chat.id, parts))
    except Exception as e:
        print("ERR:", e)
        reply(m, "ბოდიშს გიხდით, ვერ გავიგე. გთხოვთ, გაიმეოროთ.")


@BOT.message_handler(content_types=["text"])
def on_text(m):
    BOT.send_chat_action(m.chat.id, "typing")
    try:
        reply(m, gemini(m.chat.id, [{"text": m.text}]))
    except Exception as e:
        print("ERR:", e)
        reply(m, "ბოდიშს გიხდით, სცადეთ თავიდან.")


if __name__ == "__main__":
    print("Bot is running. Press Ctrl+C to stop.")
    BOT.infinity_polling()
