#!/usr/bin/env python3
"""从 all_entries_v2.json 生成红宝书 Anki 牌组"""
import json
import genanki

BASE = "/home/cloudygirl/Anki红宝书"

CSS = """
.card { font-family: "Noto Sans", "Noto Sans CJK SC", Arial, sans-serif; text-align: center; color: #333; background: #fff; }
.word { font-size: 32px; font-weight: bold; padding: 20px; }
.back { font-size: 18px; text-align: left; padding: 10px; }
"""

MODEL_TTS = genanki.Model(
    1785260160491,
    "红宝书(带发音)",
    fields=[{"name": "Front"}, {"name": "Back"}],
    templates=[{
        "name": "Card 1",
        "qfmt": '<div class="word">{{Front}}{{tts en_US:Front}}</div>',
        "afmt": '<div class="word">{{Front}}</div><hr id="answer"><div class="back">{{Back}}</div>',
    }],
    css=CSS,
)

MODEL_PLAIN = genanki.Model(
    1976273901,
    "红宝书(简化)",
    fields=[{"name": "Front"}, {"name": "Back"}],
    templates=[{
        "name": "Card 1",
        "qfmt": '<div class="word">{{Front}}</div>',
        "afmt": '<div class="word">{{Front}}</div><hr id="answer"><div class="back">{{Back}}</div>',
    }],
    css=CSS,
)


def back_field(e):
    s = f"[{e['phonetic']}] <br>{e['meaning']}"
    if e.get("mnemonic", "").strip():
        s += f" <br><br>【助记】 {e['mnemonic']}"
    return s


def make_note(e, model):
    return genanki.Note(
        model=model,
        fields=[e["word"], back_field(e)],
        guid=genanki.guid_for(e["word"]),
        tags=["红宝书", e["section"], f"Unit{e['unit']:02d}"],
    )


def main():
    with open(f"{BASE}/all_entries_v2.json") as f:
        entries = json.load(f)

    # 分层子牌组（带发音）: 红宝书考研词汇::必考词::Unit 01
    sections = sorted({e["section"] for e in entries})
    all_decks = []
    deck_id = 1785270000
    for sec in sections:
        for u in sorted({e["unit"] for e in entries if e["section"] == sec}):
            deck_id += 1
            name = f"红宝书考研词汇::{sec}::Unit {u:02d}"
            deck = genanki.Deck(deck_id, name)
            group = [e for e in entries if e["section"] == sec and e["unit"] == u]
            for e in group:
                deck.add_note(make_note(e, MODEL_TTS))
            all_decks.append(deck)

    genanki.Package(all_decks).write_to_file(f"{BASE}/红宝书考研词汇_带发音_全套.apkg")
    print(f"生成: 红宝书考研词汇_带发音_全套.apkg ({len(entries)} 词, {len(all_decks)} 子牌组)")

    # 简化版
    all_plain = []
    deck_id = 1785250000
    for sec in sections:
        for u in sorted({e["unit"] for e in entries if e["section"] == sec}):
            deck_id += 1
            name = f"红宝书考研词汇(简化)::{sec}::Unit {u:02d}"
            deck = genanki.Deck(deck_id, name)
            group = [e for e in entries if e["section"] == sec and e["unit"] == u]
            for e in group:
                deck.add_note(make_note(e, MODEL_PLAIN))
            all_plain.append(deck)

    genanki.Package(all_plain).write_to_file(f"{BASE}/红宝书考研词汇_全套.apkg")
    print(f"生成: 红宝书考研词汇_全套.apkg ({len(entries)} 词, {len(all_plain)} 子牌组)")

    # 按单元独立 apkg（简化版）
    deck_id = 1785271000
    for sec in sections:
        for u in sorted({e["unit"] for e in entries if e["section"] == sec}):
            deck_id += 1
            deck = genanki.Deck(deck_id, f"{sec}_Unit{u:02d}")
            group = [e for e in entries if e["section"] == sec and e["unit"] == u]
            for e in group:
                deck.add_note(make_note(e, MODEL_PLAIN))
            genanki.Package(deck).write_to_file(f"{BASE}/{sec}_Unit{u:02d}.apkg")
    print("单元独立牌组生成完毕")


if __name__ == "__main__":
    main()
