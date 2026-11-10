#!/usr/bin/env python3
"""红宝书二轮牌组生成器：round2/data/entries_r2.json -> apkg。

用法：
    python3 round2/tools/gen_round2_deck.py            # 真数据 -> 红宝书二轮_全量.apkg
    python3 round2/tools/gen_round2_deck.py --mock     # mock -> 红宝书二轮_mock.apkg
    python3 round2/tools/gen_round2_deck.py --all      # 1~7 全部模板（含 ⑦ 派生反推）
    python3 round2/tools/gen_round2_deck.py -t chinese,forms,phrase,cloze --with-deriv

牌组层次：红宝书二轮::必考词::Unit NN / 红宝书二轮::基础词::Unit NN
单个 note type「红宝书二轮」，7 个模板（①词义卡 / ②变形派生卡 / ③例句填空卡 /
④中译英 / ⑤变形默写 / ⑥短语填空 / ⑦派生反推）。

一轮已经考过「单词 → 中文」，二轮默认只出反向题（④⑤⑥，③）：
    -t chinese,forms,phrase,cloze   # 默认
    --all                           # 全部 7 个（① ② 与一轮重复，默认不出）

「有料才出」：每张卡的 qfmt 整体包在 {{#某字段}} 里，字段为空时 genanki/Anki
自动跳过该卡（即模板的 req 机制），所以不用在 Python 里另外判断。
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

/* 二轮多向提问（④~⑦）的题面样式 */
.zhask { font-size: 21px; line-height: 1.95; color: #1b1b1b; margin-top: 2px; }
.zhask .zsense { margin-bottom: 8px; }
.zhask .zsense .spos { color: #7a5c2e; font-weight: 600; margin-right: 6px; }
.formask {
  font-size: 19px; color: #2b2b2b; margin-top: 14px; letter-spacing: .5px;
}
.phrase-ask { font-size: 22px; line-height: 1.9; margin-bottom: 10px; }
.phrase-ask .en { color: #1b1b1b; }
.phrase-ask .zh { color: #777; font-size: 16px; }
.deriv-ask { font-size: 22px; line-height: 1.9; margin-bottom: 10px; }
.deriv-ask .dpos { font-size: 16px; margin: 0 .5em; }
.deriv-ask .dm { color: #333; }

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

/* 二轮多向提问：夜间模式 */
.nightMode .zhask, .nightMode .formask, .nightMode .phrase-ask .en,
.nightMode .deriv-ask .dw { color: #e6e4df; }
.nightMode .zhask .zsense .spos, .nightMode .deriv-ask .dpos { color: #c9a86a; }
.nightMode .phrase-ask .zh, .nightMode .deriv-ask .dm { color: #a9a7a1; }
"""

# 字段顺序是契约：新字段一律**追加到末尾**，旧字段顺序不动（否则已导入的 note 会错位）。
FIELD_NAMES = [
    "Word", "Phonetic", "Pos", "Meaning", "Forms", "Derivatives", "SynAnt",
    "Phrases", "Examples", "Mnemonic", "Meta", "Cloze", "ClozeZh",
    # ↓ 二轮「多向提问」新增的题面字段
    "ZhAsk", "FormAsk", "PhraseAsk", "DerivAsk",
]
I_WORD, I_CLOZE = 0, FIELD_NAMES.index("Cloze")
I_ZH_ASK = FIELD_NAMES.index("ZhAsk")
I_FORM_ASK = FIELD_NAMES.index("FormAsk")
I_PHRASE_ASK = FIELD_NAMES.index("PhraseAsk")
I_DERIV_ASK = FIELD_NAMES.index("DerivAsk")

# 模板档位：键 -> 显示名。ord 由上表的先后决定；①②③ 保持在最前面，
# 免得已经导入过牌组的人因为 ord 变动而丢掉旧卡。
TEMPLATE_ORDER = ("card", "extra", "cloze", "chinese", "forms", "phrase", "deriv")
TEMPLATE_LABELS = {
    "card": "①词义卡",
    "extra": "②变形派生卡",
    "cloze": "③例句填空卡",
    "chinese": "④中译英",
    "forms": "⑤变形默写",
    "phrase": "⑥短语填空",
    "deriv": "⑦派生反推",
}
DEFAULT_TEMPLATES = "chinese,forms,phrase,cloze"

