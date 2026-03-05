# Flashcard App

A responsive flashcard web application built with Python Flask.

- Flip cards with a tap or click
- Next / Previous navigation with progress bar (Card X of Y)
- Shuffle and Restart
- Passcode-protected upload of custom CSV decks
- Uploaded decks are **session-only** — reverts to default when you close the browser
- Mobile-friendly, works on any device

---

## Local Setup

### 1. Clone the repo

```bash
git clone https://github.com/lgrice8/flashcard-app.git
cd flashcard-app
```

### 2. Create a virtual environment

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Run locally

```bash
python app.py
```

Open [http://localhost:5000](http://localhost:5000)

> **Note:** `gunicorn` is for Linux/Render only. Use `python app.py` on Windows for local development.

---

## Deployment to Render

1. Push code to GitHub
2. Go to [render.com](https://render.com) and create new **Web Service**
3. Connect your GitHub repo: `https://github.com/lgrice8/flashcard-app`
4. Render will auto-detect Python
5. Set environment variable: `SECRET_KEY` = [any long random string]
6. Deploy

**Build Command** (Render fills this automatically from `requirements.txt`):
```
pip install -r requirements.txt
```

**Start Command** (Render reads this from `Procfile`):
```
gunicorn app:app
```

Render auto-deploys on every push to `main`.

> **Free tier note:** Render's free tier spins down after 15 minutes of inactivity.
> The first request after sleep takes ~30 seconds to wake up. Uploaded session
> decks are lost on restart — users revert to the default deck automatically.

---

## Changing Default Deck

1. Edit `config.json` locally
2. Change `"default_deck"` to your CSV filename
3. Commit: `git add config.json`
4. Push: `git commit -m "Updated default deck" && git push`
5. Render auto-deploys

### CSV Format

```
Word,Definition
Compel,Force or oblige
Inexorable,Unstoppable or relentless
```

- Row 1 is the header (column names don't matter)
- Column 1 → front of card
- Column 2 → back of card

---

## Upload Passcode

The passcode for the **Load New Deck** button is **`4321`**.

To change it, edit `PASSCODE` in `app.py` and redeploy.

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `SECRET_KEY` | Yes (production) | Flask session signing key — set a long random string in Render |
| `PORT` | No | Set automatically by Render; defaults to `5000` locally |

Generate a secure `SECRET_KEY`:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

---

## Project Structure

```
flashcard-app/
├── app.py                           # Flask application
├── config.json                      # Default deck configuration
├── titanic_vocabulary_synonyms.csv  # Default flashcard deck
├── requirements.txt                 # Python dependencies
├── Procfile                         # Render start command
├── runtime.txt                      # Python version for Render
├── .gitignore
├── README.md
├── templates/
│   └── index.html                   # Single-page UI
└── static/
    └── style.css                    # Stylesheet
```
