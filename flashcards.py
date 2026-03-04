"""
Flashcard Server
----------------
Serves a shared flashcard deck to all devices on the local network.
The deck is stored server-side and persists to disk until replaced.
"""

import csv
import io
import json
import os
import socket

from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

# ── Shared deck (one instance, seen by every connected client) ────────────────
deck: dict = {"filename": None, "cards": []}

PERSIST_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "saved_deck.json")


# ── Disk persistence ──────────────────────────────────────────────────────────

def save_deck() -> None:
    try:
        with open(PERSIST_FILE, "w", encoding="utf-8") as fh:
            json.dump(deck, fh, ensure_ascii=False, indent=2)
    except OSError as exc:
        print(f"  Warning: could not save deck to disk — {exc}")


def load_deck() -> None:
    if not os.path.exists(PERSIST_FILE):
        return
    try:
        with open(PERSIST_FILE, encoding="utf-8") as fh:
            saved = json.load(fh)
        deck["filename"] = saved.get("filename")
        deck["cards"]    = saved.get("cards", [])
        n = len(deck["cards"])
        print(f"  Restored: \"{deck['filename']}\"  ({n} card{'s' if n != 1 else ''})")
    except Exception as exc:
        print(f"  Warning: could not restore saved deck — {exc}")


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/deck")
def api_deck():
    """Return the currently loaded deck (filename + cards list)."""
    return jsonify(deck)


@app.route("/api/upload", methods=["POST"])
def api_upload():
    """
    Accept a multipart CSV upload, parse it server-side, store it in
    the shared `deck` dict, persist to disk, and return the deck JSON.
    """
    if "file" not in request.files:
        return jsonify({"error": "No file in request"}), 400

    uploaded = request.files["file"]
    if not uploaded.filename:
        return jsonify({"error": "Empty filename"}), 400

    # Decode — try UTF-8 (with BOM), fall back to latin-1
    raw_bytes = uploaded.read()
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            raw = raw_bytes.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        return jsonify({"error": "Could not decode the file. Save it as UTF-8 and try again."}), 400

    # Parse CSV
    try:
        reader = csv.reader(io.StringIO(raw))
        rows   = list(reader)
    except Exception as exc:
        return jsonify({"error": f"CSV parse error: {exc}"}), 400

    if len(rows) < 2:
        return jsonify({"error": "Need at least a header row and one data row."}), 400

    # Build cards — row[0] = front, row[1] = back; skip header (rows[0])
    cards = []
    for row in rows[1:]:
        front = row[0].strip() if len(row) > 0 else ""
        back  = row[1].strip() if len(row) > 1 else ""
        if front:                            # skip blank lines
            cards.append({"front": front, "back": back})

    if not cards:
        return jsonify({"error": "No valid cards found. Make sure column 1 has content."}), 400

    # Update shared state & persist
    deck["filename"] = uploaded.filename
    deck["cards"]    = cards
    save_deck()

    n = len(cards)
    print(f"  New deck loaded: \"{uploaded.filename}\"  ({n} card{'s' if n != 1 else ''})")
    return jsonify(deck)


# ── Startup ───────────────────────────────────────────────────────────────────

def get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "unable-to-determine"


if __name__ == "__main__":
    PORT = 5000
    load_deck()
    ip = get_local_ip()

    print()
    print("=" * 52)
    print("  Flashcard Server")
    print("=" * 52)
    print(f"  Local access:    http://localhost:{PORT}")
    print(f"  Network access:  http://{ip}:{PORT}")
    print("=" * 52)
    print("  Ctrl+C to stop")
    print()

    app.run(host="0.0.0.0", port=PORT, debug=False)
