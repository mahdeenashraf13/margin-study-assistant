import json

import pytest

import llm
import pipeline
from app import create_app

NOTES = ("Photosynthesis converts light energy into chemical energy in chloroplasts.\n\n" * 3 +
         "The Calvin cycle fixes carbon dioxide into sugar and does not need light directly.\n\n" * 3)


def card(q="What organelle hosts photosynthesis?", idx=0):
    return {"question": q, "choices": ["Chloroplast", "Nucleus", "Ribosome", "Golgi"], "answer_index": idx, "explanation": "Chloroplasts."}


@pytest.fixture
def client(tmp_path, monkeypatch):
    def fake_ask(system, user, **kw):
        if system == pipeline.VERIFY_SYSTEM:
            n = user.count("marked answer")
            return [{"i": i, "answerable": i == 0, "correct": True, "reason": "not in passage"} for i in range(n)]
        return [card("Q1?"), card("Q2?"), {"question": "broken"}]  # last one fails schema validation
    monkeypatch.setattr(llm, "ask_json", fake_ask)
    return create_app(str(tmp_path / "s.db")).test_client()


def test_chunking_respects_limit_and_overlaps():
    text = "\n\n".join(f"Paragraph {i} " + "word " * 100 for i in range(12))
    chunks = pipeline.chunk_text(text, max_chars=1200, overlap=100)
    assert len(chunks) > 1 and all(len(c) <= 1200 for c in chunks)
    assert chunks[0][-50:] in chunks[1]  # overlap carried forward


def test_chunking_splits_giant_paragraph():
    assert all(len(c) <= 500 for c in pipeline.chunk_text("x" * 2000, max_chars=500, overlap=0))


def test_parse_json_strips_fences():
    assert llm.parse_json('```json\n[{"a": 1}]\n```') == [{"a": 1}]


def test_validate_card_rejects_bad_schema():
    assert pipeline.validate_card(card())
    assert pipeline.validate_card({**card(), "answer_index": 7}) is None
    assert pipeline.validate_card({**card(), "choices": ["a", "a", "b", "c"]}) is None
    assert pipeline.validate_card({"question": "x"}) is None


def test_deck_flow_with_verification(client):
    assert client.post("/api/decks", json={"text": "too short"}).status_code == 400
    deck_id = client.post("/api/decks", json={"title": "Bio", "text": NOTES}).get_json()["id"]
    cards = client.get(f"/api/decks/{deck_id}").get_json()["cards"]
    assert cards and all(len(c["choices"]) == 4 for c in cards)
    assert cards[0]["verified"] is True and cards[1]["verified"] is False  # fake grader fails the 2nd card
    assert cards[1]["reason"] == "not in passage"


def test_edit_regenerate_delete(client):
    deck_id = client.post("/api/decks", json={"text": NOTES}).get_json()["id"]
    cid = client.get(f"/api/decks/{deck_id}").get_json()["cards"][0]["id"]
    assert client.patch(f"/api/cards/{cid}", json={**card("Edited?"), "answer_index": 9}).status_code == 400
    assert client.patch(f"/api/cards/{cid}", json=card("Edited?")).status_code == 200
    edited = client.get(f"/api/decks/{deck_id}").get_json()["cards"][0]
    assert edited["question"] == "Edited?" and edited["verified"] is None
    regen = client.post(f"/api/cards/{cid}/regenerate").get_json()
    assert regen["question"] == "Q1?" and regen["verified"] is True
    assert client.delete(f"/api/cards/{cid}").status_code == 204
    assert client.post("/api/cards/9999/regenerate").status_code == 404
