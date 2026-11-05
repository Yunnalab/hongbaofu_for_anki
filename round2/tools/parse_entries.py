#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""二轮词条解析器：round2/ocr/page_*.txt → round2/data/entries_r2.json。

设计要点（对应 round2/SCHEMA.md）：

1. **切词靠「一轮词表锚点」**。一单元预期词序列 vs OCR 里长得像 headword 的行做
   顺序对齐，而不是靠排版猜。OCR 把 strain 认成 strairn、把 divert 认成
   diveré 时仍能恢复；条目 `word` 直接取一轮词表里的原形，保证能 join 回一轮数据。
2. **标记解析容忍 OCR 退化**。`【】` 常被认成 `[]()`，标记名常被认残
   （助记→Hid、同义→司义、派生→JRE）；先做名字模糊匹配，名字彻底丢了就用
   后面内容的形状（圈码+中文 / 只剩词性缩写 / 纯英文词）猜槽位，猜过的打
   `marker_name_garbled`。
3. **不编造中文释义**。解析不到就留空；派生/同义/反义的英文词必须能在该词条
   OCR 原文里回溯到，否则打 `hallucinated_*`。
4. **置信度是扣分制**（见 score_confidence），只有「词形精确 + 有音标 + 至少一条
   含中文的释义 + 无 flag」才给 1.0。

用法：
    python3 round2/tools/parse_entries.py                  # 全量跑
    python3 round2/tools/parse_entries.py --limit-pages 30 # 只解析页码 ≤30 的页（调试）
    python3 round2/tools/parse_entries.py --self-test      # 内置样本文本单测
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------- 常量与正则

CJK = r"\u4e00-\u9fff"
CJK_RE = re.compile(f"[{CJK}]")

# 词性缩写白名单（含 OCR 常见误认：adj.→ag./a., n.→m., v.→w.）
POS_ALIAS = {
    "a": "adj.", "ad": "adv.", "ag": "adj.", "adj": "adj.", "adv": "adv.",
    "n": "n.", "m": "n.", "v": "v.", "w": "v.", "vt": "vt.", "vi": "vi.",
    "aux": "aux.", "prep": "prep.", "conj": "conj.", "pron": "pron.",
    "num": "num.", "art": "art.", "int": "int.", "abbr": "abbr.", "pl": "pl.",
}
POS_TOKEN_RE = re.compile(
    r"\b(" + "|".join(sorted(POS_ALIAS, key=len, reverse=True)) + r")\.",
    re.IGNORECASE,
)

MARKER_NAMES = [
    "真题例句", "同义词", "反义词", "派生词", "词汇辨析", "习惯用语", "典型考题",
    "试题分析", "助记", "词性", "词义", "同义", "反义", "派生", "词组", "搭配",
    "辨析", "用法", "联想", "记忆", "扩展", "例句", "短语", "考点",
]
MARKER_ALT = "|".join(MARKER_NAMES)
# 行首裸标记（丢了括号的情形）
MARKER_BARE_RE = re.compile(rf"(?m)^\s*(【|\[)?\s*({MARKER_ALT})\s*[】\]］:：]")

# 标记名 → 槽位
MARKER_SLOT = {
    "助记": "mnemonic", "记忆": "mnemonic", "联想": "mnemonic",
    "词性": "pos", "词义": "def", "例句": "examples", "真题例句": "examples",
    "同义": "syn", "同义词": "syn", "反义": "ant", "反义词": "ant",
    "派生": "deriv", "派生词": "deriv",
    "词组": "phrase", "搭配": "phrase", "短语": "phrase", "习惯用语": "phrase",
    "辨析": "notes", "词汇辨析": "notes", "用法": "notes", "扩展": "notes",
    "考点": "notes", "典型考题": "notes", "试题分析": "notes",
}
UNMODELED = ("notes",)

CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳❶❷❸❹❺❻❼❽❾❿➀➁➂➃➄"
SENT = "\x00"

# 音标：书上是 [ ... ]，OCR 常把 ] 认成 ) 或干脆丢掉
PHON_RE = re.compile(r"[\[［]\s*([^\]］\n]{1,45}?)\s*[\]］]")
PHON_OPEN_RE = re.compile(r"[\[［]\s*([^\]］\n]{1,45})")
PHON_BAD_CHARS = re.compile(r"[=\[\]{}<>]")
IPA_CHARS = set("abcdefghijklmnopqrstuvwxyzæɑɒɔəɜɪʊʌʃʒθðŋˈˌː'’()-,;:. ")

# 页眉/页脚/装饰行
NOISE_RE = re.compile(r"^\s*(?:[·•.…\-—_=~*\s]*\d{1,4}[·•.…\-—_=~*\s]*|红宝书?|红宝•?\s*书)\s*$")

HEADWORD_MAX_LEN = 60
ALIGN_WINDOW = 45


# ---------------------------------------------------------------- 文本工具

def norm_spaces(s: str) -> str:
    return re.sub(r"[ \t\u00a0\u3000]+", " ", s).strip()


def letters_only(s: str) -> str:
    return re.sub(r"[^a-z]", "", s.lower())


def edit_distance_le1(a: str, b: str) -> bool:
    if a == b:
        return True
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    if la == lb:
        return sum(1 for x, y in zip(a, b) if x != y) <= 1
    if la > lb:
        a, b, la, lb = b, a, lb, la
    i = 0
    while i < la and a[i] == b[i]:
        i += 1
    return a[i:] == b[i + 1:]


def similar(a: str, b: str) -> int:
    """0=不像 1=模糊像 2=完全相同（比较前归一成纯字母小写）。"""
    na, nb = letters_only(a), letters_only(b)
    if not na or not nb:
        return 0
    if na == nb:
        return 2
    if len(na) >= 4 and len(nb) >= 4 and edit_distance_le1(na, nb):
        return 1
    if len(na) >= 5 and len(nb) >= 5 and na[0] == nb[0] and na[-1] == nb[-1] \
            and abs(len(na) - len(nb)) <= 2:
        return 1
    return 0


def is_noise(line: str) -> bool:
    s = line.strip()
    if not s:
        return True
    if NOISE_RE.match(s):
        return True
    if re.fullmatch(r"[|\-—_=·.。,，、;；:：'\"“”‘’()（）\[\]【】]+", s):
        return True
    return False


def looks_ipa(s: str) -> bool:
    s = s.strip().strip("|").strip()
    if not (1 <= len(s) <= 45):
        return False
    if CJK_RE.search(s) or re.search(r"\d", s):
        return False
    if PHON_BAD_CHARS.search(s):
        return False
    if not re.search(r"[a-zA-Zæɑɒɔəɜɪʊʌʃʒθðŋ]", s):
        return False
    if len(re.findall(r"[A-Za-z]+", s)) > 3:   # 一句英文而不是音标
        return False
    good = sum(1 for ch in s.lower() if ch in IPA_CHARS)
    return good / len(s) >= 0.75