# 背面常用区块，多个模板复用（空字段不出现空标题）
SEC_MEANING = '  {{#Meaning}}<section><h3>释义</h3><div class="meaning">{{Meaning}}</div></section>{{/Meaning}}\n'
SEC_FORMS = '  {{#Forms}}<section><h3>变形</h3><div>{{Forms}}</div></section>{{/Forms}}\n'
SEC_DERIV = '  {{#Derivatives}}<section><h3>派生</h3><div>{{Derivatives}}</div></section>{{/Derivatives}}\n'
SEC_SYNANT = '  {{#SynAnt}}<section><h3>同义 / 反义</h3><div class="synant">{{SynAnt}}</div></section>{{/SynAnt}}\n'
SEC_PHRASES = '  {{#Phrases}}<section><h3>词组</h3><div>{{Phrases}}</div></section>{{/Phrases}}\n'
SEC_EXAMPLES = '  {{#Examples}}<section><h3>例句</h3><div>{{Examples}}</div></section>{{/Examples}}\n'
SEC_MNEMONIC = '  {{#Mnemonic}}<section><h3>助记</h3><div>{{Mnemonic}}</div></section>{{/Mnemonic}}\n'
SEC_META = '  {{#Meta}}<div class="meta">{{Meta}}</div>{{/Meta}}\n'

HEAD_WORD_SMALL = """  <div class="word-small">{{Word}}</div>
  <div class="tts">{{tts en_US:Word}}</div>
"""
FRONT_WORD = """  <div class="word">{{Word}}</div>
  {{#Phonetic}}<div class="phonetic">/{{Phonetic}}/</div>{{/Phonetic}}
  <div class="tts">{{tts en_US:Word}}</div>
"""


def _back(*blocks: str) -> str:
    return ('{{FrontSide}}\n<hr id="answer">\n<div class="back">\n'
            + "".join(blocks) + "</div>\n")


def _template_specs() -> dict[str, dict]:
    """全部模板定义（键与 TEMPLATE_ORDER 对应）。"""
    specs: dict[str, dict] = {}

    specs["card"] = {
        "name": TEMPLATE_LABELS["card"],
        "qfmt": """
<div class="front">
""" + FRONT_WORD + """  {{#Pos}}<div class="pos">{{Pos}}</div>{{/Pos}}
</div>
""",
        "afmt": _back(SEC_MEANING, SEC_FORMS, SEC_DERIV, SEC_SYNANT,
                      SEC_PHRASES, SEC_EXAMPLES, SEC_MNEMONIC, SEC_META),
    }

    specs["extra"] = {
        "name": TEMPLATE_LABELS["extra"],
        "qfmt": """
<div class="front">
  <div class="word">{{Word}}</div>
  {{#Phonetic}}<div class="phonetic">/{{Phonetic}}/</div>{{/Phonetic}}
  <div class="tts">{{tts en_US:Word}}</div>
  <div class="prompt">变形 · 派生 · 搭配</div>
</div>
""",
        "afmt": _back(SEC_FORMS, SEC_DERIV, SEC_SYNANT, SEC_PHRASES, SEC_META),
    }

    specs["cloze"] = {
        "name": TEMPLATE_LABELS["cloze"],
        "qfmt": """
{{#Cloze}}
<div class="cloze">{{Cloze}}</div>
{{#ClozeZh}}<div class="cloze-zh">{{ClozeZh}}</div>{{/ClozeZh}}
<div class="cloze-tip">补全句中缺掉的词</div>
{{/Cloze}}
""",
        "afmt": _back(HEAD_WORD_SMALL, SEC_MEANING, SEC_FORMS, SEC_DERIV,
                      SEC_SYNANT, SEC_PHRASES, SEC_EXAMPLES, SEC_MNEMONIC, SEC_META),
    }

    # ④ 中译英：只给中文释义（不含任何词形），反推英文单词
    specs["chinese"] = {
        "name": TEMPLATE_LABELS["chinese"],
        "qfmt": """
{{#ZhAsk}}
<div class="front">
  {{#Pos}}<div class="pos">{{Pos}}</div>{{/Pos}}
  <div class="zhask">{{ZhAsk}}</div>
  <div class="prompt">↑ 想出对应的英文单词</div>
</div>
{{/ZhAsk}}
""",
        "afmt": _back(
            """  <div class="word">{{Word}}</div>
  {{#Phonetic}}<div class="phonetic">/{{Phonetic}}/</div>{{/Phonetic}}
  <div class="tts">{{tts en_US:Word}}</div>
""",
            SEC_MEANING, SEC_FORMS, SEC_DERIV, SEC_SYNANT,
            SEC_PHRASES, SEC_EXAMPLES, SEC_MNEMONIC, SEC_META),
    }

    # ⑤ 变形默写：只说要考哪几种变形，不给答案、不暗示是否规则
    specs["forms"] = {
        "name": TEMPLATE_LABELS["forms"],
        "qfmt": """
{{#FormAsk}}
<div class="front">
  <div class="word">{{Word}}</div>
  {{#Phonetic}}<div class="phonetic">/{{Phonetic}}/</div>{{/Phonetic}}
  {{#Pos}}<div class="pos">{{Pos}}</div>{{/Pos}}
  <div class="formask">{{FormAsk}}</div>
</div>
{{/FormAsk}}
""",
        "afmt": _back(SEC_FORMS, SEC_EXAMPLES, SEC_PHRASES, SEC_META),
    }

    # ⑥ 短语填空：固定搭配里挖掉本词，只留中文
    specs["phrase"] = {
        "name": TEMPLATE_LABELS["phrase"],
        "qfmt": """
{{#PhraseAsk}}
<div class="front">
  {{PhraseAsk}}
  <div class="prompt">↑ 补出这个固定搭配里缺的词</div>
</div>
{{/PhraseAsk}}
""",
        "afmt": _back(HEAD_WORD_SMALL, SEC_PHRASES, SEC_EXAMPLES, SEC_META),
    }

    # ⑦ 派生反推：给派生词 + 词性 + 中文，反推母词
    specs["deriv"] = {
        "name": TEMPLATE_LABELS["deriv"],
        "qfmt": """
{{#DerivAsk}}
<div class="front">
  {{DerivAsk}}
  <div class="prompt">↑ 它的母词是？</div>
</div>
{{/DerivAsk}}
""",
        "afmt": _back(HEAD_WORD_SMALL, SEC_DERIV, SEC_MEANING, SEC_META),
    }

    return specs


