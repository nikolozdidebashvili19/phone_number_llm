"""One-command launcher for the Georgian phone line.

`python run_phone.py` does everything:
  1. starts a cloudflared tunnel and grabs its public https URL,
  2. points your SignalWire number's voice webhook at it over the REST API,
  3. runs the call server.

Fill these in .env first (Space -> API):
    SIGNALWIRE_SPACE_URL     e.g. your-space.signalwire.com
    SIGNALWIRE_PROJECT_ID    the UUID
    SIGNALWIRE_API_TOKEN     the PT... token
    SIGNALWIRE_PHONE_NUMBER  optional; e.g. +14155551234 (else all numbers are pointed here)
    GEMINI_API_KEY           already set

Needs cloudflared:  winget install --id Cloudflare.cloudflared  (then open a new terminal)
"""

import os
import re
import sys
import time
import atexit
import shutil
import threading
import subprocess

import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

PORT = 5000
PROJECT = os.environ.get("SIGNALWIRE_PROJECT_ID")
TOKEN = os.environ.get("SIGNALWIRE_API_TOKEN")
SPACE = os.environ.get("SIGNALWIRE_SPACE_URL", "").replace("https://", "").replace("http://", "").strip("/")
NUMBER = os.environ.get("SIGNALWIRE_PHONE_NUMBER")

_TRYCLOUDFLARE = re.compile(r"https://[a-z0-9\-]+\.trycloudflare\.com")


def find_cloudflared():
    """Locate cloudflared on PATH, or in the default winget install locations
    (so it works even if PATH hasn't refreshed since install)."""
    exe = shutil.which("cloudflared")
    if exe:
        return exe
    for root in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles")):
        if root:
            candidate = os.path.join(root, "cloudflared", "cloudflared.exe")
            if os.path.exists(candidate):
                return candidate
    return None


def start_cloudflared():
    """Launch a quick tunnel and return its public https URL."""
    exe = find_cloudflared()
    if not exe:
        sys.exit("❌ cloudflared not found. Install it with:\n"
                 "   winget install --id Cloudflare.cloudflared\n"
                 "   then open a NEW terminal and run this again.")
    proc = subprocess.Popen(
        [exe, "tunnel", "--url", f"http://localhost:{PORT}"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
    )
    atexit.register(proc.terminate)

    url = None
    deadline = time.time() + 40
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            if proc.poll() is not None:
                break
            continue
        m = _TRYCLOUDFLARE.search(line)
        if m:
            url = m.group(0)
            break
    if not url:
        sys.exit("❌ Couldn't obtain a cloudflared URL (check your internet connection).")

    # Keep draining cloudflared's output so its pipe never blocks.
    threading.Thread(target=lambda: [None for _ in proc.stdout], daemon=True).start()
    return url


def configure_number(public_url):
    """Point the SignalWire number(s) at <public_url>/incoming via the REST API."""
    voice_url = f"{public_url}/incoming"
    if not (PROJECT and TOKEN and SPACE):
        print("⚠️  SignalWire Space/creds missing — set the webhook manually in the dashboard:")
        print(f"    Number -> Voice -> When a Call Comes In (POST):  {voice_url}")
        return

    base = f"https://{SPACE}/api/laml/2010-04-01/Accounts/{PROJECT}/IncomingPhoneNumbers"
    auth = (PROJECT, TOKEN)
    try:
        r = requests.get(base + ".json", auth=auth, timeout=20)
        r.raise_for_status()
        numbers = r.json().get("incoming_phone_numbers", [])
    except Exception as e:
        print(f"⚠️  Could not list numbers ({e}). Set the webhook manually:")
        print(f"    Number -> Voice -> When a Call Comes In (POST):  {voice_url}")
        return

    if NUMBER:
        numbers = [n for n in numbers if n.get("phone_number") == NUMBER]
    if not numbers:
        print("⚠️  No matching phone number found on the account. Check SIGNALWIRE_PHONE_NUMBER.")
        return

    for n in numbers:
        try:
            upd = requests.post(f"{base}/{n['sid']}.json", auth=auth,
                                data={"VoiceUrl": voice_url, "VoiceMethod": "POST"}, timeout=20)
            upd.raise_for_status()
            print(f"✅ {n['phone_number']}  ->  {voice_url}")
        except Exception as e:
            print(f"⚠️  Failed to configure {n.get('phone_number')}: {e}")


def main():
    print("Starting cloudflared tunnel...")
    public_url = start_cloudflared()
    print(f"🌐 Public URL: {public_url}")

    os.environ["PUBLIC_URL"] = public_url
    import call                      # imported after PUBLIC_URL is set
    call.PUBLIC_URL = public_url

    configure_number(public_url)

    print("\n✅ Ready. Call your SignalWire number and speak Georgian after the beep.")
    print("   (Trial Space: add your phone as a Verified Caller ID first.)")
    print("   Press Ctrl+C to stop.\n")
    call.app.run(host="0.0.0.0", port=PORT)


if __name__ == "__main__":
    main()