def extract_phonetic(line: str):
    m = PHON_RE.search(line)
    cand = m.group(1) if m else None
    if cand is None:
        m2 = PHON_OPEN_RE.search(line)
        if m2:
            cand = m2.group(1)
    if cand is None:
        return None
    cand = cand.strip().strip("|").strip()
    return cand if looks_ipa(cand) else None


# ---------------------------------------------------------------- 标记识别

CONFUSE = str.maketrans({"司": "同", "伺": "同", "饲": "同", "叉": "义", "艾": "义"})
BRACKET_RE = re.compile(r"[【\[［(（]\s*([^\]】）)］\n]{1,12}?)\s*[】\]］)）]")

# 行首 OCR 认残的圈码（①→@/O/0/Q/G/CD/GD/iO…），后面必须紧跟中文才算 item 开头
ITEM_LEAD_RE = re.compile(
    rf"^\s*[0-9@OoQqGgCcDdJjLl]{{1,2}}\s*[).\]】:：]?\s*(?=[{CJK}])"
)


def cjk_core(s: str) -> str:
    return "".join(ch for ch in s.translate(CONFUSE) if re.match(f"[{CJK}]", ch))


def lev(a: str, b: str) -> int:
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def match_marker_name(content: str):
    """括号里那串字符是不是某个标记名（容忍 OCR 认残）。"""
    core = cjk_core(content)
    if not core:
        return None
    lead = re.match(rf"[{CJK}]+", content.translate(CONFUSE))
    if lead and len(lead.group(0)) <= 4:
        core = lead.group(0)
    best, best_d = None, 99
    for name in MARKER_NAMES:
        ncore = cjk_core(name)
        if not ncore:
            continue
        if ncore == core:
            return name
        if len(core) >= 2 and ncore.endswith(core):
            return name
        if len(core) >= 2 and core.endswith(ncore):
            return name
        d = lev(ncore, core)
        if d <= 1 and d < best_d:
            best, best_d = name, d
    return best


def _at_line_start(text: str, i: int) -> bool:
    j = i - 1
    while j >= 0 and text[j] in " \t":
        j -= 1
    return j < 0 or text[j] == "\n"


def looks_pos_only(s: str) -> bool:
    """整段是否只剩词性缩写（容忍「❶ v.」/「@ [kon'test] v.」）。"""
    t = s
    for ch in CIRCLED:
        t = t.replace(ch, " ")
    t = PHON_RE.sub(" ", t)
    t = re.sub(r"[\[\]【】()（）.,;:/、]", " ", t)
    toks = [x for x in t.split() if x]
    if not toks or len(toks) > 4:
        return False
    return all(re.fullmatch(r"(?:[a-z]{1,4}\.?)+", x) for x in toks)


def guess_slot(rest: str):
    """标记名彻底认不出来时，靠后面内容的形状猜槽位。"""
    r = rest.lstrip()
    if not r:
        return None
    line0 = r.split("\n")[0]
    if looks_pos_only(line0):
        return "pos"
    if re.match(rf"^\s*[\[［]\s*[^\]］]*[\]］]\s*(?:[a-z]{{1,5}}\.)", line0):
        return "pos"
    if re.match(rf"^\s*[0-9@OoQqGgCcDdJjLl]{{1,2}}\s*[).\]】:：]?\s*[{CJK}]", line0):
        return "def"
    if CJK_RE.match(line0.strip()[:1] or "x"):
        return "def"
    if re.fullmatch(r"[A-Za-z][A-Za-z ,.;:/\-']{2,80}", line0.strip()) and not CJK_RE.search(line0):
        return "syn"
    # 英文词 + 音标 + 词性 + 中文 → 派生（【派生】/【反义】长的都这样）
    if re.match(rf"^[A-Za-z][A-Za-z'’\-]*\s*[\[［][^\]］]*[\]］]\s*(?:[a-z]{{1,5}}\.)", line0):
        return "deriv"
    if CJK_RE.search(line0) and re.match(r"^[A-Za-z~\-]", line0.strip()):
        return "phrase"
    return None


def scan_markers(text: str):
    """返回 [(start, end, slot, name_or_None, guessed), ...]，按出现顺序。"""
    hits = []
    for m in BRACKET_RE.finditer(text):
        content = m.group(1)
        core = cjk_core(content)
        name = match_marker_name(content)
        if name is not None:
            hits.append((m.start(), m.end(), MARKER_SLOT.get(name, "notes"), name, False))
            continue
        latin = content.strip()
        # 标记名整个被认成拉丁乱码（JRE/ME/WK/JO），只能看全大写 + 行首
        if not core:
            if not (_at_line_start(text, m.start()) and 1 <= len(latin) <= 4
                    and latin.isupper()):
                continue
        elif not (_at_line_start(text, m.start()) and 1 <= len(core) <= 3):
            continue
        slot = guess_slot(text[m.end(): m.end() + 60])
        if slot is None:
            continue
        hits.append((m.start(), m.end(), slot, None, True))
    for m in MARKER_BARE_RE.finditer(text):
        if any(h[0] <= m.start() < h[1] for h in hits):
            continue
        name = m.group(2)
        hits.append((m.start(), m.end(), MARKER_SLOT.get(name, "notes"), name, False))
    hits.sort(key=lambda h: h[0])
    out = []
    for h in hits:
        if out and h[0] < out[-1][1]:
            continue
        out.append(h)
    return out


def split_marker_blocks(text: str):
    """切块 → [(slot, block_text, name, guessed), ...]。"""
    hits = scan_markers(text)
    if not hits:
        return [(None, text, None, False)]
    blocks = []
    head = text[: hits[0][0]]
    if head.strip():
        blocks.append((None, head, None, False))
    for k, (start, end, slot, name, guessed) in enumerate(hits):
        stop = hits[k + 1][0] if k + 1 < len(hits) else len(text)
        blocks.append((slot, text[end:stop], name, guessed))
    return blocks


# ---------------------------------------------------------------- 各标记内容解析

def parse_pos_list(s: str) -> list:
    out = []
    for m in POS_TOKEN_RE.finditer(s):
        tok = m.group(1).lower()
        part = POS_ALIAS.get(tok)
        if part and part not in out:
            out.append(part)
    return out


def split_items(text: str) -> list:
    """【词义】块 → item 列表（保留书上「中文释义：英文用法/例句 中文翻译」写法）。"""
    t = text
    for ch in CIRCLED:
        t = t.replace(ch, SENT)
    items, buf = [], ""
    for raw in t.splitlines():
        if SENT in raw:
            parts = raw.split(SENT)
            head = parts[0].strip()
            if head:
                buf = f"{buf} {head}".strip() if buf else head
            if buf:
                items.append(buf)
            items.extend(p.strip() for p in parts[1:-1] if p.strip())
            buf = parts[-1].strip()
            continue
        ln = raw.strip()
        if not ln:
            continue
        if ITEM_LEAD_RE.match(ln):
            if buf:
                items.append(buf)
            buf = ITEM_LEAD_RE.sub("", ln, count=1)
            continue
        if buf and re.search(r"[。！？!?…]\s*$", buf) and CJK_RE.match(ln):
            items.append(buf)
            buf = ln
            continue
        buf = f"{buf} {ln}".strip() if buf else ln
    if buf:
        items.append(buf)
    return [norm_spaces(x) for x in items if x.strip()]


