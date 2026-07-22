# Georgian Voice Assistant — Telegram Bot

A voice assistant for elderly and disabled users, in Georgian, inside Telegram.
Hold the mic button, speak → the bot understands and replies with a Georgian voice
message. Text works too. The chat itself is your live transcript.

**Pipeline:** voice message → Gemini (audio in, Georgian text out) → `edge-tts`
(`ka-GE-EkaNeural`) → MP3 → `sendVoice`. No telephony, no webhook, no tunnel,
no API key for TTS.

## Setup

1. **Bot token** — Telegram → [@BotFather](https://t.me/BotFather) → `/newbot` → copy the token.
2. **Gemini key** — free at [Google AI Studio](https://aistudio.google.com/apikey) (no credit card).
3. **Install deps:**
   ```bash
   pip install -U -r requirements.txt
   ```
4. **Smoke test the Georgian voice** (do this first — it's the one hard constraint):
   ```bash
   python -m edge_tts --voice ka-GE-EkaNeural --text "გამარჯობა, როგორ დაგეხმაროთ?" --write-media t.mp3
   ```
   If `t.mp3` plays, you're set.

## Run

PowerShell (Windows):
```powershell
$env:TELEGRAM_BOT_TOKEN="123456:ABC..."
$env:GEMINI_API_KEY="AIza..."
python bot.py
```

bash (macOS/Linux/Git Bash):
```bash
export TELEGRAM_BOT_TOKEN=123456:ABC...
export GEMINI_API_KEY=AIza...
python bot.py
```

Then open your bot in Telegram and send `/start`.

## Notes

- `edge_tts` must be called as `python -m edge_tts` if the `edge-tts` script isn't on PATH.
- Conversation memory is per-chat, last 8 turns (`h[-8:]`). Say **„გამიმეორე"** to test it.
- Voice clips longer than `MAX_VOICE_SECONDS` (45s) get a polite "please send shorter" reply.
- Gemini free tier is ~10–15 req/min — plenty for a demo, don't let the whole team hammer it at once.
- Run `pip install -U edge-tts` on demo morning; Microsoft occasionally rotates tokens.
- If Telegram is blocked on venue wifi, use a phone hotspot — long polling works over anything.

## Config knobs (top of `bot.py`)

| Constant | Default | Meaning |
|---|---|---|
| `MODEL` | `gemini-2.5-flash` | Gemini model id (check AI Studio for current free id) |
| `VOICE` | `ka-GE-EkaNeural` | TTS voice (`ka-GE-GiorgiNeural` for male) |
| `MAX_VOICE_SECONDS` | `45` | Reject clips longer than this |
