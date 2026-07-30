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

    # 全套：带发音 + 简化
    for model, suffix in ((MODEL_TTS, "带发音_全套"), (MODEL_PLAIN, "全套")):
        deck = genanki.Deck(1785260001, "红宝书考研词汇")
        for e in entries:
            deck.add_note(make_note(e, model))
        out = f"{BASE}/红宝书考研词汇_{suffix}.apkg"
        genanki.Package(deck).write_to_file(out)
        print(f"生成: {out} ({len(entries)} 词)")

    # 按单元拆分
    sections = sorted({e["section"] for e in entries})
    deck_id = 1785270000
    for sec in sections:
        units = sorted({e["unit"] for e in entries if e["section"] == sec})
        for u in units:
            deck_id += 1
            deck = genanki.Deck(deck_id, f"{sec}_Unit{u:02d}")
            group = [e for e in entries if e["section"] == sec and e["unit"] == u]
            for e in group:
                deck.add_note(make_note(e, MODEL_PLAIN))
            out = f"{BASE}/{sec}_Unit{u:02d}.apkg"
            genanki.Package(deck).write_to_file(out)
    print("单元牌组生成完毕")


if __name__ == "__main__":
    main()