def build_model(enabled_keys) -> genanki.Model:
    """按选中的模板档位建模型；字段表恒定，只变模板集合。"""
    specs = _template_specs()
    wanted = [k for k in TEMPLATE_ORDER if k in set(enabled_keys)]
    if not wanted:
        raise SystemExit("至少得选一个模板")
    return genanki.Model(
        MODEL_ID,
        "红宝书二轮",
        fields=[{"name": name} for name in FIELD_NAMES],
        templates=[specs[k] for k in wanted],
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


CJK_RE = re.compile(r"[\u4e00-\u9fff]")
ASCII_RE = re.compile(r"[A-Za-z]")
BLANK_MARK = "\x00"          # 内部占位符，渲染时换成 ＿＿
BLANK_TEXT = "＿＿"


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
FORM_ORDER = ("past", "pp", "3sg", "ing", "plural", "comparative", "superlative")


def render_forms(word: str, pos: str) -> str:
    all_forms = inflect.forms(word, pos)
    if not all_forms:
        return ""
    flags = inflect.is_irregular(word, pos)
    rows = []
    any_irr = False
    for key in FORM_ORDER:
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


def surface_re(surfaces: list[str]) -> re.Pattern:
    """按词边界匹配任意词形（大小写不敏感）。"""
    alts = "|".join(re.escape(s) for s in surfaces)
    return re.compile(r"(?<![A-Za-z])(" + alts + r")(?![A-Za-z])", re.IGNORECASE)


def make_cloze(entry: dict, word: str, pos: str) -> tuple[str, str]:
    """挑第一条「含目标词形 + 有中文」的例句挖空；不合格返回 ("", "")。"""
    surfaces = candidate_surfaces(word, pos)
    if not surfaces:
        return "", ""
    pattern = surface_re(surfaces)
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


# ---------------------------------------------------------------------------
# 多向提问：ZhAsk / FormAsk / PhraseAsk / DerivAsk
# ---------------------------------------------------------------------------
MAX_ZH_ITEMS = 5
MAX_PHRASE_ASKS = 2
MAX_DERIV_ASKS = 3
TRAILING_JUNK = " \t，,、；;：:．.。·／/｜|—－-"


def _pos_label(raw) -> str:
    """`vi.` / `vt.` 之类统一成 `v.`，只保留 v./n./adj./adv.。"""
    return "/".join(f"{t}." for t in inflect.parse_pos(raw))


def _strip_dangling_paren(text: str) -> str:
    for op, cl in (("（", "）"), ("(", ")")):
        if text.count(op) > text.count(cl):
            text = text[: text.rfind(op)]
    return text


def _zh_punct(text: str) -> str:
    """中文旁边的半角逗号/分号换成全角（`(一块)布,织物` -> `(一块)布，织物`）。"""
    text = re.sub(r"(?<=[\u4e00-\u9fff]),|,(?=[\u4e00-\u9fff])", "，", text)
    text = re.sub(r"(?<=[\u4e00-\u9fff]);|;(?=[\u4e00-\u9fff])", "；", text)
    return text


def zh_gloss(raw) -> str:
    """`①使紧张，尽力使用：~ one's eyes 瞪大眼睛看` -> `①使紧张，尽力使用`。

    取序号 + 冒号前的中文部分，丢掉冒号后的英文用法/例句；`~` 一律换成 ＿＿。
    """
    text = str(raw or "").replace("\u00a0", " ").strip()
    if not text:
        return ""
    cut = len(text)
    for mark in ("：", ":", "~", "～"):
        i = text.find(mark)
        if i != -1:
            cut = min(cut, i)
    m = ASCII_RE.search(text[:cut])
    if m:
        cut = m.start()
    text = text[:cut]
    # 括注里带英文字母的（OCR 噪声 `(c/u）`、`（u】`）整段丢掉
    text = re.sub(r"[（(][^（()）]*[A-Za-z][^（()）]*[)）\]]", "", text)
    text = _strip_dangling_paren(text)
    text = re.sub(r"\s+", " ", text).strip()
    return _zh_punct(text.strip(TRAILING_JUNK))


def render_zh_ask(entry: dict, word: str, pos: str) -> str:
    """④ 的题面：按词性分组的中文释义，最多 5 条，保证不含目标词任何词形。"""
    surfaces = candidate_surfaces(word, pos) or [word.lower()]
    pattern = surface_re(surfaces)
    seen: set[str] = set()
    total = 0
    out = []
    for sense in entry.get("senses") or []:
        items = []
        for raw in sense.get("items") or []:
            gloss = zh_gloss(raw)
            if not gloss or not CJK_RE.search(gloss):
                continue
            gloss = gloss.replace("～", BLANK_TEXT).replace("~", BLANK_TEXT)
            if pattern.search(gloss) or gloss in seen:
                continue
            seen.add(gloss)
            items.append(gloss)
        if not items:
            continue
        items = items[: max(0, MAX_ZH_ITEMS - total)]
        total += len(items)
        label = _pos_label(sense.get("pos"))
        head = f'<span class="spos">{esc(label)}</span>' if label else ""
        out.append('<div class="zsense">' + head
                   + "<br>".join(esc(i) for i in items) + "</div>")
        if total >= MAX_ZH_ITEMS:
            break
    return "".join(out)


def render_form_ask(word: str, pos: str) -> str:
    """⑤ 的题面：只列要考哪几种变形，不给答案、不暗示规则与否。"""
    all_forms = inflect.forms(word, pos)
    keys = [k for k in FORM_ORDER if k in all_forms]
    if len(keys) < 2:            # 只有一种变形（如光杆复数）不值得单独出卡
        return ""
    return "写出变形：" + " · ".join(FORM_LABELS[k] for k in keys)


def zh_hint(raw) -> str:
    """⑥ 题面里的中文提示：OCR 常把整句例句并进 zh，切到第一个英文段为止。"""
    text = esc_plain(raw).replace("～", BLANK_TEXT).replace("~", BLANK_TEXT)
    m = ASCII_RE.search(text)
    if m:
        text = text[:m.start()]
    text = _strip_dangling_paren(re.sub(r"\s+", " ", text)).strip(TRAILING_JUNK)
    if not text or not CJK_RE.search(text):
        return ""
    return _zh_punct(text)


def render_phrase_ask(entry: dict, word: str, pos: str) -> str:
    """⑥ 的题面：固定短语里把本词挖成 ＿＿，后面附中文。"""
    surfaces = candidate_surfaces(word, pos)
    if not surfaces:
        return ""
    pattern = surface_re(surfaces)
    out = []
    for p in entry.get("phrases") or []:
        en = expand_tilde(esc_plain(p.get("en")), word, pos)
        if not en or not pattern.search(en):
            continue
        blanked = pattern.sub(BLANK_MARK, en)
        low = blanked.lower()
        if any(s in low for s in surfaces):
            # 挖掉之后还剩词形（`go ape/apeshit` 这类），换下一条
            continue
        zh = zh_hint(p.get("zh"))
        if zh and pattern.search(zh):    # 中文那栏还带着本词，换下一条
            continue
        en_html = f'<span class="blank">{BLANK_TEXT}</span>'.join(
            esc_keep(part) for part in blanked.split(BLANK_MARK))
        zh_html = f'<span class="zh">　{esc(zh)}</span>' if zh else ""
        out.append(f'<div class="phrase-ask"><span class="en">{en_html}</span>'
                   + zh_html + "</div>")
        if len(out) >= MAX_PHRASE_ASKS:
            break
    return "".join(out)


DERIV_WORD_RE = re.compile(r"[a-z]{4,20}")
DERIV_SUFFIXES = (
    "tion", "sion", "ment", "ness", "ity", "ance", "ence", "ive", "ous", "ful",
    "less", "able", "ible", "ism", "ist", "hood", "ship", "ing", "ed", "al",
    "ly", "er", "or", "ic", "ate", "ify", "ize", "ise", "cy", "th", "y",
)


def _common_prefix(a: str, b: str) -> int:
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


def _plausible_deriv(base: str, deriv_word: str) -> bool:
    """派生词得像一个真英文词：OCR 把音标错当派生词的（`kanfai`、`taa'ri`）要挡掉。"""
    if not DERIV_WORD_RE.fullmatch(deriv_word):
        return False
    if "a" not in deriv_word and "e" not in deriv_word and "i" not in deriv_word \
            and "o" not in deriv_word and "u" not in deriv_word and "y" not in deriv_word:
        return False
    if _common_prefix(base, deriv_word) >= 3:
        return True
    return deriv_word.endswith(DERIV_SUFFIXES)


def deriv_hint(raw) -> str:
    """派生词的中文释义：OCR 会把下一条派生（`② vastly`）粘在后面，从第一个汉字取起。"""
    text = re.split(r"[①-⑩]", esc_plain(raw))[0]
    m = CJK_RE.search(text)
    if not m:
        return ""
    text = text[m.start():]
    m = ASCII_RE.search(text)
    if m:
        text = text[: m.start()]
    text = _strip_dangling_paren(re.sub(r"\s+", " ", text)).strip(TRAILING_JUNK)
    if not CJK_RE.search(text):
        return ""
    text = _zh_punct(text)
    return text if len(text) <= 60 else text[:60].rstrip() + "…"


def render_deriv_ask(entry: dict, word: str, pos: str) -> str:
    """⑦ 的题面：派生词 + 词性 + 中文，让人反推母词。"""
    base = word.lower()
    out = []
    for d in entry.get("deriv") or []:
        dw = esc_plain(d.get("word"))
        low = dw.lower()
        if not dw or low == base:      # 派生词 = 母词本身，问了等于白问
            continue
        if not _plausible_deriv(base, low):
            continue
        dpos = _pos_label(d.get("pos"))
        dm = deriv_hint(d.get("meaning"))
        bits = [f'<span class="dw">{esc(dw)}</span>']
        if dpos:
            bits.append(f'<span class="dpos">{dpos}</span>')
        if dm:
            bits.append(f'<span class="dm">{dm}</span>')
        out.append('<div class="deriv-ask">' + "".join(bits) + "</div>")
        if len(out) >= MAX_DERIV_ASKS:
            break
    return "".join(out)


def build_note(entry: dict, r1_index: dict[str, dict], model: genanki.Model) -> genanki.Note:
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
    # 四个题面字段永远填满：模板选没选只影响出卡，不影响 note 本身，
    # 这样换 --templates 重新导入时 note 内容一致，不会产生重复卡。
    zh_ask = render_zh_ask(entry, word, pos)
    form_ask = render_form_ask(word, pos) if pos else ""
    phrase_ask = render_phrase_ask(entry, word, pos)
    deriv_ask = render_deriv_ask(entry, word, pos)

    fields = [
        esc(word), esc(phonetic), esc(pos), meaning, forms, deriv, syn_ant,
        phrases, examples, mnemonic, meta, cloze, cloze_zh,
        zh_ask, form_ask, phrase_ask, deriv_ask,
    ]
    tags = ["红宝书二轮"]
    if entry.get("section"):
        tags.append(entry["section"])
    if entry.get("unit") is not None:
        tags.append(f"Unit{int(entry['unit']):02d}")
    if cloze:
        tags.append("有例句")
    return genanki.Note(
        model=model,
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


def parse_templates(spec: str) -> list[str]:
    keys = [k.strip().lower() for k in spec.replace("，", ",").split(",") if k.strip()]
    if not keys:
        raise SystemExit("--templates 不能为空")
    bad = [k for k in keys if k not in TEMPLATE_LABELS]
    if bad:
        raise SystemExit(f"未知模板 {', '.join(bad)}；可选："
                         + ", ".join(TEMPLATE_ORDER))
    return list(dict.fromkeys(keys))


def main() -> None:
    ap = argparse.ArgumentParser(description="生成红宝书二轮 apkg")
    ap.add_argument("--mock", action="store_true", help="用 mock_entries.json 自测")
    ap.add_argument("--data", type=Path, help="指定 entries JSON")
    ap.add_argument("--out", type=Path, help="指定输出 apkg")
    ap.add_argument("-t", "--templates", default=DEFAULT_TEMPLATES,
                    help=f"选模板，逗号分隔（可选：{', '.join(TEMPLATE_ORDER)}），"
                         f"默认 {DEFAULT_TEMPLATES}")
    ap.add_argument("--all", action="store_true", help="出全部 7 个模板（含 ①② 与 ⑦）")
    ap.add_argument("--with-deriv", action="store_true", help="额外加上 ⑦ 派生反推")
    args = ap.parse_args()

    enabled = list(TEMPLATE_ORDER) if args.all else parse_templates(args.templates)
    if args.with_deriv and "deriv" not in enabled:
        enabled.append("deriv")
    enabled = [k for k in TEMPLATE_ORDER if k in set(enabled)]  # 按 ord 排序

    data_path = args.data or (ROUND2 / "data" /
                              ("mock_entries.json" if args.mock else "entries_r2.json"))
    if not data_path.exists():
        raise SystemExit(f"数据文件不存在：{data_path}"
                         + ("（真数据还没解析出来？先跑 parse_entries.py）" if not args.mock else ""))
    out_path = args.out or (ROUND2 / ("红宝书二轮_mock.apkg" if args.mock
                                      else "红宝书二轮_全量.apkg"))

    entries = load_entries(data_path)
    r1_index = load_round1()
    model = build_model(enabled)

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
                deck.add_note(build_note(entry, r1_index, model))
            decks.append(deck)

    notes = [n for d in decks for n in d.notes]
    placed = len(notes)
    skipped = len(entries) - placed
    genanki.Package(decks).write_to_file(str(out_path))

    # 「有料才出」：题面字段为空的 note 不会出这张卡
    gates = {"chinese": I_ZH_ASK, "forms": I_FORM_ASK,
             "phrase": I_PHRASE_ASK, "deriv": I_DERIV_ASK,
             "cloze": I_CLOZE}
    print(f"输出: {out_path}")
    print(f"note: {placed}  跳过(无 section/unit): {skipped}  子牌组: {len(decks)}")
    print(f"模板: {', '.join(TEMPLATE_LABELS[k] for k in enabled)}")
    total = 0
    for key in enabled:
        if key in gates:
            count = sum(1 for n in notes if n.fields[gates[key]].strip())
        else:
            count = placed
        total += count
        print(f"  {TEMPLATE_LABELS[key]:<8} {count}")
    print(f"cards 合计: {total}")


if __name__ == "__main__":
    main()
