"""Vercel serverless entry for the Georgian live captioner.

Self-contained (no edge-tts / telebot) so the serverless bundle stays lean: it only
transcribes Georgian audio and labels speakers by voice pitch. Set GEMINI_API_KEY as
a Vercel Environment Variable.
"""

import os
import io
import wave
import base64

import requests
import numpy as np
from flask import Flask, request, jsonify, Response

KEY = os.environ.get("GEMINI_API_KEY", "")
TRANSCRIBE_MODEL = "gemini-flash-lite-latest"   # high free RPM, good Georgian

TRANSCRIBE_SYSTEM = """შენ ხარ ქართული მეტყველების ზუსტი ტრანსკრიბატორი.
დააბრუნე მხოლოდ ის ტექსტი, რაც აუდიოში ითქვა, ქართულ ენაზე.
არ დაამატო ახსნა, კომენტარი, ემოჯი ან ბრჭყალები.
თუ აუდიოში მეტყველება არ ისმის ან გაუგებარია, დააბრუნე ცარიელი პასუხი."""

app = Flask(__name__)

# ---- speaker identification by voice pitch (labels persist while the instance is warm) ----
F_MIN, F_MAX = 70, 350
TOLERANCE_HZ = 25.0
_registry = {}


def estimate_pitch(wav_bytes):
    try:
        w = wave.open(io.BytesIO(wav_bytes), "rb")
        sr = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32)
        if w.getnchannels() == 2:
            x = x[::2]
    except (wave.Error, EOFError, ValueError):
        return None
    if x.size == 0:
        return None
    frame = int(0.04 * sr)
    hop = int(0.02 * sr)
    if frame < 2:
        return None
    lag_min, lag_max = int(sr / F_MAX), int(sr / F_MIN)
    overall_rms = np.sqrt(np.mean(x * x)) or 1.0
    f0s = []
    for i in range(0, len(x) - frame, hop):
        seg = x[i:i + frame]
        if np.sqrt(np.mean(seg * seg)) < 0.5 * overall_rms:
            continue
        seg = seg - seg.mean()
        corr = np.correlate(seg, seg, "full")[frame - 1:]
        if lag_max >= len(corr) or corr[0] <= 0:
            continue
        region = corr[lag_min:lag_max]
        if region.size == 0:
            continue
        lag = int(np.argmax(region)) + lag_min
        if corr[lag] < 0.3 * corr[0]:
            continue
        f0s.append(sr / lag)
    return float(np.median(f0s)) if f0s else None


def identify(sid, wav_bytes):
    pitch = estimate_pitch(wav_bytes)
    reg = _registry.setdefault(sid, [])
    if pitch is None:
        return reg[-1]["label"] if reg else "მოსაუბრე"
    best, best_d = None, 1e9
    for s in reg:
        d = abs(s["pitch"] - pitch)
        if d < best_d:
            best, best_d = s, d
    if best and best_d <= TOLERANCE_HZ:
        best["pitch"] = (best["pitch"] * best["count"] + pitch) / (best["count"] + 1)
        best["count"] += 1
        return best["label"]
    label = f"მოსაუბრე {len(reg) + 1}"
    reg.append({"label": label, "pitch": pitch, "count": 1})
    return label


def transcribe(audio_b64, mime="audio/wav"):
    r = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{TRANSCRIBE_MODEL}:generateContent?key={KEY}",
        json={
            "system_instruction": {"parts": [{"text": TRANSCRIBE_SYSTEM}]},
            "contents": [{"role": "user", "parts": [
                {"inline_data": {"mime_type": mime, "data": audio_b64}},
                {"text": "ჩაწერე ტექსტად ის, რაც ითქვა."},
            ]}],
            "generationConfig": {"maxOutputTokens": 400, "temperature": 0.0},
        },
        timeout=20,
    )
    r.raise_for_status()
    data = r.json()
    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except (KeyError, IndexError):
        return ""
    if text in ("", "-", "—") or text.startswith("(") or text.startswith("["):
        return ""
    return text


@app.route("/")
def index():
    return Response(PAGE, mimetype="text/html")


@app.route("/caption", methods=["POST"])
def caption():
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
    return jsonify(text=text, speaker=identify(sid, audio))


