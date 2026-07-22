# Georgian Voice Assistant

A voice assistant for elderly and disabled users, in Georgian. Front-ends share
one brain and voice:

- **🌐 Browser call** (`web.py`) — open a web page, tap, speak Georgian, hear the AI reply.
  Call-like, free, no phone number, works from any browser (incl. phones). **Recommended.**
- **💬 Telegram bot** (`bot.py`) — send a voice message or text, get a Georgian voice reply.
- **📞 Phone line** (`run_phone.py`) — call a real SignalWire number. Note: SignalWire's
  free trial geo-blocks Georgian (+995) numbers, so this needs a paid upgrade to use from Georgia.

**Brain:** Gemini (`gemini-3.6-flash`) — takes audio in, answers in Georgian.
**Voice:** `edge-tts` with `ka-GE-EkaNeural` — free, no key, natural Georgian speech.
Both live in [assistant.py](assistant.py) so the persona stays in one place.

## Files

| File | Role |
|---|---|
| `assistant.py` | Shared Gemini brain + edge-tts voice |
| `call.py` | SignalWire phone webhook (Flask) |
| `run_phone.py` | One-command launcher: tunnel + auto-configure number + server |
| `bot.py` | Telegram bot |

## Setup

```bash
pip install -U -r requirements.txt
cp .env.example .env      # then fill in the values
```

Fill `.env`:
- `GEMINI_API_KEY` — free at [Google AI Studio](https://aistudio.google.com/apikey)
- `TELEGRAM_BOT_TOKEN` — from [@BotFather](https://t.me/BotFather) (only for the Telegram bot)
- `SIGNALWIRE_SPACE_URL`, `SIGNALWIRE_PROJECT_ID`, `SIGNALWIRE_API_TOKEN` — SignalWire Space → API (only for the phone line)
- `SIGNALWIRE_PHONE_NUMBER` — optional; blank means "configure all my numbers"

## Run the browser call app (recommended)

```bash
python web.py
```
Open **http://localhost:5000** in Chrome/Edge on this laptop, allow the mic, tap the
button, speak Georgian, tap again to send. The AI answers in the `ka-GE` voice and the
Georgian text scrolls on screen (your live transcript for a demo).

**To use it on your phone:** the mic needs a secure (https) page, so expose it with a
free tunnel and open the printed https URL on the phone (same page, works over any wifi):
```bash
cloudflared tunnel --url http://localhost:5000
```

## Run the phone line

Install the tunnel once (then open a **new** terminal so it's on PATH):
```bash
winget install --id Cloudflare.cloudflared
```

Then just:
```bash
python run_phone.py
```

That single command starts a cloudflared tunnel, points your SignalWire number's voice
webhook at it automatically, and runs the server. Call the number and speak Georgian
after the beep.

> **Trial Space:** add your own phone as a **Verified Caller ID** in SignalWire first,
> or incoming calls will be blocked.

### How a call works
```
call in  → /incoming : play greeting, then <Record>
you talk → /handle   : download recording → Gemini (Georgian) → edge-tts → <Play> → <Record> again
```
Understanding uses Gemini on the recorded audio (not phone STT), so Georgian stays sharp.
Phone answers are kept short (2–3 sentences) so callers aren't stuck in long silences.
Expect ~5–12s per turn (silence detection + download + Gemini + TTS).

## Run the Telegram bot
```bash
python bot.py
```
Send `/start`, then a voice message or text. Telegram answers are detailed/long
(different from the phone's brief style).

## Notes
- `edge-tts` smoke test: `python -m edge_tts --voice ka-GE-EkaNeural --text "გამარჯობა" --write-media t.mp3`
- Pro Gemini models return `limit: 0` on this key's free tier — stay on `gemini-3.6-flash`.
- Generated call audio lands in `call_audio/` and is auto-deleted after 5 minutes.
- Never commit `.env`. If a token was ever exposed, rotate it (BotFather `/revoke`; SignalWire → new token).
