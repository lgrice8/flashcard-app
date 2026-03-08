"""
Flashcard App
-------------
Per-session uploaded decks (temporary, reverts to default when session ends).
Default deck loaded from config.json on startup.
Deployable to Render via gunicorn.
"""

import csv
import io
import json
import os

from flask import Flask, jsonify, render_template, request, session

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-in-production")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
PASSCODE = "4321"


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_config() -> dict:
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"default_deck": ""}


def parse_csv_bytes(raw_bytes: bytes) -> list[dict]:
    """Decode and parse CSV bytes; return list of {front, back} dicts."""
    raw = None
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            raw = raw_bytes.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if raw is None:
        raise ValueError("Could not decode file. Save it as UTF-8 and try again.")

    reader = csv.reader(io.StringIO(raw))
    rows = list(reader)
    if len(rows) < 2:
        raise ValueError("Need at least a header row and one data row.")

    cards = []
    for row in rows[1:]:
        front = row[0].strip() if len(row) > 0 else ""
        back  = row[1].strip() if len(row) > 1 else ""
        if front:
            cards.append({"front": front, "back": back})

    if not cards:
        raise ValueError("No valid cards found. Make sure column 1 has content.")
    return cards


def load_default_deck() -> dict:
    config = load_config()
    filename = config.get("default_deck", "")
    if not filename:
        return {"filename": None, "cards": []}

    filepath = os.path.join(BASE_DIR, filename)
    if not os.path.exists(filepath):
        print(f"  Warning: default deck '{filename}' not found at {filepath}")
        return {"filename": None, "cards": []}

    try:
        with open(filepath, "rb") as f:
            cards = parse_csv_bytes(f.read())
        n = len(cards)
        print(f'  Default deck loaded: "{filename}" ({n} card{"s" if n != 1 else ""})')
        return {"filename": filename, "cards": cards}
    except Exception as exc:
        print(f"  Warning: could not load default deck — {exc}")
        return {"filename": None, "cards": []}


# Load once at startup (shared, read-only reference)
default_deck: dict = load_default_deck()


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/game")
def game():
    return render_template("game.html")


@app.route("/api/deck")
def api_deck():
    """Return the active deck for this session."""
    if "deck" in session:
        return jsonify({**session["deck"], "is_temporary": True})
    return jsonify({**default_deck, "is_temporary": False})


@app.route("/api/verify-passcode", methods=["POST"])
def verify_passcode():
    data = request.get_json(silent=True) or {}
    if data.get("passcode") == PASSCODE:
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "Incorrect passcode"}), 401


@app.route("/api/upload", methods=["POST"])
def api_upload():
    if "file" not in request.files:
        return jsonify({"error": "No file in request"}), 400

    uploaded = request.files["file"]
    if not uploaded.filename:
        return jsonify({"error": "Empty filename"}), 400
    if not uploaded.filename.lower().endswith(".csv"):
        return jsonify({"error": "Please upload a .csv file"}), 400

    try:
        cards = parse_csv_bytes(uploaded.read())
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    # Store only in session — not persisted globally
    session["deck"] = {"filename": uploaded.filename, "cards": cards}
    n = len(cards)
    print(f'  Session deck: "{uploaded.filename}" ({n} card{"s" if n != 1 else ""})')
    return jsonify({"filename": uploaded.filename, "cards": cards, "is_temporary": True})


@app.route("/api/reset", methods=["POST"])
def api_reset():
    """Clear session deck; caller reverts to default."""
    session.pop("deck", None)
    return jsonify({**default_deck, "is_temporary": False})


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print()
    print("=" * 52)
    print("  Flashcard App")
    print("=" * 52)
    print(f"  http://localhost:{port}")
    print("=" * 52)
    print()
    app.run(host="0.0.0.0", port=port, debug=False)