def split_phrase_chunks(text: str) -> list:
    t = text
    for ch in CIRCLED:
        t = t.replace(ch, SENT)
    chunks = []
    for raw in t.split(SENT):
        for ln in raw.splitlines():
            ln = ITEM_LEAD_RE.sub("", norm_spaces(ln), count=1)
            if ln:
                chunks.append(ln)
    return chunks


def first_cjk_outside_parens(s: str):
    depth = 0
    for i, ch in enumerate(s):
        if ch in "(（[［":
            depth += 1
        elif ch in ")）]］":
            depth = max(0, depth - 1)
        elif depth == 0 and CJK_RE.match(ch):
            return i
    return -1


def parse_phrases(text: str) -> list:
    out = []
    for chunk in split_phrase_chunks(text):
        idx = first_cjk_outside_parens(chunk)
        if idx < 0:
            en, zh = chunk, None
        else:
            en, zh = chunk[:idx].strip(" :：,，"), chunk[idx:].strip()
        if not en or not re.search(r"[A-Za-z]", en):
            continue
        en = re.sub(r"^[A-Z@0-9]\s+", "", en).strip()      # 圈码认残留下的单字符
        if not en:
            continue
        wc = len(en.split())
        if wc > 8:
            continue
        if zh is None and (wc > 4 or en[:1].isupper()):
            continue
        out.append({"en": en, "zh": zh or None})
    return out


DERIV_RE = re.compile(
    rf"(?P<w>[A-Za-z][A-Za-z'’\-]{{1,24}})"
    rf"(?:\s*[\[［]\s*(?P<ph>[^\]］]{{0,60}}?)\s*[\]］])?"
    rf"\s*(?P<pos>(?:[a-z]{{1,5}}\.){{1,2}})?"
    rf"\s*(?P<zh>[{CJK}].*)?"
)
ANT_RE = re.compile(rf"^{DERIV_RE.pattern}$")


def parse_deriv(text: str) -> list:
    """【派生】strained ['streɪnd] adj. 紧张的;勉强的，不自然的"""
    out = []
    for chunk in split_phrase_chunks(text):
        for m in DERIV_RE.finditer(chunk):
            if not m.group("zh") and not m.group("ph") and not m.group("pos"):
                continue  # 只是正文里的一个英文词
            out.append({
                "word": m.group("w"),
                "phonetic": (m.group("ph") or "").strip() or None,
                "pos": m.group("pos") or None,
                "meaning": (m.group("zh") or "").strip() or None,
            })
    return out


def parse_ant(text: str) -> list:
    """【反义】relaxation n. 松弛,缓和"""
    out = []
    for chunk in split_phrase_chunks(text):
        m = ANT_RE.match(chunk)
        if not m or not (m.group("pos") or m.group("zh")):
            continue        # 光一个英文词的同义块，不是反义
        out.append({
            "word": m.group("w"),
            "phonetic": (m.group("ph") or "").strip() or None,
            "pos": m.group("pos") or None,
            "meaning": (m.group("zh") or "").strip() or None,
        })
    return out


SYN_STOP = {"n", "v", "adj", "adv", "vt", "vi", "a", "ad", "prep", "to", "and",
            "or", "sth", "the", "this", "that", "these", "those", "of", "in", "on"}


def parse_syn(text: str) -> list:
    t = text
    for ch in CIRCLED:
        t = t.replace(ch, " ")
    t = re.sub(rf"[{CJK}][{CJK}，,、;；:：()（）.…]*", " ", t)   # 丢掉中文注释
    out = []
    for tok in re.split(r"[\s/,、;；|]+", t):
        tok = tok.strip(" .:：()（）[]【】'\"“”")
        if not re.fullmatch(r"[A-Za-z][A-Za-z'’\-]{1,24}", tok):
            continue
        if tok.isupper() or len(tok) <= 2:
            continue
        if tok.lower() in SYN_STOP:
            continue
        tok = tok.lower()
        if tok not in out:
            out.append(tok)
    return out


SENT_EN_RE = re.compile(
    rf"(?P<en>[A-Za-z][A-Za-z0-9 ,.;:'’\"“”!?()\-~]{{8,}}?[.?!])"
    rf"\s*(?P<zh>[{CJK}][^;；]*)"
)


def extract_examples(items: list) -> list:
    out = []
    for it in items:
        for m in SENT_EN_RE.finditer(it):
            en = norm_spaces(m.group("en"))
            zh = norm_spaces(m.group("zh"))
            if len(en.split()) < 3 or not CJK_RE.search(zh):
                continue
            if not re.match(r"[A-Z\"“‘'(~]", en):
                continue
            out.append({"en": en, "zh": zh})
    return out


def parse_example_block(text: str) -> list:
    out = []
    for m in SENT_EN_RE.finditer(text):
        en, zh = norm_spaces(m.group("en")), norm_spaces(m.group("zh"))
        if len(en.split()) >= 3:
            out.append({"en": en, "zh": zh})
    if not out:
        t = norm_spaces(text)
        if t:
            out.append({"en": t, "zh": None})
    return out


# ---------------------------------------------------------------- 词条解析

def has_item_marks(text: str) -> bool:
    if any(ch in text for ch in CIRCLED):
        return True
    return any(ITEM_LEAD_RE.match(ln) for ln in text.splitlines())


