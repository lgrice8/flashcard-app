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
from datetime import datetime

from flask import Flask, jsonify, make_response, redirect, render_template, request, session, url_for

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-in-production")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
PASSCODE = "4321"
ACCESS_PASSCODE = "3911"
MAX_ACCESS_ATTEMPTS = 5


# ── Helpers ───────────────────────────────────────────────────────────────────

def is_production():
    """Returns True if running on Render (production), False if local."""
    return bool(os.environ.get('RENDER')) or bool(os.environ.get('PORT'))


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


# ── Authentication ─────────────────────────────────────────────────────────────

@app.before_request
def check_authentication():
    """Require access passcode only on Render (production)."""
    if is_production():
        if request.endpoint not in ('login', 'static') and not session.get('authenticated'):
            return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    # Already authenticated → go to app
    if session.get('authenticated'):
        return redirect(url_for('index'))

    attempts = session.get('access_attempts', 0)
    locked = attempts >= MAX_ACCESS_ATTEMPTS

    if request.method == 'POST':
        if locked:
            return render_template('login.html', locked=True, max_attempts=MAX_ACCESS_ATTEMPTS)

        passcode = request.form.get('passcode', '').strip()
        if passcode == ACCESS_PASSCODE:
            session['authenticated'] = True
            session.pop('access_attempts', None)
            return redirect(url_for('index'))
        else:
            session['access_attempts'] = attempts + 1
            new_attempts = session['access_attempts']
            locked = new_attempts >= MAX_ACCESS_ATTEMPTS
            remaining = MAX_ACCESS_ATTEMPTS - new_attempts
            return render_template(
                'login.html',
                error=True,
                locked=locked,
                remaining=remaining,
                max_attempts=MAX_ACCESS_ATTEMPTS,
            )

    remaining = MAX_ACCESS_ATTEMPTS - attempts
    return render_template(
        'login.html',
        locked=locked,
        remaining=remaining,
        max_attempts=MAX_ACCESS_ATTEMPTS,
    )


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


def get_deck_data() -> list[dict]:
    """Return active deck as [{word, synonyms}] for game/quiz templates."""
    active = session["deck"] if "deck" in session else default_deck
    cards = active.get("cards", [])
    return [{"word": c["front"], "synonyms": [c["back"]]} for c in cards if c.get("front")]


@app.route("/game")
def game():
    return render_template("game.html", deck_data=get_deck_data())


@app.route("/quiz")
def quiz():
    return render_template("quiz.html", deck_data=get_deck_data())


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


# ── Flag routes ────────────────────────────────────────────────────────────────

@app.route("/flag/<int:card_id>", methods=["POST"])
def toggle_flag(card_id):
    data = request.get_json(silent=True) or {}
    word = data.get("word", "")
    definition = data.get("definition", "")

    flagged = session.get("flagged_cards", [])
    existing_idx = next((i for i, c in enumerate(flagged) if c["card_id"] == card_id), None)

    if existing_idx is not None:
        flagged.pop(existing_idx)
        is_flagged = False
    else:
        flagged.append({"card_id": card_id, "word": word, "definition": definition})
        is_flagged = True

    session["flagged_cards"] = flagged
    session.modified = True
    return jsonify({"is_flagged": is_flagged, "count": len(flagged)})


@app.route("/get_flagged_cards", methods=["POST"])
def get_flagged_cards():
    flagged = session.get("flagged_cards", [])
    return jsonify({"cards": flagged, "count": len(flagged)})


@app.route("/download_review_list", methods=["POST"])
def download_review_list():
    data = request.get_json(silent=True) or {}
    selected_ids = set(data.get("selected_ids", []))

    if not selected_ids:
        return jsonify({"error": "Please select at least one word to download"}), 400

    flagged = session.get("flagged_cards", [])
    selected = [c for c in flagged if c["card_id"] in selected_ids]

    if not selected:
        return jsonify({"error": "Please select at least one word to download"}), 400

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Word", "Definition"])
    for card in selected:
        writer.writerow([card["word"], card["definition"]])

    csv_content = output.getvalue()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"review_list_{timestamp}.csv"

    response = make_response(csv_content)
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@app.route("/clear_flags", methods=["POST"])
def clear_flags():
    session.pop("flagged_cards", None)
    session.modified = True
    return jsonify({"success": True, "count": 0})


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
