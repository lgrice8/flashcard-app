"""
Flashcard App
-------------
Multi-deck support: scans for CSV files on startup (up to 5, alphabetically).
Uploaded decks stored per-session (temporary).
Deployable to Render via gunicorn.
"""

import csv
import glob
import io
import os
from datetime import datetime

from flask import Flask, jsonify, make_response, redirect, render_template, request, session, url_for

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-in-production")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PASSCODE = "4321"
ACCESS_PASSCODE = "3911"
MAX_ACCESS_ATTEMPTS = 5


# ── Helpers ───────────────────────────────────────────────────────────────────

def is_production():
    """Returns True if running on Render (production), False if local."""
    return bool(os.environ.get('RENDER')) or bool(os.environ.get('PORT'))


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


def load_all_decks() -> dict:
    """Scan BASE_DIR for CSV files, load up to 5 alphabetically."""
    pattern = os.path.join(BASE_DIR, "*.csv")
    csv_files = sorted(glob.glob(pattern))[:5]

    decks = {}
    for filepath in csv_files:
        filename = os.path.basename(filepath)
        try:
            with open(filepath, "rb") as f:
                cards = parse_csv_bytes(f.read())
            if cards:
                decks[filename] = {"cards": cards, "count": len(cards)}
                n = len(cards)
                print(f'  Deck loaded: "{filename}" ({n} card{"s" if n != 1 else ""})')
        except Exception as exc:
            print(f'  Warning: could not load "{filename}" — {exc}')

    return decks


# Load all decks at startup (shared, read-only)
ALL_DECKS: dict = load_all_decks()
DEFAULT_DECK: str | None = sorted(ALL_DECKS.keys())[0] if ALL_DECKS else None


def get_current_deck_name() -> str | None:
    """Get active deck key from session, falling back to default."""
    current = session.get("current_deck")
    if current == "__uploaded__" and "deck" in session:
        return "__uploaded__"
    if current and current in ALL_DECKS:
        return current
    return DEFAULT_DECK


def get_current_deck_data() -> dict:
    """Return active deck as {filename, cards, count, is_temporary, current_deck}."""
    current = get_current_deck_name()

    if current == "__uploaded__" and "deck" in session:
        d = session["deck"]
        return {
            "filename": d["filename"],
            "cards": d["cards"],
            "count": len(d["cards"]),
            "is_temporary": True,
            "current_deck": "__uploaded__",
        }

    if current and current in ALL_DECKS:
        d = ALL_DECKS[current]
        return {
            "filename": current,
            "cards": d["cards"],
            "count": d["count"],
            "is_temporary": False,
            "current_deck": current,
        }

    return {"filename": None, "cards": [], "count": 0, "is_temporary": False, "current_deck": None}


# ── Authentication ─────────────────────────────────────────────────────────────

@app.before_request
def check_authentication():
    """Require access passcode only on Render (production)."""
    if is_production():
        if request.endpoint not in ('login', 'static') and not session.get('authenticated'):
            return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
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
    deck = get_current_deck_data()
    cards = deck.get("cards", [])
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
    return jsonify(get_current_deck_data())


@app.route("/api/decks")
def api_decks():
    """Return list of all available decks plus the active deck key."""
    decks = [
        {"filename": k, "count": v["count"], "is_temporary": False, "key": k}
        for k, v in ALL_DECKS.items()
    ]
    # Include uploaded deck if present in session
    if "deck" in session:
        uploaded = session["deck"]
        decks.append({
            "filename": uploaded["filename"],
            "count": len(uploaded["cards"]),
            "is_temporary": True,
            "key": "__uploaded__",
        })
    current = get_current_deck_name()
    return jsonify({"decks": decks, "current": current, "default": DEFAULT_DECK})


@app.route("/api/switch_deck", methods=["POST"])
def api_switch_deck():
    """Switch the active deck for this session."""
    data = request.get_json(silent=True) or {}
    deck_key = data.get("deck_key", "")

    if deck_key == "__uploaded__":
        if "deck" in session:
            session["current_deck"] = "__uploaded__"
            d = session["deck"]
            return jsonify({
                "filename": d["filename"],
                "cards": d["cards"],
                "count": len(d["cards"]),
                "is_temporary": True,
                "current_deck": "__uploaded__",
            })
        return jsonify({"error": "No uploaded deck in session"}), 400

    if deck_key in ALL_DECKS:
        session["current_deck"] = deck_key
        d = ALL_DECKS[deck_key]
        return jsonify({
            "filename": deck_key,
            "cards": d["cards"],
            "count": d["count"],
            "is_temporary": False,
            "current_deck": deck_key,
        })

    return jsonify({"error": "Deck not found"}), 400


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

    session["deck"] = {"filename": uploaded.filename, "cards": cards}
    session["current_deck"] = "__uploaded__"
    n = len(cards)
    print(f'  Session deck: "{uploaded.filename}" ({n} card{"s" if n != 1 else ""})')
    return jsonify({
        "filename": uploaded.filename,
        "cards": cards,
        "count": n,
        "is_temporary": True,
        "current_deck": "__uploaded__",
    })


@app.route("/api/reset", methods=["POST"])
def api_reset():
    """Clear session deck; reverts to default."""
    session.pop("deck", None)
    session.pop("current_deck", None)
    return jsonify(get_current_deck_data())


# ── Flag routes ────────────────────────────────────────────────────────────────

@app.route("/flag/<int:card_id>", methods=["POST"])
def toggle_flag(card_id):
    data = request.get_json(silent=True) or {}
    word = data.get("word", "")
    definition = data.get("definition", "")
    deck = data.get("deck", "")  # deck key for namespacing flags

    flagged = session.get("flagged_cards", [])
    existing_idx = next(
        (i for i, c in enumerate(flagged)
         if c["card_id"] == card_id and c.get("deck") == deck),
        None
    )

    if existing_idx is not None:
        flagged.pop(existing_idx)
        is_flagged = False
    else:
        flagged.append({"card_id": card_id, "word": word, "definition": definition, "deck": deck})
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
    selected_uids = set(data.get("selected_ids", []))  # composite "deck___cardid" strings

    if not selected_uids:
        return jsonify({"error": "Please select at least one word to download"}), 400

    flagged = session.get("flagged_cards", [])
    selected = []
    for c in flagged:
        uid = f"{c.get('deck', '')}___{c['card_id']}"
        if uid in selected_uids:
            selected.append(c)

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
    print("  Flashcard App — Multi-Deck")
    print("=" * 52)
    print(f"  http://localhost:{port}")
    if DEFAULT_DECK:
        print(f"  Default deck : {DEFAULT_DECK}")
    else:
        print("  Warning: No valid CSV decks found!")
    print(f"  Decks loaded : {len(ALL_DECKS)}")
    print("=" * 52)
    print()
    app.run(host="0.0.0.0", port=port, debug=False)