@app.route("/reset", methods=["POST"])
def reset():
    _registry.pop(request.form.get("sid", "anon"), None)
    return jsonify(ok=True)


@app.route("/health")
def health():
    return "ok"


PAGE = r"""<!doctype html>
<html lang="ka">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<title>ცოცხალი სუბტიტრები</title>
<style>
  * { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
  html, body { height: 100%; margin: 0; }
  body {
    display: flex; flex-direction: column;
    font-family: system-ui, "Segoe UI", sans-serif;
    background: #0b1220; color: #f8fafc;
  }
  header {
    padding: 14px 18px; display: flex; align-items: center; justify-content: space-between;
    border-bottom: 1px solid #1e293b;
  }
  header h1 { margin: 0; font-size: 16px; font-weight: 600; color: #cbd5e1; }
  #dot { width: 12px; height: 12px; border-radius: 50%; background: #475569; }
  #dot.live { background: #22c55e; animation: pulse 1.2s infinite; }
  #dot.thinking { background: #f59e0b; }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.35} }

  #captions {
    flex: 1; overflow-y: auto; padding: 24px 22px 10px;
    display: flex; flex-direction: column; justify-content: flex-end; gap: 16px;
  }
  .line {
    font-size: clamp(26px, 5.5vw, 46px); line-height: 1.35; font-weight: 600;
    color: #e2e8f0;
  }
  .who {
    display: inline-block; font-size: 0.5em; font-weight: 700; vertical-align: middle;
    padding: 2px 10px; border-radius: 20px; margin-right: 12px;
    background: var(--c, #475569); color: #05121f;
  }
  .line:last-child { filter: brightness(1.15); }
  #hint { color: #64748b; font-size: 18px; text-align: center; margin: auto; }

  footer { padding: 18px 16px 30px; text-align: center; border-top: 1px solid #1e293b; }
  #status { font-size: 15px; color: #94a3b8; min-height: 20px; margin-bottom: 12px; }
  #btn {
    padding: 16px 40px; border-radius: 40px; border: none; cursor: pointer;
    background: #22c55e; color: #05240f; font-size: 20px; font-weight: 700;
  }
  #btn.on { background: #dc2626; color: #fff; }
</style>
</head>
<body>
  <header>
    <h1>ცოცხალი სუბტიტრები</h1>
    <div id="dot" title="status"></div>
  </header>

  <div id="captions"><div id="hint">დააჭირეთ „დაწყება"-ს და მიუშვირეთ ტელეფონი მოსაუბრეს</div></div>

  <footer>
    <div id="status">გამორთულია</div>
    <button id="btn">დაწყება</button>
  </footer>

<script>
const btn = document.getElementById('btn');
const statusEl = document.getElementById('status');
const dot = document.getElementById('dot');
const capEl = document.getElementById('captions');
const hint = document.getElementById('hint');

const sid = localStorage.capSid || (localStorage.capSid = Math.random().toString(36).slice(2));
const SPEAKER_COLORS = ['#22c55e', '#38bdf8', '#f59e0b', '#f472b6', '#a78bfa', '#facc15'];
const speakerColor = {};

let ctx, source, processor, stream, running = false;
let speaking = false, seg = [], lookback = [], silenceStart = 0, segStart = 0;
let noiseFloor = 0.005;
let queue = [], working = false;

const SILENCE_MS = 700;
const MIN_MS = 350;
const MAX_MS = 12000;

btn.onclick = () => running ? stop() : start();

async function start() {
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (e) { setStatus('მიკროფონზე წვდომა ვერ მოხერხდა'); return; }
  ctx = new (window.AudioContext || window.webkitAudioContext)();
  source = ctx.createMediaStreamSource(stream);
  processor = ctx.createScriptProcessor(4096, 1, 1);
  processor.onaudioprocess = onAudio;
  source.connect(processor);
  processor.connect(ctx.destination);
  running = true;
  btn.textContent = 'გაჩერება'; btn.classList.add('on');
  dot.classList.add('live');
  setStatus('ვუსმენ...');
  if (hint) hint.remove();
}

function stop() {
  running = false;
  try { processor.disconnect(); source.disconnect(); stream.getTracks().forEach(t => t.stop()); ctx.close(); } catch (e) {}
  speaking = false; seg = []; lookback = [];
  btn.textContent = 'დაწყება'; btn.classList.remove('on');
  dot.classList.remove('live', 'thinking');
  setStatus('გამორთულია');
}

function onAudio(e) {
  const buf = e.inputBuffer.getChannelData(0);
  let sum = 0; for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i];
  const rms = Math.sqrt(sum / buf.length);
  const now = performance.now();

  lookback.push(new Float32Array(buf));
  if (lookback.length > 3) lookback.shift();

  const thresh = Math.max(0.01, noiseFloor * 4);
  if (!speaking && rms < thresh) noiseFloor = noiseFloor * 0.95 + rms * 0.05;

  if (rms > thresh) {
    if (!speaking) { speaking = true; segStart = now; seg = lookback.slice(); }
    else seg.push(new Float32Array(buf));
    silenceStart = 0;
  } else if (speaking) {
    seg.push(new Float32Array(buf));
    if (!silenceStart) silenceStart = now;
    if (now - silenceStart > SILENCE_MS) endPhrase(now);
  }
  if (speaking && now - segStart > MAX_MS) endPhrase(now);
}

function endPhrase(now) {
  const dur = now - segStart;
  const frames = seg;
  speaking = false; seg = []; silenceStart = 0;
  if (dur > MIN_MS) { queue.push(frames); if (queue.length > 6) queue.shift(); pump(); }
}

async function pump() {
  if (working || !queue.length) return;
  working = true; dot.classList.add('thinking'); setStatus('ვშიფრავ...');
  const wav = encodeWAV(queue.shift(), ctx.sampleRate);
  const fd = new FormData();
  fd.append('audio', wav, 'phrase.wav');
  fd.append('sid', sid);
  try {
    const r = await fetch('/caption', { method: 'POST', body: fd });
    const j = await r.json();
    if (j.text) addLine(j.speaker, j.text);
  } catch (e) {}
  working = false;
  if (queue.length) pump();
  else if (running) { dot.classList.remove('thinking'); setStatus('ვუსმენ...'); }
}

function colorFor(speaker) {
  if (!speaker) return null;
  if (!(speaker in speakerColor)) {
    speakerColor[speaker] = SPEAKER_COLORS[Object.keys(speakerColor).length % SPEAKER_COLORS.length];
  }
  return speakerColor[speaker];
}

function addLine(speaker, text) {
  const d = document.createElement('div');
  d.className = 'line';
  const c = colorFor(speaker);
  if (speaker) {
    const chip = document.createElement('span');
    chip.className = 'who';
    chip.style.setProperty('--c', c);
    chip.textContent = speaker;
    d.appendChild(chip);
  }
  d.appendChild(document.createTextNode(text));
  capEl.appendChild(d);
  while (capEl.children.length > 12) capEl.removeChild(capEl.firstChild);
  capEl.scrollTop = capEl.scrollHeight;
}

function setStatus(t) { statusEl.textContent = t; }

function encodeWAV(frames, sampleRate) {
  let length = frames.reduce((a, c) => a + c.length, 0);
  const data = new Float32Array(length);
  let off = 0;
  for (const c of frames) { data.set(c, off); off += c.length; }
  const buffer = new ArrayBuffer(44 + data.length * 2);
  const view = new DataView(buffer);
  const w = (o, s) => { for (let i = 0; i < s.length; i++) view.setUint8(o + i, s.charCodeAt(i)); };
  w(0, 'RIFF'); view.setUint32(4, 36 + data.length * 2, true); w(8, 'WAVE');
  w(12, 'fmt '); view.setUint32(16, 16, true); view.setUint16(20, 1, true);
  view.setUint16(22, 1, true); view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true);
  w(36, 'data'); view.setUint32(40, data.length * 2, true);
  let o = 44;
  for (let i = 0; i < data.length; i++, o += 2) {
    let s = Math.max(-1, Math.min(1, data[i]));
    view.setInt16(o, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
  }
  return new Blob([view], { type: 'audio/wav' });
}
</script>
</body>
</html>"""
