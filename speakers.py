"""Lightweight speaker labelling for the live captioner.

Each caption phrase is a separate, stateless request, so we can't rely on the model
to keep "Speaker 1 / Speaker 2" consistent across phrases. Instead we identify a
speaker by the pitch (fundamental frequency) of their voice and cluster phrases per
session. Deterministic, no extra model calls. It reliably separates clearly different
voices (e.g. a man and a woman); very similar voices may merge — good enough for a demo.
"""

import io
import wave

import numpy as np

# Human speaking pitch lives roughly in this band (Hz).
F_MIN, F_MAX = 70, 350
# Two phrases whose median pitch differ by less than this count as the same speaker.
TOLERANCE_HZ = 25.0

# Per-session speaker registry: {sid: [ {label, pitch, count}, ... ] }
_registry = {}


def estimate_pitch(wav_bytes):
    """Median fundamental frequency (Hz) of the voiced speech in a mono 16-bit WAV.
    Returns None if no clear voiced sound is found."""
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

    frame = int(0.04 * sr)          # 40 ms analysis frames
    hop = int(0.02 * sr)
    if frame < 2:
        return None
    lag_min, lag_max = int(sr / F_MAX), int(sr / F_MIN)
    overall_rms = np.sqrt(np.mean(x * x)) or 1.0

    f0s = []
    for i in range(0, len(x) - frame, hop):
        seg = x[i:i + frame]
        if np.sqrt(np.mean(seg * seg)) < 0.5 * overall_rms:
            continue                # skip near-silent / unvoiced frames
        seg = seg - seg.mean()
        corr = np.correlate(seg, seg, "full")[frame - 1:]
        if lag_max >= len(corr) or corr[0] <= 0:
            continue
        region = corr[lag_min:lag_max]
        if region.size == 0:
            continue
        lag = int(np.argmax(region)) + lag_min
        if corr[lag] < 0.3 * corr[0]:
            continue                # not periodic enough to be voiced
        f0s.append(sr / lag)

    return float(np.median(f0s)) if f0s else None


def identify(sid, wav_bytes):
    """Return a stable Georgian speaker label ("მოსაუბრე N") for this phrase."""
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


def reset(sid):
    _registry.pop(sid, None)