def parse_entry(segment: list) -> dict:
    """segment: [(page, line), ...]，第一行是 headword 行。"""
    raw = "\n".join(ln for _, ln in segment)
    pages = sorted({p for p, _ in segment})
    lines = [ln for _, ln in segment]
    head = lines[0] if lines else ""

    # headword 行 = 第一行「像 headword」的行（OCR 常把音标/词性拆到下一行）
    head_idx = 0
    for k, ln in enumerate(lines[:4]):
        if candidate_token(ln):
            head_idx = k
            break
    head = lines[head_idx] if lines else ""
    phonetic = extract_phonetic(head)
    head_pos = parse_pos_list(head[PHON_OPEN_RE.search(head).end():] if PHON_OPEN_RE.search(head) else head)
    if not phonetic and head_idx + 1 < len(lines):
        nxt = lines[head_idx + 1].strip()
        if len(nxt) <= 40 and re.match(r"^[\[［][^\]］]{1,30}[\]］]\s*(?:[a-z]{1,5}\.)?$", nxt):
            phonetic = extract_phonetic(nxt)
    if not head_pos:
        for ln in lines[head_idx:head_idx + 2]:
            head_pos = parse_pos_list(ln)
            if head_pos:
                break

    body = "\n".join(lines[head_idx + 1:])
    blocks = split_marker_blocks(body)

    mnemonic = None
    notes, leftovers = [], []
    senses = []
    syn, ant, deriv, phrases, examples = [], [], [], [], []
    guessed_markers = 0
    cur = None
    pending_pos = head_pos

    for slot, text, name, guessed in blocks:
        if guessed:
            guessed_markers += 1
        if slot is None:
            if text.strip():
                leftovers.append(text)
            continue
        if slot == "mnemonic":
            t = norm_spaces(text)
            mnemonic = f"{mnemonic} {t}".strip() if mnemonic else (t or None)
        elif slot == "pos":
            poss = parse_pos_list(text) or pending_pos
            cur = {"pos": "/".join(poss) if poss else None, "items": []}
            senses.append(cur)
            pending_pos = poss
        elif slot == "def":
            items = split_items(text)
            if cur is None:
                cur = {"pos": "/".join(pending_pos) if pending_pos else None, "items": []}
                senses.append(cur)
            cur["items"].extend(items)
            examples.extend(extract_examples(items))
        elif slot == "syn":
            # 有些行其实是【反义】（标记名被认残并进同义块）：词 + 词性 + 中文
            ant_lines = [c for c in split_phrase_chunks(text)
                         if ANT_RE.match(c) and (ANT_RE.match(c).group("pos")
                                                 or ANT_RE.match(c).group("zh"))]
            if ant_lines:
                ant.extend(parse_ant("\n".join(ant_lines)))
                text = "\n".join(c for c in split_phrase_chunks(text) if c not in ant_lines)
            syn.extend(parse_syn(text))
        elif slot == "ant":
            ant.extend(parse_ant(text))
        elif slot == "deriv":
            deriv.extend(parse_deriv(text))
        elif slot == "phrase":
            phrases.extend(parse_phrases(text))
        elif slot == "examples":
            examples.extend(parse_example_block(text))
        elif slot in UNMODELED:
            t = norm_spaces(text)
            if t:
                notes.append(t)
            # 标记名认残的块里也可能藏着释义条目
            if has_item_marks(text):
                items = split_items(text)
                if cur is None:
                    cur = {"pos": "/".join(head_pos) if head_pos else None, "items": []}
                    senses.append(cur)
                cur["items"].extend(items)
                examples.extend(extract_examples(items))

    # headword 行之后、第一个标记之前散落的文本
    for blk in leftovers:
        bt = norm_spaces(blk)
        if not bt:
            continue
        if has_item_marks(blk):
            items = split_items(blk)
            if cur is None:
                cur = {"pos": "/".join(head_pos) if head_pos else None, "items": []}
                senses.append(cur)
            cur["items"].extend(items)
            examples.extend(extract_examples(items))
        else:
            notes.append(bt)

    senses = [s for s in senses if s["items"] or s["pos"]]
    pos_summary = []
    for s in senses:
        for p in (s["pos"] or "").split("/"):
            if p and p not in pos_summary:
                pos_summary.append(p)
    if not pos_summary:
        pos_summary = list(head_pos)

    seen, ex2 = set(), []
    for ex in examples:
        k = (ex["en"], ex["zh"])
        if k not in seen:
            seen.add(k)
            ex2.append(ex)

    return {
        "phonetic": phonetic,
        "pos": "/".join(pos_summary) if pos_summary else None,
        "pdf_pages": pages,
        "mnemonic": mnemonic,
        "senses": senses,
        "syn": syn,
        "ant": ant,
        "deriv": deriv,
        "phrases": phrases,
        "examples": ex2,
        "notes": " ".join(notes) if notes else None,
        "_raw": raw,
        "_guessed_markers": guessed_markers,
    }


# ---------------------------------------------------------------- 输入加载

