"""Study Assistant API: upload notes -> chunk -> generate quiz cards -> verify -> edit/regenerate."""
import json
import os
import sqlite3

from flask import Flask, g, jsonify, request
from pypdf import PdfReader

import pipeline

MAX_CHARS = 60_000   # cap input size to bound API cost
MAX_CHUNKS = 10

SCHEMA = """
CREATE TABLE IF NOT EXISTS decks (id INTEGER PRIMARY KEY, title TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS chunks (id INTEGER PRIMARY KEY, deck_id INTEGER NOT NULL, text TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS cards (
  id INTEGER PRIMARY KEY, deck_id INTEGER NOT NULL, chunk_id INTEGER NOT NULL,
  question TEXT NOT NULL, choices TEXT NOT NULL, answer_index INTEGER NOT NULL,
  explanation TEXT, verified INTEGER, reason TEXT);
"""


def extract_text(file_storage):
    if file_storage.filename.lower().endswith(".pdf"):
        return "\n\n".join(p.extract_text() or "" for p in PdfReader(file_storage).pages)
    return file_storage.read().decode("utf-8", errors="ignore")


def create_app(db_path=None):
    app = Flask(__name__, static_folder="static", static_url_path="")
    app.config["DB_PATH"] = db_path or os.environ.get("DB_PATH", "study.db")
    app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024

    def db():
        if "db" not in g:
            g.db = sqlite3.connect(app.config["DB_PATH"])
            g.db.row_factory = sqlite3.Row
        return g.db

    @app.teardown_appcontext
    def close_db(_):
        if (conn := g.pop("db", None)) is not None:
            conn.close()

    with sqlite3.connect(app.config["DB_PATH"]) as c:
        c.executescript(SCHEMA)

    def card_json(r):
        return {"id": r["id"], "question": r["question"], "choices": json.loads(r["choices"]),
                "answer_index": r["answer_index"], "explanation": r["explanation"],
                "verified": None if r["verified"] is None else bool(r["verified"]), "reason": r["reason"]}

    def insert_cards(deck_id, chunk_id, chunk, cards):
        for c, (ok, why) in zip(cards, pipeline.verify_cards(chunk, cards)):
            db().execute("INSERT INTO cards(deck_id,chunk_id,question,choices,answer_index,explanation,verified,reason) "
                         "VALUES (?,?,?,?,?,?,?,?)", (deck_id, chunk_id, c["question"], json.dumps(c["choices"]),
                                                      c["answer_index"], c["explanation"], None if ok is None else int(ok), why))

    @app.post("/api/decks")
    def create_deck():
        if request.files.get("file"):
            text, title = extract_text(request.files["file"]), request.files["file"].filename
        else:
            d = request.get_json(silent=True) or {}
            text, title = str(d.get("text", "")), str(d.get("title") or "Untitled deck")
        text = text.strip()
        if len(text) < 200:
            return jsonify(error="Add at least a few paragraphs of notes (200+ characters)."), 400
        chunks = pipeline.chunk_text(text[:MAX_CHARS])[:MAX_CHUNKS]
        deck_id = db().execute("INSERT INTO decks(title) VALUES (?)", (title[:80],)).lastrowid
        for chunk in chunks:
            chunk_id = db().execute("INSERT INTO chunks(deck_id,text) VALUES (?,?)", (deck_id, chunk)).lastrowid
            try:
                insert_cards(deck_id, chunk_id, chunk, pipeline.generate_cards(chunk))
            except Exception as e:  # one bad chunk shouldn't sink the whole deck
                app.logger.warning("chunk %s failed: %s", chunk_id, e)
        db().commit()
        return jsonify(id=deck_id), 201

    @app.get("/api/decks")
    def list_decks():
        rows = db().execute("SELECT d.*, (SELECT COUNT(*) FROM cards WHERE deck_id=d.id) n FROM decks d ORDER BY id DESC")
        return jsonify([{"id": r["id"], "title": r["title"], "cards": r["n"]} for r in rows])

    @app.get("/api/decks/<int:deck_id>")
    def get_deck(deck_id):
        d = db().execute("SELECT * FROM decks WHERE id=?", (deck_id,)).fetchone()
        if not d:
            return jsonify(error="not found"), 404
        cards = db().execute("SELECT * FROM cards WHERE deck_id=? ORDER BY id", (deck_id,)).fetchall()
        return jsonify(id=d["id"], title=d["title"], cards=[card_json(c) for c in cards])

    @app.patch("/api/cards/<int:cid>")
    def edit_card(cid):
        c = pipeline.validate_card(request.get_json(silent=True) or {})
        if not c:
            return jsonify(error="Need a question, 4 different non-empty choices and a valid answer."), 400
        cur = db().execute("UPDATE cards SET question=?,choices=?,answer_index=?,explanation=?,verified=NULL,reason='edited by you' WHERE id=?",
                           (c["question"], json.dumps(c["choices"]), c["answer_index"], c["explanation"], cid))
        db().commit()
        return (jsonify(ok=True) if cur.rowcount else (jsonify(error="not found"), 404))

    @app.post("/api/cards/<int:cid>/regenerate")
    def regenerate(cid):
        old = db().execute("SELECT c.*, k.text FROM cards c JOIN chunks k ON k.id=c.chunk_id WHERE c.id=?", (cid,)).fetchone()
        if not old:
            return jsonify(error="not found"), 404
        try:
            new = pipeline.generate_cards(old["text"], n=1, avoid=old["question"])
        except ValueError:
            new = []
        if not new:
            return jsonify(error="Could not generate a replacement. Try again."), 502
        (ok, why), = pipeline.verify_cards(old["text"], new[:1])
        n = new[0]
        db().execute("UPDATE cards SET question=?,choices=?,answer_index=?,explanation=?,verified=?,reason=? WHERE id=?",
                     (n["question"], json.dumps(n["choices"]), n["answer_index"], n["explanation"],
                      None if ok is None else int(ok), why, cid))
        db().commit()
        return jsonify(card_json(db().execute("SELECT * FROM cards WHERE id=?", (cid,)).fetchone()))

    @app.delete("/api/cards/<int:cid>")
    def delete_card(cid):
        db().execute("DELETE FROM cards WHERE id=?", (cid,))
        db().commit()
        return "", 204

    @app.get("/")
    def index():
        return app.send_static_file("index.html")

    return app


app = create_app() if os.environ.get("CREATE_APP_ON_IMPORT", "1") == "1" else None

if __name__ == "__main__":
    app.run(debug=True)
