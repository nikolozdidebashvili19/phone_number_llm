"""Georgian voice assistant — Telegram bot.

Flow: user sends a voice message (or text) -> Gemini (audio-in, Georgian-out)
-> edge-tts renders Georgian speech -> bot replies with text + a voice bubble.
Brain and voice live in assistant.py (shared with the phone line, call.py).

Run:
    python bot.py            # reads TELEGRAM_BOT_TOKEN / GEMINI_API_KEY from .env
"""

import os
import base64

import telebot

from assistant import respond, synthesize  # noqa: E402  (assistant loads .env on import)

BOT = telebot.TeleBot(os.environ["TELEGRAM_BOT_TOKEN"])
MAX_VOICE_SECONDS = 45            # ask for a shorter clip beyond this

# Per-chat conversation history: {chat_id: [ {role, parts}, ... ] }
sessions = {}


def brain(sid, parts):
    """Run one turn through Gemini using this chat's history, and log it."""
    out = respond(sessions.setdefault(sid, []), parts)
    print(f"👤 (chat {sid})\n🤖 {out}\n")
    return out


def reply(m, answer):
    """Send the answer as text (doubles as transcript) and as a voice bubble."""
    BOT.send_message(m.chat.id, answer)
    BOT.send_chat_action(m.chat.id, "record_voice")
    fn = synthesize(answer)
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
        reply(m, brain(m.chat.id, parts))
    except Exception as e:
        print("ERR:", e)
        reply(m, "ბოდიშს გიხდით, ვერ გავიგე. გთხოვთ, გაიმეოროთ.")


@BOT.message_handler(content_types=["text"])
def on_text(m):
    BOT.send_chat_action(m.chat.id, "typing")
    try:
        reply(m, brain(m.chat.id, [{"text": m.text}]))
    except Exception as e:
        print("ERR:", e)
        reply(m, "ბოდიშს გიხდით, სცადეთ თავიდან.")


if __name__ == "__main__":
    print("Bot is running. Press Ctrl+C to stop.")
    BOT.infinity_polling()
