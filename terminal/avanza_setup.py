"""
Avanza two-factor setup helper.

WHY THIS EXISTS. Activating TOTP on Avanza is not "copy the secret into .env" --
Avanza makes you prove the secret works by pasting a generated 6-digit code back
into the activation screen. Without a way to generate that code you cannot
finish activation at all, which makes the secret useless. This prints it.

    python3.13 -m terminal.avanza_setup          # prompt for the secret, hidden
    python3.13 -m terminal.avanza_setup --watch  # keep printing as it rotates
    python3.13 -m terminal.avanza_setup --login  # read .env and test a real login

THE SECRET IS NEVER STORED, LOGGED OR ECHOED by this script. It is read with
getpass so it does not land in shell history, used in memory, and dropped. Put
it in .env yourself -- that file is gitignored.
"""

from __future__ import annotations

import argparse
import getpass
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from terminal.feeds.avanza import _totp  # noqa: E402


def _secret(arg: str | None) -> str:
    # Deliberately not a positional argument by default: a secret typed on the
    # command line is written to shell history in plain text.
    s = arg or getpass.getpass("Avanza TOTP secret (hidden, paste and press enter): ")
    s = s.strip()
    if not s:
        print("no secret given", file=sys.stderr)
        raise SystemExit(2)
    try:
        _totp(s)
    except Exception as e:
        print(f"\nThat does not decode as a base32 TOTP secret ({type(e).__name__}).\n"
              "You want the long string revealed by 'Kan du inte scanna QR-koden?',\n"
              "not the 6-digit code and not the QR image.", file=sys.stderr)
        raise SystemExit(2)
    return s


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate the TOTP code Avanza asks for.")
    ap.add_argument("--secret", help="avoid: this lands in shell history")
    ap.add_argument("--watch", action="store_true", help="keep printing as codes rotate")
    ap.add_argument("--login", action="store_true", help="test a real login using .env")
    ap.add_argument("--activate", action="store_true",
                    help="print the URL Avanza gives for activating two-factor login")
    a = ap.parse_args()

    if a.login or a.activate:
        import os
        for line in (ROOT / ".env").read_text().splitlines() if (ROOT / ".env").exists() else []:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip("\"'"))
        from terminal.feeds.avanza import AvanzaAuth
        auth = AvanzaAuth()
        missing = [k for k in ("AVANZA_USERNAME", "AVANZA_PASSWORD") if not os.getenv(k)]
        if missing:
            print(f"missing from .env: {', '.join(missing)}")
            raise SystemExit(1)
        if not os.getenv("AVANZA_TOTP_SECRET"):
            print("No AVANZA_TOTP_SECRET set — trying username and password alone,\n"
                  "so Avanza can say for itself whether that is enough.\n")
        ok, reason = auth.login()
        print(("LOGIN OK — " if ok else "LOGIN FAILED — ") + reason)
        if ok:
            print("Real-time quotes, order book depth and positions are unlocked.")
            return
        if auth.activation_url:
            if a.activate:
                # Printed to YOUR terminal only. It embeds a one-time ticket, so
                # it is never logged and should not be pasted into a chat.
                print("\nOpen this in a browser to activate two-factor login:\n")
                print("   " + auth.activation_url)
                print("\nChoose an authenticator app, reveal the base32 secret, then run\n"
                      "   python3.13 -m terminal.avanza_setup\n"
                      "to generate the code Avanza asks for to confirm activation.")
            else:
                print("\nRun with --activate to print the activation URL Avanza returned.")
        raise SystemExit(1)

    s = _secret(a.secret)
    if not a.watch:
        left = 30 - int(time.time()) % 30
        print(f"\n  {_totp(s)}   (valid {left}s)\n"
              "  Paste this into Avanza's activation screen to finish setup.")
        if left < 5:
            print("  ...that expires almost immediately — rerun for a fresh one.")
        return

    print("\nCtrl-C to stop.\n")
    last = None
    try:
        while True:
            code = _totp(s)
            left = 30 - int(time.time()) % 30
            if code != last:
                print(f"  {code}   (valid {left}s)")
                last = code
            time.sleep(1)
    except KeyboardInterrupt:
        print()


if __name__ == "__main__":
    main()