def load_all_entries(path: Path) -> list:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def load_units(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def load_pages(ocr_dir: Path) -> dict:
    """page_0009.txt → {9: [line, ...]}"""
    pages = {}
    for p in sorted(ocr_dir.glob("page_*.txt")):
        m = re.search(r"(\d+)", p.stem)
        if not m:
            continue
        pages[int(m.group(1))] = p.read_text(encoding="utf-8", errors="replace").splitlines()
    return pages


def infer_page_offset(units: dict, entries: list) -> int:
    """书上页码 → PDF 页码的偏移（正常是 8）。用各单元首页与一轮 page 最小值的中位数估。"""
    diffs = []
    for section in ("必考词", "基础词"):
        for u in units.get(section, []):
            pages = [e["page"] for e in entries
                     if e["section"] == section and e["unit"] == u["unit"] and e.get("page")]
            if pages:
                diffs.append(u["pdf_start"] - min(pages))
    if not diffs:
        return 0
    diffs.sort()
    return diffs[len(diffs) // 2]


def unit_word_lists(entries: list) -> dict:
    """(section, unit) → [word, ...]，保持一轮 JSON 的书上顺序。"""
    out = {}
    for e in entries:
        out.setdefault((e["section"], e["unit"]), []).append(e["word"])
    return out


# ---------------------------------------------------------------- headword 候选

def candidate_token(line: str):
    """若这一行看起来像 headword 行，返回行首英文词，否则 None。"""
    s = line.strip()
    s = re.sub(r"^[^A-Za-z\u4e00-\u9fff]+", "", s).strip()
    if not s or len(s) > HEADWORD_MAX_LEN:
        return None
    # 行内被 OCR 拼上了标记（「remainder [...] n. 【助记】…」）→ 在标记处截断
    mk = scan_markers(s)
    if mk:
        s = s[: mk[0][0]].strip()
    if not s or CJK_RE.search(s) or s[0] in "[【(（{":
        return None
    m = re.match(r"^([A-Za-z][A-Za-z'’\-]{1,24})", s)
    if not m:
        return None
    tok = m.group(1)
    if len(tok) < 3 or not re.search(r"[aeiouy]", tok.lower()):
        return None
    rest = s[m.end():]
    if "~" in rest:                        # 正文里 "the ~ of ..."
        return None
    if len(rest.split()) > 7:
        return None
    return tok


def head_likeness(stream: list, idx: int) -> int:
    """headword 行长什么样：有音标 / 有词性 / 紧跟标记行，加分。"""
    ln = stream[idx][1]
    score = 0
    if PHON_OPEN_RE.search(ln):
        score += 2
    if parse_pos_list(ln):
        score += 1
    nxt = ""
    for k in range(idx + 1, min(idx + 3, len(stream))):
        if stream[k][1].strip():
            nxt = stream[k][1]
            break
    if nxt and scan_markers(nxt):
        score += 2
    body = ln.split(None, 1)[1] if len(ln.split(None, 1)) > 1 else ""
    if re.search(r"[.,;]$", body.strip()) or len(body.split()) >= 4:
        score -= 1
    return score


def align(expected: list, candidates: list, window: int = ALIGN_WINDOW):
    """顺序贪心对齐：每个预期词在窗口内找最像的候选（先看相似度，再看 headword 像不像）。

    返回 [(expected_idx, candidate_idx) 或 (expected_idx, None), ...]，外加未用到的候选。
    """
    letters = [letters_only(w) for w in expected]
    matched, used = [], set()
    pos = 0
    for wi, w in enumerate(expected):
        best_key, best_j = None, None
        for j in range(pos, min(len(candidates), pos + window)):
            if j in used:
                continue
            tok = candidates[j][1]
            s = similar(w, tok)
            if not s:
                continue
            if s == 1:
                # 这是不是后面某个词的原形？是的话别抢，留给它
                nt = letters_only(tok)
                if any(letters[k] == nt for k in range(wi + 1, min(len(expected), wi + 8))):
                    continue
            key = (s, candidates[j][2])
            if best_key is None or key > best_key:
                best_key, best_j = key, j
        if best_j is None:
            matched.append((wi, None))
            continue
        matched.append((wi, best_j))
        used.add(best_j)
        pos = best_j + 1
    unused = [c for j, c in enumerate(candidates) if j not in used]
    return matched, unused


def is_preview_row(line: str, expected_letters: set) -> bool:
    """单词表页的勾选框清单：一行里挤着好几个本单元的词（4 列排版）。"""
    toks = re.findall(r"[A-Za-z][A-Za-z'’\-]{2,24}", line)
    if len(toks) < 2:
        return False
    hits = sum(1 for t in toks if letters_only(t) in expected_letters)
    return hits >= 2 or (hits >= 1 and len(toks) >= 4)


def build_segments(pages: dict, section: str, unit: int, expected: list,
                   first_page: int, last_page: int, stats: dict):
    """返回 ([(word, segment, exact_head, ocr_head), ...], leading_segment)。"""
    expected_letters = {letters_only(w) for w in expected}
    stream = []
    for p in range(first_page, last_page + 1):
        for ln in pages.get(p, []):
            if is_noise(ln):
                continue
            # 单词表页（首页）的清单行不能当 headword，否则一个单元的词会被清单吃光
            if p == first_page and is_preview_row(ln, expected_letters):
                continue
            stream.append((p, ln))

    cands = []  # (stream_idx, token, likeness)
    for idx, (_p, ln) in enumerate(stream):
        tok = candidate_token(ln)
        if tok:
            cands.append((idx, tok, head_likeness(stream, idx)))

    matched, unused = align(expected, cands)
    for w in unused:
        stats["unmatched_candidates"].append(
            {"section": section, "unit": unit, "token": w[1], "page": stream[w[0]][0]})
    for wi, cj in matched:
        if cj is None:
            stats["missing_in_ocr"].append(
                {"section": section, "unit": unit, "word": expected[wi]})

    ok = [(wi, cj) for wi, cj in matched if cj is not None]
    out = []
    for k, (wi, cj) in enumerate(ok):
        start = cands[cj][0]
        stop = cands[ok[k + 1][1]][0] if k + 1 < len(ok) else len(stream)
        # 防止「下一个词没认出来」时整段被前一条吞掉：
        # 遇到「像 headword 且能对上本单元某个词」的行就截断
        for kk in range(start + 1, stop):
            if head_likeness(stream, kk) < 3:
                continue
            tok = candidate_token(stream[kk][1])
            if not tok:
                continue
            if any(similar(tok, w) for w in expected):
                stop = kk
                stats["truncated_segments"] += 1
                break
        seg = stream[start:stop]
        ocr_head = cands[cj][1]
        out.append((expected[wi], seg, ocr_head.lower() == expected[wi].lower(), ocr_head))

    leading = stream[: cands[ok[0][1]][0]] if ok else stream
    return out, leading


def preview_page_words(lines: list) -> list:
    """单词表页（勾选框清单）里的英文词——一页 4 列，不能只看行首。"""
    words = []
    for ln in lines:
        for tok in re.findall(r"[A-Za-z][A-Za-z'’\-]{2,24}", ln):
            if not re.search(r"[aeiouy]", tok.lower()):
                continue
            words.append(tok)
    return words


# ---------------------------------------------------------------- 置信度

def score_confidence(entry: dict, flags: list, exact_head: bool) -> float:
    c = 1.0
    if not entry["senses"]:
        c -= 0.30
    if not exact_head:
        c -= 0.10
    if not entry["phonetic"]:
        c -= 0.05
    if not entry["mnemonic"]:
        c -= 0.05
    first_items = "".join(entry["senses"][0]["items"]) if entry["senses"] else ""
    if entry["senses"] and len(CJK_RE.findall(first_items)) < 3:
        c -= 0.10
    for f in flags:
        if f.startswith("hallucinated"):
            c -= 0.10
        elif f in ("ocr_garbled", "marker_name_garbled"):
            c -= 0.08
        elif f in ("no_phonetic", "no_mnemonic", "empty_sense_items"):
            c -= 0.03
    return round(max(0.05, min(1.0, c)), 3)


def trace(word: str, haystacks: list) -> bool:
    target = letters_only(word)
    if not target:
        return False
    return any(target in h for h in haystacks)


# ---------------------------------------------------------------- 主流程

def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ocr-dir", default="round2/ocr")
    ap.add_argument("--units", default="round2/ocr/units.json")
    ap.add_argument("--all-entries", default="all_entries_v2.json")
    ap.add_argument("--out-dir", default="round2/data")
    ap.add_argument("--limit-pages", type=int, default=0, help="调试：只解析页码 ≤N 的页")
    ap.add_argument("--limit-units", type=int, default=0, help="调试：只解析前 N 个单元")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test()

    root = Path(".")
    ocr_dir = root / args.ocr_dir
    units = load_units(root / args.units)
    all_entries = load_all_entries(root / args.all_entries)
    pages = load_pages(ocr_dir)
    if not pages:
        print(f"[fatal] {ocr_dir} 下没有 page_*.txt", file=sys.stderr)
        return 2
    if args.limit_pages:
        pages = {k: v for k, v in pages.items() if k <= args.limit_pages}

    by_unit = unit_word_lists(all_entries)
    page_offset = infer_page_offset(units, all_entries)
    meta_by_word = {e["word"]: e for e in all_entries}

    stats = {"missing_in_ocr": [], "unmatched_candidates": [], "unit_gaps": [],
             "pages_missing": [], "truncated_segments": 0, "available_units": []}
    entries = []
    units_done = 0

    for section in ("必考词", "基础词"):
        for u in units.get(section, []):
            key = (section, u["unit"])
            if key not in by_unit:
                continue
            if args.limit_units and units_done >= args.limit_units:
                break
            rng = [p for p in range(u["pdf_start"], u["pdf_end"] + 1) if p in pages]
            if not rng:
                continue
            units_done += 1
            stats["available_units"].append((section, u["unit"]))
            if len(rng) < u["pdf_end"] - u["pdf_start"] + 1:
                stats["pages_missing"].append(
                    {"section": section, "unit": u["unit"],
                     "missing": u["pdf_end"] - u["pdf_start"] + 1 - len(rng)})
            expected = by_unit[key]
            segs, leading = build_segments(
                pages, section, u["unit"], expected, u["pdf_start"], u["pdf_end"], stats)

            # 单元首页 = 单词表页：OCR 词序列 vs 一轮词表
            seen = preview_page_words(pages.get(u["pdf_start"], []))
            seen_set = {letters_only(x) for x in seen}
            gaps = [w for w in expected
                    if letters_only(w) not in seen_set
                    and not any(similar(w, x) for x in seen)]
            stats["unit_gaps"].append({
                "section": section, "unit": u["unit"], "pdf_page": u["pdf_start"],
                "expected": len(expected), "seen_heads": len(seen), "gaps": gaps,
            })

            if leading and entries:
                entries[-1]["_tail_seg"] = entries[-1].get("_tail_seg", []) + leading

            for word, seg, exact, ocr_head in segs:
                parsed = parse_entry(seg)
                parsed.update({"word": word, "section": section, "unit": u["unit"]})
                parsed["_exact_head"] = exact
                parsed["_ocr_head"] = ocr_head
                entries.append(parsed)

    # 跨单元的续文并回上一条
    for e in entries:
        tail = e.get("_tail_seg")
        if not tail:
            continue
        tail_text = "\n".join(ln for _, ln in tail)
        e["_raw"] += "\n" + tail_text
        e["pdf_pages"] = sorted(set(e["pdf_pages"]) | {p for p, _ in tail})
        for slot, text, _name, _g in split_marker_blocks(tail_text):
            if slot == "def":
                items = split_items(text)
                if e["senses"]:
                    e["senses"][-1]["items"].extend(items)
                else:
                    e["senses"].append({"pos": e["pos"], "items": items})
                e["examples"].extend(extract_examples(items))
            elif slot == "phrase":
                e["phrases"].extend(parse_phrases(text))
            elif slot == "examples":
                e["examples"].extend(parse_example_block(text))
            elif slot == "deriv":
                e["deriv"].extend(parse_deriv(text))
            elif slot == "syn":
                e["syn"].extend(parse_syn(text))
            elif slot == "ant":
                e["ant"].extend(parse_ant(text))

    # 校验 + 置信度
    out_entries, raw_by_word = [], {}
    for e in entries:
        flags = []
        raw_letters = letters_only(e["_raw"])
        if not e["_exact_head"]:
            flags.append("fuzzy_headword_match")
        if not e["senses"]:
            flags.append("no_senses")
        elif not any(s["items"] for s in e["senses"]):
            flags.append("empty_sense_items")
        if not e["phonetic"]:
            flags.append("no_phonetic")
        if e["word"] not in by_unit.get((e["section"], e["unit"]), []):
            flags.append("word_not_in_unit_list")
        for field, tag in (("deriv", "hallucinated_deriv"),
                           ("syn", "hallucinated_syn"),
                           ("ant", "hallucinated_ant")):
            bad = [x["word"] if isinstance(x, dict) else x for x in e[field]
                   if not trace(x["word"] if isinstance(x, dict) else x, [raw_letters])]
            if bad:
                flags.append(tag)
        if not e["mnemonic"]:
            flags.append("no_mnemonic")
        if e.get("_guessed_markers"):
            flags.append("marker_name_garbled")
        if e["_raw"].count("助记") + e["_raw"].count("记忆") > 1:
            flags.append("possible_merge")
        if not CJK_RE.search(e["_raw"]) and not e["phonetic"]:
            flags.append("ocr_garbled")

        meta = meta_by_word.get(e["word"], {})
        mnemonic = e["mnemonic"] or meta.get("mnemonic") or None
        conf = score_confidence({**e, "mnemonic": mnemonic}, flags, e["_exact_head"])
        raw_by_word[e["word"]] = e["_raw"]
        out_entries.append({
            "word": e["word"],
            "phonetic": e["phonetic"],
            "pos": e["pos"],
            "section": e["section"],
            "unit": e["unit"],
            "pdf_pages": e["pdf_pages"],
            "mnemonic": mnemonic,
            "senses": e["senses"],
            "syn": e["syn"],
            "ant": e["ant"],
            "deriv": e["deriv"],
            "phrases": e["phrases"],
            "examples": e["examples"],
            "notes": e["notes"],
            "ocr_confidence": conf,
            "flags": flags,
        })

    out_dir = root / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    covered = {x["word"] for x in out_entries}

    unmatched = []
    for x in stats["missing_in_ocr"]:
        if x["word"] in covered:
            continue
        e = meta_by_word.get(x["word"], {})
        unmatched.append({
            "word": x["word"], "section": x["section"], "unit": x["unit"],
            "reason": "missing_in_ocr",
            "one_round_meaning": (e.get("meaning") or "")[:60] or None,
        })
    for x in stats["unmatched_candidates"]:
        unmatched.append({
            "word": None, "ocr_token": x["token"], "page": x["page"],
            "section": x["section"], "unit": x["unit"],
            "reason": "candidate_not_in_unit_list",
        })

    payload = {
        "meta": {
            "source": "2026 红宝书考研英语词汇",
            "pdf": "00-红宝书.pdf",
            "pages_ocr": len(pages),
            "generated": _dt.datetime.now().isoformat(timespec="seconds"),
            "parser": "round2/tools/parse_entries.py",
        },
        "entries": out_entries,
    }
    (out_dir / "entries_r2.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "unmatched.json").write_text(json.dumps({
        "generated": payload["meta"]["generated"],
        "coverage": {"expected": len(all_entries), "covered": len(covered),
                     "ratio": round(len(covered) / max(1, len(all_entries)), 4)},
        "unmatched": unmatched,
        "unit_gaps": stats["unit_gaps"],
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    parsed_pages = set(pages)
    on_pages = [e for e in all_entries if (e.get("page") or 0) + page_offset in parsed_pages]
    payload["meta"]["page_offset"] = page_offset
    payload["meta"]["words_on_parsed_pages"] = len(on_pages)
    (out_dir / "parse_report.md").write_text(
        render_report(payload, all_entries, stats, raw_by_word), encoding="utf-8")

    print(f"entries={len(out_entries)} covered={len(covered)}/{len(all_entries)} "
          f"unmatched={len(unmatched)} pages={len(pages)} → {out_dir}")
    return 0


# ---------------------------------------------------------------- 报告

FIELD_NAMES = [("senses", "senses（有释义组）"), ("deriv", "deriv"), ("syn", "syn"),
               ("ant", "ant"), ("phrases", "phrases"), ("examples", "examples"),
               ("mnemonic", "mnemonic"), ("phonetic", "phonetic"),
               ("notes", "notes（扩展字段）")]


def render_report(payload: dict, all_entries: list, stats: dict, raw_by_word: dict) -> str:
    E = payload["entries"]
    n = len(E)
    total = len(all_entries)
    L = []
    A = L.append
    A("# 二轮词条解析质量报告")
    A("")
    A(f"- 生成时间：{payload['meta']['generated']}")
    A(f"- OCR 页数：{payload['meta']['pages_ocr']}")
    onp = payload["meta"].get("words_on_parsed_pages")
    A(f"- 解析出的词条数：**{n}**")
    A(f"- 一轮词表 {total} 词，全书覆盖率 **{n / max(1, total):.2%}**（{n}/{total}）")
    if onp:
        A(f"- **本次 OCR 覆盖页上**的一轮词数 {onp}，页内覆盖率 **{n / onp:.2%}**（{n}/{onp}）"
          f" —— 这是衡量解析器本身的关键数字")
    A("")
    if stats.get("pages_missing"):
        miss = sum(x["missing"] for x in stats["pages_missing"])
        A(f"- ⚠️ 有 {len(stats['pages_missing'])} 个单元页码不完整，共缺 {miss} 页，"
          f"这些页上的词条不可能出现")
    A("")

    A("## 1. 字段填充率")
    A("")
    A("| 字段 | 非空条目 | 填充率 |")
    A("|------|---------:|-------:|")
    for key, label in FIELD_NAMES:
        filled = sum(1 for e in E if e.get(key))
        A(f"| {label} | {filled} | {filled / max(1, n):.1%} |")
    items = sum(len(s["items"]) for e in E for s in e["senses"])
    A("")
    A(f"释义条目（senses.items 总数）：{items}，平均每词 {items / max(1, n):.2f} 条；"
      f"平均每词 {sum(len(e['phrases']) for e in E) / max(1, n):.2f} 个词组、"
      f"{sum(len(e['deriv']) for e in E) / max(1, n):.2f} 个派生、"
      f"{sum(len(e['examples']) for e in E) / max(1, n):.2f} 条例句。")
    A("")

    A("## 2. 按 section + unit 的分布")
    A("")
    A("| section | unit | 词条数 | 一轮应有 | 平均置信度 |")
    A("|---------|-----:|-------:|---------:|-----------:|")
    expect_cnt = {}
    for e in all_entries:
        expect_cnt[(e["section"], e["unit"])] = expect_cnt.get((e["section"], e["unit"]), 0) + 1
    buckets = {}
    for e in E:
        buckets.setdefault((e["section"], e["unit"]), []).append(e["ocr_confidence"])
    for (sec, unit), confs in sorted(buckets.items(),
                                     key=lambda kv: (kv[0][0] != "必考词", kv[0][1])):
        A(f"| {sec} | {unit} | {len(confs)} | {expect_cnt.get((sec, unit), 0)} | "
          f"{sum(confs) / len(confs):.2f} |")
    avail = stats.get("available_units") or list(expect_cnt)
    empty = [f"{sec} Unit {unit}" for sec, unit in avail if (sec, unit) not in buckets]
    A("")
    if empty:
        A("**完全没有解析结果的单元**：" + "；".join(empty))
        A("")

    A("## 3. flags 统计")
    A("")
    cnt = {}
    for e in E:
        for f in e["flags"]:
            cnt[f] = cnt.get(f, 0) + 1
    if cnt:
        A("| flag | 条目数 | 含义 |")
        A("|------|-------:|------|")
        meaning = {
            "fuzzy_headword_match": "headword 与一轮词形不完全一致（OCR 错字）",
            "no_senses": "没切出任何释义",
            "empty_sense_items": "有词性但释义条目为空",
            "no_phonetic": "没有音标",
            "no_mnemonic": "书上无【助记】且一轮也没有",
            "marker_name_garbled": "有标记名没认出来，靠内容形状猜的槽位",
            "hallucinated_deriv": "派生词在 OCR 原文里回溯不到",
            "hallucinated_syn": "同义词在 OCR 原文里回溯不到",
            "hallucinated_ant": "反义词在 OCR 原文里回溯不到",
            "ocr_garbled": "整条既无中文也无音标",
            "word_not_in_unit_list": "词不在该单元词表里",
            "possible_merge": "同一段里出现多个【助记】，多半把没认出来的相邻词条吞了",
        }
        for k, v in sorted(cnt.items(), key=lambda kv: -kv[1]):
            A(f"| `{k}` | {v} | {meaning.get(k, '')} |")
    else:
        A("无 flag。")
    A("")

    A("## 4. 与一轮词表的对账")
    A("")
    A(f"- 缺失词（该单元页内有、但没切出来/没对齐上）：{len(stats['missing_in_ocr'])} 个")
    A(f"- 未命中词表的候选 headword（误检）：{len(stats['unmatched_candidates'])} 个")
    A(f"- 因「下一个词没认出来」被截断的段：{stats.get('truncated_segments', 0)} 处")
    A("")
    gaps_nonempty = [g for g in stats["unit_gaps"] if g["gaps"]]
    A(f"### 4.1 单元首页（单词表页）OCR 词序列 vs 一轮词表：{len(gaps_nonempty)} 个单元有缺口")
    A("")
    if gaps_nonempty:
        A("| section | unit | 首页 | 应有 | OCR 见到 | 缺口数 | 缺口示例 |")
        A("|---------|-----:|-----:|-----:|---------:|-------:|----------|")
        for g in gaps_nonempty[:45]:
            gp = ", ".join(g["gaps"][:10]) + (" …" if len(g["gaps"]) > 10 else "")
            A(f"| {g['section']} | {g['unit']} | {g['pdf_page']} | {g['expected']} "
              f"| {g['seen_heads']} | {len(g['gaps'])} | {gp} |")
        A("")
    miss = stats["missing_in_ocr"]
    if miss:
        A("### 4.2 缺失词（前 80 个）")
        A("")
        A("、".join(f"{x['section'][:2]}{x['unit']}-{x['word']}" for x in miss[:80]))
        A("")

    A("## 5. 置信度最低的 20 个词")
    A("")
    A("| # | word | section/unit | 置信度 | flags | OCR 认成 |")
    A("|--:|------|--------------|-------:|-------|----------|")
    low = sorted(E, key=lambda x: (x["ocr_confidence"], x["word"]))[:20]
    for i, e in enumerate(low, 1):
        head = ""
        for ln in (raw_by_word.get(e["word"], "").splitlines() or [""])[:1]:
            head = ln.strip()[:34]
        A(f"| {i} | `{e['word']}` | {e['section']} {e['unit']} | {e['ocr_confidence']} "
          f"| {', '.join(e['flags']) or '-'} | {head} |")
    A("")

    A("## 6. 人工核对：OCR 原文 vs 解析结果")
    A("")
    A(sample_section(E, raw_by_word))
    A("")
    A("## 7. 未建模内容与兜底建议")
    A("")
    notes_cnt = sum(1 for e in E if e.get("notes"))
    A(f"- 书上确实存在、但 SCHEMA 没有对应字段的块（辨析/用法/联想/扩展/考点/典型考题/"
      f"试题分析）被塞进 `notes`（**扩展字段，需 SCHEMA 追认**）：{notes_cnt} 条。")
    A("- 建议再补：`examples`（正则抠的，长例句会被截断）、`phrases.zh`、"
      "以及本报告第 5 节的低置信度词条。")
    A("- 建议不上面：`notes`（辨析/考题）体量大、依赖排版、OCR 最不稳；"
      "`syn` 里的编号（①②）价值低。")
    A("")
    return "\n".join(L)


def sample_section(E: list, raw_by_word: dict) -> str:
    """挑 5 个「派生 + 词组 + 例句」俱全的词并排展示 OCR 原文与解析结果。"""
    pool = [e for e in E if e["deriv"] and e["phrases"] and e["examples"] and e["senses"]]
    if len(pool) < 5:
        pool = sorted(E, key=lambda e: -(len(e["deriv"]) + len(e["phrases"])
                                         + len(e["examples"]) + len(e["senses"])))[:5]
    picks = sorted(pool, key=lambda e: -(len(e["deriv"]) + len(e["phrases"]) + len(e["examples"])))[:5]
    if not picks:
        return "（没有可用的样例条目）"
    out = []
    for e in picks:
        out.append(f"### `{e['word']}`（{e['section']} Unit {e['unit']}，"
                   f"p.{','.join(map(str, e['pdf_pages']))}，conf={e['ocr_confidence']}）")
        out.append("")
        raw = raw_by_word.get(e["word"], "")
        raw_lines = [ln for ln in raw.splitlines() if ln.strip()][:14]
        out.append("OCR 原文（前 14 行）：")
        out.append("```text")
        out.extend(raw_lines)
        out.append("```")
        out.append("解析结果：")
        out.append("```json")
        sub = {k: e[k] for k in ("phonetic", "pos", "senses", "deriv", "syn", "ant",
                                 "phrases", "examples")}
        out.append(json.dumps(sub, ensure_ascii=False, indent=1)[:1800])
        out.append("```")
        out.append(f"flags：{', '.join(e['flags']) or '（无）'}")
        out.append("")
    return "\n".join(out)


# ---------------------------------------------------------------- 自测

SAMPLE_PAGE_ONE = """\
remain                     [rɪ'meɪn] v.
【助记】re(again 再,又)+main(=man 停留)→余留,留待
【词义】① 剩下,余留: In the late autumn, few apples ~ ed on the tree. 晚秋树上没剩下几个苹果。
      ② 留待,尚需: This ~ s to be proved. 这尚待证实。
      ③ 仍然是,依旧是: to ~ silent 保持沉默 / The affair ~ ed a complete mystery. 这事仍然是个谜。
【词组】it remains to be seen 情况仍未明,要看怎样发展
【真题例句】There are many different types of automatic door, with each relying on specific signals to tell them when to open.
"""

SAMPLE_PAGE_TWO = """\
strain                     [streɪn]
【助记】train(火车)前面放 "s",司机很strain(紧张)
【词性】❶ v.
【词义】① 使紧张,尽力使用: ~ one's eyes 瞪大眼睛看
【词性】❷ n.
【词义】① 拉力,张力: Can nylon ropes take more ~ than the old kind rope?
【同义】① tension ③ injury
【反义】relaxation n. 松弛,缓和
【派生】strained ['streɪnd] adj. 紧张的;勉强的,不自然的
【词组】be(或become,fall) prey to sth. 被……捕食
"""

# 真实 tesseract 退化形态（取自 PDF 第 10/11 页的实际输出，未做人工纠错）
SAMPLE_PAGE_DEGRADED = """\
remedy |                             | !remadi |
(JO nv.
【词义]@ 治疗,治疗法,药品:  This doctor often uses herbal
remedies. ix K i AH eH
Q 补救{ 办法) , 2 iE ( Pri#) We only ~ is to appeal to
law. 你的唯一补救办法是诉诸法律。
[ 词性】全 w.
【词义】@ 医治,治疗:4spirin may ~ headache. 阿斯匹林可
治头痛。
【 词组 ] remedy for 对……的治疗 ,补救
【 JRE ) remedial [ r1' mizdial ] adj. 治疗的,矫了
"""


def self_test() -> int:
    fails = []

    def chk(cond, msg):
        if not cond:
            fails.append(msg)

    part1 = SAMPLE_PAGE_ONE.rstrip().splitlines()
    e = parse_entry([(10, ln) for ln in part1])
    chk(e["phonetic"] == "rɪ'meɪn", f"phonetic: {e['phonetic']}")
    chk(e["pos"] == "v.", f"pos: {e['pos']}")
    chk(len(e["senses"]) == 1, f"senses groups: {len(e['senses'])}")
    chk(len(e["senses"][0]["items"]) == 3, f"items: {e['senses'][0]['items']}")
    chk(e["phrases"] and e["phrases"][0]["en"] == "it remains to be seen",
        f"phrases: {e['phrases']}")
    chk(e["mnemonic"] and e["mnemonic"].startswith("re(again"), f"mnemonic: {e['mnemonic']}")

    e2 = parse_entry([(12, ln) for ln in SAMPLE_PAGE_TWO.splitlines()])
    chk(len(e2["senses"]) == 2, f"two pos groups: {e2['senses']}")
    chk([s["pos"] for s in e2["senses"]] == ["v.", "n."],
        f"group pos: {[s['pos'] for s in e2['senses']]}")
    chk(e2["syn"] == ["tension", "injury"], f"syn: {e2['syn']}")
    chk(e2["ant"] and e2["ant"][0]["word"] == "relaxation"
        and e2["ant"][0]["pos"] == "n." and "松弛" in (e2["ant"][0]["meaning"] or ""),
        f"ant: {e2['ant']}")
    chk(e2["deriv"] and e2["deriv"][0]["word"] == "strained"
        and e2["deriv"][0]["phonetic"].strip("'’") == "streɪnd"
        and e2["deriv"][0]["pos"] == "adj.", f"deriv: {e2['deriv']}")
    chk(len(e2["phrases"]) == 1
        and e2["phrases"][0]["en"].startswith("be(或become,fall) prey to sth."),
        f"phrase en/zh split: {e2['phrases']}")

    # 退化形态：`(JO nv.` / `[ 词性】全 w.` / `【 JRE )`（派生名认不出来）
    e3 = parse_entry([(13, "remedy")] + [(13, ln) for ln in SAMPLE_PAGE_DEGRADED.splitlines()])
    chk(e3["senses"], f"degraded senses: {e3['senses']}")
    chk(len(e3["senses"]) == 2, f"degraded sense groups: {e3['senses']}")
    chk(any(s["pos"] == "v." for s in e3["senses"]), f"degraded v. pos: {e3['senses']}")
    chk(e3["phrases"], f"degraded phrase: {e3['phrases']}")
    chk(e3["deriv"] and e3["deriv"][0]["word"] == "remedial", f"degraded deriv: {e3['deriv']}")

    # 切词：OCR 把 strain 认成 strairn，且正文里混入误检候选
    pages = {1: ["memo       [ˈmeməʊ] n.",
                 "【词义】① 备忘录: a ~ on the desk 桌上的备忘录"],
             2: ["kitchen. The dish is on the table.",
                 "strairn    [streɪn] v.",
                 "【词义】① 使紧张: ~ one's eyes 瞪大眼睛看"]}
    stats = {"missing_in_ocr": [], "unmatched_candidates": [], "unit_gaps": [],
             "pages_missing": [], "truncated_segments": 0, "available_units": []}
    segs, _leading = build_segments(pages, "必考词", 1, ["memo", "strain"], 1, 2, stats)
    chk([s[0] for s in segs] == ["memo", "strain"],
        f"segment words: {[s[0] for s in segs]}")
    chk(segs and segs[-1][2] is False, "fuzzy head should be marked non-exact")

    if fails:
        print("SELF-TEST FAILED:")
        for f in fails:
            print("  -", f)
        return 1
    print(f"self-test ok: {16 + 2} checks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
