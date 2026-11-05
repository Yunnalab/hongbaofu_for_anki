#!/usr/bin/env python3
"""红宝书二轮牌组生成器：round2/data/entries_r2.json -> apkg。

用法：
    python3 round2/tools/gen_round2_deck.py            # 真数据 -> 红宝书二轮_全量.apkg
    python3 round2/tools/gen_round2_deck.py --mock     # mock -> 红宝书二轮_mock.apkg

牌组层次：红宝书二轮::必考词::Unit NN / 红宝书二轮::基础词::Unit NN
单个 note type「红宝书二轮」，3 个模板：词义卡 / 变形派生卡 / 例句填空卡。
没有合格例句的 note 不生成例句填空卡（模板 qfmt 整体包在 {{#Cloze}} 里，
genanki 会据此跳过该卡）。
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path

import genanki

HERE = Path(__file__).resolve().parent
ROUND2 = HERE.parent
BASE = ROUND2.parent

sys.path.insert(0, str(HERE))
import inflect  # noqa: E402

MODEL_ID = 1785340001
DECK_ID_BASE = 1785341000

SECTIONS = [("必考词", 26), ("基础词", 30)]

CSS = """
.card {
  font-family: "Noto Sans CJK SC", "Source Han Sans SC", "PingFang SC",
               "Microsoft YaHei", "Noto Sans", sans-serif;
  font-size: 17px;
  line-height: 1.7;
  color: #222;
  background: #fdfdfb;
  text-align: left;
  padding: 18px 20px;
}
.front { text-align: center; }
.word { font-size: 40px; font-weight: 700; letter-spacing: .5px; color: #1b1b1b; }
.word-small { font-size: 26px; font-weight: 700; margin-top: 10px; }
.phonetic { color: #6a6a6a; font-size: 17px; font-family: "DejaVu Sans", "Noto Sans", sans-serif; }
.pos { color: #7a5c2e; font-size: 15px; margin-top: 4px; }
.tts { margin-top: 6px; }
.prompt { color: #8a8a8a; font-size: 14px; margin-top: 14px; letter-spacing: 1px; }
.back { text-align: left; }
hr#answer { border: 0; border-top: 1px solid #dcdcd6; margin: 16px 0; }
section { margin: 0 0 14px; }
section h3 {
  font-size: 13px; font-weight: 600; color: #8a6d3b;
  letter-spacing: 1.5px; margin: 0 0 4px;
}
.meaning .sense { margin-bottom: 4px; }
.meaning .spos { color: #7a5c2e; font-weight: 600; margin-right: 4px; }
.form-row { display: flex; gap: 10px; }
.form-row .k { flex: 0 0 6.5em; color: #777; font-size: 14px; }
.form-row .v { flex: 1; }
.irr { color: #b4552d; font-weight: 700; }
.note, .meta { color: #8a8a8a; font-size: 13px; }
.meta { margin-top: 14px; border-top: 1px dashed #e2e2dc; padding-top: 8px; }
.deriv-item, .phrase, .ex { margin-bottom: 6px; }
.dw { font-weight: 600; }
.dp, .dpos { color: #8a6d3b; font-size: 14px; }
.dm { color: #333; }
.synant .k { color: #777; font-size: 14px; margin-right: 6px; }
.synant .row { margin-bottom: 4px; }
.phrase .en { color: #333; }
.phrase .zh { color: #777; }
.ex-en { color: #222; }
.ex-zh { color: #777; font-size: 15px; }
.cloze { font-size: 22px; line-height: 1.9; text-align: left; }
.blank { color: #b4552d; font-weight: 700; letter-spacing: 1px; }
.cloze-zh { color: #777; font-size: 15px; margin-top: 10px; text-align: left; }
.cloze-tip { color: #aaa; font-size: 13px; margin-top: 12px; text-align: left; }

.nightMode .card, .card.nightMode {
  color: #e6e4df; background: #1f2023;
}
.nightMode .word, .card.nightMode .word { color: #f2f0eb; }
.nightMode .phonetic, .nightMode .pos, .nightMode .meta,
.nightMode .note, .nightMode .cloze-zh, .nightMode .ex-zh,
.nightMode .phrase .zh { color: #a9a7a1; }.nightMode section h3, .nightMode .dp, .nightMode .dpos,
.nightMode .cloze-zh { color: #c9a86a; }
.nightMode hr#answer, .nightMode .meta { border-color: #3a3b3f; }
.nightMode .dm, .nightMode .ex-en { color: #ddd; }
.nightMode .blank, .nightMode .irr { color: #e08b5f; }
"""


MODEL = genanki.Model(
    MODEL_ID,
    "红宝书二轮",
    fields=[
        {"name": "Word"},
        {"name": "Phonetic"},
        {"name": "Pos"},
        {"name": "Meaning"},
        {"name": "Forms"},
        {"name": "Derivatives"},
        {"name": "SynAnt"},
        {"name": "Phrases"},
        {"name": "Examples"},
        {"name": "Mnemonic"},
        {"name": "Meta"},
        {"name": "Cloze"},
        {"name": "ClozeZh"},
    ],
    templates=[
        {
            "name": "①词义卡",
            "qfmt": """
<div class="front">
  <div class="word">{{Word}}</div>
  {{#Phonetic}}<div class="phonetic">/{{Phonetic}}/</div>{{/Phonetic}}
  {{#Pos}}<div class="pos">{{Pos}}</div>{{/Pos}}
  <div class="tts">{{tts en_US:Word}}</div>
</div>
""",
            "afmt": """
{{FrontSide}}
<hr id="answer">
<div class="back">
  {{#Meaning}}<section><h3>释义</h3><div class="meaning">{{Meaning}}</div></section>{{/Meaning}}
  {{#Forms}}<section><h3>变形</h3><div>{{Forms}}</div></section>{{/Forms}}
  {{#Derivatives}}<section><h3>派生</h3><div>{{Derivatives}}</div></section>{{/Derivatives}}
  {{#SynAnt}}<section><h3>同义 / 反义</h3><div class="synant">{{SynAnt}}</div></section>{{/SynAnt}}
  {{#Phrases}}<section><h3>词组</h3><div>{{Phrases}}</div></section>{{/Phrases}}
  {{#Examples}}<section><h3>例句</h3><div>{{Examples}}</div></section>{{/Examples}}
  {{#Mnemonic}}<section><h3>助记</h3><div>{{Mnemonic}}</div></section>{{/Mnemonic}}
  {{#Meta}}<div class="meta">{{Meta}}</div>{{/Meta}}
</div>
""",
        },
        {
            "name": "②变形派生卡",
            "qfmt": """
<div class="front">
  <div class="word">{{Word}}</div>
  {{#Phonetic}}<div class="phonetic">/{{Phonetic}}/</div>{{/Phonetic}}
  <div class="tts">{{tts en_US:Word}}</div>
  <div class="prompt">变形 · 派生 · 搭配</div>
</div>
""",
            "afmt": """
{{FrontSide}}
<hr id="answer">
<div class="back">
  {{#Forms}}<section><h3>变形</h3><div>{{Forms}}</div></section>{{/Forms}}
  {{#Derivatives}}<section><h3>派生</h3><div>{{Derivatives}}</div></section>{{/Derivatives}}
  {{#SynAnt}}<section><h3>同义 / 反义</h3><div class="synant">{{SynAnt}}</div></section>{{/SynAnt}}
  {{#Phrases}}<section><h3>词组</h3><div>{{Phrases}}</div></section>{{/Phrases}}
  {{#Meta}}<div class="meta">{{Meta}}</div>{{/Meta}}
</div>
""",
        },
        {
            "name": "③例句填空卡",
            "qfmt": """
{{#Cloze}}
<div class="cloze">{{Cloze}}</div>
{{#ClozeZh}}<div class="cloze-zh">{{ClozeZh}}</div>{{/ClozeZh}}
<div class="cloze-tip">补全句中缺掉的词</div>
{{/Cloze}}
""",
            "afmt": """
{{FrontSide}}
<hr id="answer">
<div class="back">
  <div class="word-small">{{Word}}</div>
  <div class="tts">{{tts en_US:Word}}</div>
  {{#Meaning}}<section><h3>释义</h3><div class="meaning">{{Meaning}}</div></section>{{/Meaning}}
  {{#Forms}}<section><h3>变形</h3><div>{{Forms}}</div></section>{{/Forms}}
  {{#Derivatives}}<section><h3>派生</h3><div>{{Derivatives}}</div></section>{{/Derivatives}}
  {{#SynAnt}}<section><h3>同义 / 反义</h3><div class="synant">{{SynAnt}}</div></section>{{/SynAnt}}
  {{#Phrases}}<section><h3>词组</h3><div>{{Phrases}}</div></section>{{/Phrases}}
  {{#Examples}}<section><h3>例句</h3><div>{{Examples}}</div></section>{{/Examples}}
  {{#Mnemonic}}<section><h3>助记</h3><div>{{Mnemonic}}</div></section>{{/Mnemonic}}
  {{#Meta}}<div class="meta">{{Meta}}</div>{{/Meta}}
</div>
""",
        },
    ],
    css=CSS,
)


# ---------------------------------------------------------------------------
# 文本处理
# ---------------------------------------------------------------------------
def esc_keep(value) -> str:
    """转义成 HTML，但保留首尾空白（例句挖空后空格有意义）。"""
    if value is None:
        return ""
    text = str(value).replace("\u00a0", " ").replace("&nbsp;", " ")
    return html.escape(text, quote=False)


def esc(value) -> str:
    """转义成可放进字段的 HTML；顺手把书里的 &nbsp; 归一成空格。"""
    return esc_keep(value).strip()


def expand_tilde(text: str, word: str, pos: str | None) -> str:
    """书上用 ~ 指代词条本身；按后面跟的后缀还原成正确词形。"""
    if not text:
        return ""
    w = word.lower()
    f = inflect.forms(w, pos)
    pos_list = inflect.parse_pos(pos)

    def repl(m: re.Match) -> str:
        tail = m.group(1)
        if not tail:
            return w
        low = tail.lower()
        if low in {"s", "es"}:
            if "v" in pos_list and "3sg" in f:
                return f["3sg"]
            if "n" in pos_list and "plural" in f:
                return f["plural"]
            return w + tail
        if low in {"ed", "d"} and "past" in f:
            return f["past"]
        if low == "ing" and "ing" in f:
            return f["ing"]
        return w + tail

    return re.sub(r"~([A-Za-z]*)", repl, text)


def render_meaning(entry: dict, r1: dict | None) -> str:
    """优先用一轮简明释义；没有就退回二轮 senses。"""
    if r1 and (r1.get("meaning") or "").strip():
        # 一轮释义原样保留（其中可能带书上的 ~，按约定只在 Examples 里展开）
        return esc(r1["meaning"])
    out = []
    for sense in entry.get("senses") or []:
        items = [esc(it) for it in (sense.get("items") or []) if esc(it)]
        if not items:
            continue
        pos = esc(sense.get("pos"))
        head = f'<span class="spos">{pos}</span>' if pos else ""
        out.append(f'<div class="sense">{head}{"<br>".join(items)}</div>')
    return "".join(out)


def resolve_pos(entry: dict, r1: dict | None, meaning: str) -> str:
    """合并所有来源的词性（红宝书一个词常兼 v./n.），变形按并集算。"""
    found: list[str] = []

    def add(value) -> None:
        for token in inflect.parse_pos(value):
            if token not in found:
                found.append(token)

    add(entry.get("pos"))
    add((r1 or {}).get("pos"))
    for sense in entry.get("senses") or []:
        add(sense.get("pos"))
    if not found:
        add(inflect.guess_pos(entry.get("word", ""), meaning))
    else:
        # 释义正文里的词性标签（如 `v. 使紧张…… n. 拉力`）补进来
        for tag in re.findall(r"(?:^|[\s；;，,])(adj|adv|vt|vi|v|n)\.", meaning or ""):
            add(tag)
    order = {p: i for i, p in enumerate(("v", "n", "adj", "adv"))}
    found.sort(key=lambda p: order.get(p, 9))
    return "/".join(f"{p}." for p in found)


FORM_LABELS = {
    "past": "过去式", "pp": "过去分词", "3sg": "第三人称单数", "ing": "现在分词",
    "plural": "复数", "comparative": "比较级", "superlative": "最高级",
}


def render_forms(word: str, pos: str) -> str:
    all_forms = inflect.forms(word, pos)
    if not all_forms:
        return ""
    flags = inflect.is_irregular(word, pos)
    rows = []
    any_irr = False
    for key in ("past", "pp", "3sg", "ing", "plural", "comparative", "superlative"):
        if key not in all_forms:
            continue
        irr = flags.get(key, False)
        any_irr = any_irr or irr
        mark = ' <span class="irr">✱</span>' if irr else ""
        rows.append(
            f'<div class="form-row"><span class="k">{FORM_LABELS[key]}</span>'
            f'<span class="v">{esc(all_forms[key])}{mark}</span></div>'
        )
    if any_irr:
        note = inflect.IRREGULAR_VERB_NOTES.get(word.lower())
        extra = esc(note) if note else ""
        rows.append(
            '<div class="note">✱ 不规则变化'
            + (f"；{extra}" if extra else "")
            + "</div>"
        )
    return "".join(rows)


def render_derivatives(entry: dict) -> str:
    out = []
    for d in entry.get("deriv") or []:
        word = esc(d.get("word"))
        if not word:
            continue
        phon = esc(d.get("phonetic"))
        pos = esc(d.get("pos"))
        mean = esc(d.get("meaning"))
        bits = [f'<span class="dw">{word}</span>']
        if phon:
            bits.append(f'<span class="dp">/{phon}/</span>')
        if pos:
            bits.append(f'<span class="dpos">{pos}</span>')
        if mean:
            bits.append(f'<span class="dm">{mean}</span>')
        out.append(f'<div class="deriv-item">{" ".join(bits)}</div>')
    return "".join(out)


def render_syn_ant(entry: dict) -> str:
    rows = []
    syn = [esc(s) for s in (entry.get("syn") or []) if esc(s)]
    if syn:
        rows.append(f'<div class="row"><span class="k">同义</span>{", ".join(syn)}</div>')
    ants = []
    for a in entry.get("ant") or []:
        word = esc(a.get("word"))
        if not word:
            continue
        pos = esc(a.get("pos"))
        mean = esc(a.get("meaning"))
        tail = " ".join(x for x in (f'<span class="dpos">{pos}</span>' if pos else "",
                                    mean) if x)
        ants.append(f"{word} {tail}".strip())
    if ants:
        rows.append(f'<div class="row"><span class="k">反义</span>{"；".join(ants)}</div>')
    return "".join(rows)


def render_phrases(entry: dict) -> str:
    out = []
    for p in entry.get("phrases") or []:
        en = esc(p.get("en"))
        zh = esc(p.get("zh"))
        if not en and not zh:
            continue
        zh_html = ""
        if zh:
            zh_html = (f'<span class="zh"> — {zh}</span>' if en
                       else f'<span class="zh">{zh}</span>')
        out.append(f'<div class="phrase"><span class="en">{en}</span>'
                   + zh_html + '</div>')
    return "".join(out)


def en_punct(text) -> str:
    """OCR 把中文句读混进英文例句（`it will break。`），统一成半角。"""
    if not text:
        return text
    for zh, en_ch in {"。": ".", "，": ",", "；": ";", "？": "?", "！": "!", "：": ":"}.items():
        text = text.replace(zh, en_ch)
    return text


def render_examples(entry: dict, word: str, pos: str) -> str:
    out = []
    for ex in entry.get("examples") or []:
        en = expand_tilde(esc_plain(en_punct(ex.get("en"))), word, pos)
        zh = esc(ex.get("zh"))
        if not en:
            continue
        out.append(f'<div class="ex"><div class="ex-en">{esc(en)}</div>'
                   f'<div class="ex-zh">{zh}</div></div>')
    return "".join(out)


def esc_plain(value) -> str:
    """先不做 HTML 转义，供 expand_tilde 使用。"""
    if value is None:
        return ""
    return str(value).replace("\u00a0", " ").replace("&nbsp;", " ").strip()


def candidate_surfaces(word: str, pos: str) -> list[str]:
    """例句里可能出现的词形（原型 + 各种变形）。"""
    surfaces = {word.lower()}
    for p in ("v", "n", "adj"):
        for value in inflect.forms(word, p).values():
            for v in inflect.split_forms(value):
                surfaces.add(v.lower())
    surfaces = {s for s in surfaces if len(s) >= 2}
    return sorted(surfaces, key=len, reverse=True)


def make_cloze(entry: dict, word: str, pos: str) -> tuple[str, str]:
    """挑第一条「含目标词形 + 有中文」的例句挖空；不合格返回 ("", "")。"""
    surfaces = candidate_surfaces(word, pos)
    if not surfaces:
        return "", ""
    pattern = re.compile(
        r"(?<![A-Za-z])(" + "|".join(re.escape(s) for s in surfaces) + r")(?![A-Za-z])",
        re.IGNORECASE,
    )
    for ex in entry.get("examples") or []:
        en = expand_tilde(esc_plain(en_punct(ex.get("en"))), word, pos)
        zh = esc_plain(ex.get("zh"))
        if not en or not zh:
            continue
        m = pattern.search(en)
        if not m:
            continue
        before = esc_keep(en[:m.start()])
        after = esc_keep(en[m.end():])
        cloze = f'{before}<span class="blank">____</span>{after}'
        return cloze, "提示：" + esc(zh)
    return "", ""


def render_meta(entry: dict, r1: dict | None) -> str:
    section = entry.get("section") or ""
    unit = entry.get("unit")
    page = (r1 or {}).get("page")
    if page is None:
        pages = entry.get("pdf_pages") or []
        page = pages[0] if pages else None
    bits = [section]
    if unit is not None:
        bits.append(f"Unit {int(unit):02d}")
    if page is not None:
        bits.append(f"p.{page}")
    return esc(" · ".join(b for b in bits if b))


def build_note(entry: dict, r1_index: dict[str, dict]) -> genanki.Note:
    word = (entry.get("word") or "").strip()
    r1 = r1_index.get(word.lower())
    meaning_plain = (r1 or {}).get("meaning") or ""
    pos = resolve_pos(entry, r1, meaning_plain)
    phonetic = entry.get("phonetic") or (r1 or {}).get("phonetic") or ""

    meaning = render_meaning(entry, r1)
    forms = render_forms(word, pos) if pos else ""
    deriv = render_derivatives(entry)
    syn_ant = render_syn_ant(entry)
    phrases = render_phrases(entry)
    examples = render_examples(entry, word, pos)
    mnemonic = esc(entry.get("mnemonic") or (r1 or {}).get("mnemonic"))
    meta = render_meta(entry, r1)
    cloze, cloze_zh = make_cloze(entry, word, pos)

    fields = [
        esc(word), esc(phonetic), esc(pos), meaning, forms, deriv, syn_ant,
        phrases, examples, mnemonic, meta, cloze, cloze_zh,
    ]
    tags = ["红宝书二轮"]
    if entry.get("section"):
        tags.append(entry["section"])
    if entry.get("unit") is not None:
        tags.append(f"Unit{int(entry['unit']):02d}")
    if cloze:
        tags.append("有例句")
    return genanki.Note(
        model=MODEL,
        fields=fields,
        guid=genanki.guid_for("红宝书二轮", word),
        tags=tags,
    )


def load_entries(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    entries = data.get("entries") if isinstance(data, dict) else data
    if not isinstance(entries, list):
        raise SystemExit(f"{path} 里没有 entries 列表")
    return entries


def load_round1() -> dict[str, dict]:
    path = BASE / "all_entries_v2.json"
    if not path.exists():
        print(f"[warn] 找不到 {path}，释义/音标将只能取自二轮 senses", file=sys.stderr)
        return {}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return {e["word"].lower(): e for e in data if e.get("word")}


def main() -> None:
    ap = argparse.ArgumentParser(description="生成红宝书二轮 apkg")
    ap.add_argument("--mock", action="store_true", help="用 mock_entries.json 自测")
    ap.add_argument("--data", type=Path, help="指定 entries JSON")
    ap.add_argument("--out", type=Path, help="指定输出 apkg")
    args = ap.parse_args()

    data_path = args.data or (ROUND2 / "data" /
                              ("mock_entries.json" if args.mock else "entries_r2.json"))
    if not data_path.exists():
        raise SystemExit(f"数据文件不存在：{data_path}"
                         + ("（真数据还没解析出来？先跑 parse_entries.py）" if not args.mock else ""))
    out_path = args.out or (ROUND2 / ("红宝书二轮_mock.apkg" if args.mock
                                      else "红宝书二轮_全量.apkg"))

    entries = load_entries(data_path)
    r1_index = load_round1()

    decks = []
    deck_id = DECK_ID_BASE
    for section, unit_count in SECTIONS:
        for unit in range(1, unit_count + 1):
            deck_id += 1
            deck = genanki.Deck(deck_id, f"红宝书二轮::{section}::Unit {unit:02d}")
            group = [e for e in entries
                     if e.get("section") == section and int(e.get("unit") or 0) == unit]
            for entry in group:
                if not (entry.get("word") or "").strip():
                    continue
                deck.add_note(build_note(entry, r1_index))
            decks.append(deck)

    placed = sum(len(d.notes) for d in decks)
    skipped = len(entries) - placed
    genanki.Package(decks).write_to_file(str(out_path))
    cloze_notes = sum(1 for d in decks for n in d.notes if n.fields[11])
    print(f"输出: {out_path}")
    print(f"note: {placed}  跳过(无 section/unit): {skipped}  "
          f"子牌组: {len(decks)}  例句填空卡: {cloze_notes}")
    print(f"cards: {placed * 2 + cloze_notes}（每个 note 2 张 + 有例句的加 1 张）")


if __name__ == "__main__":
    main()
