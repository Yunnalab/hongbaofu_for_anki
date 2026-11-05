#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""二轮词条解析器：round2/ocr/page_*.txt → round2/data/entries_r2.json。

契约见 round2/SCHEMA.md。对着合并版 OCR（中文层汉字 + 英文层分词）实测写成，
不假设行内排版规范。

设计要点：

1. **切词靠「单元词表 + 书上顺序」**。每单元从 units.json 拿到页码范围，正文里
   「行首是拉丁词、整行无汉字」的行才可能是 headword，且必须在该单元尚未出现的
   词里按顺序命中（先精确前缀，再编辑距离 ≤2 的模糊匹配）。于是
   `reliable[rr'laiobl] adj.` / `unreliableadj` / `removeEn'muviu` 都能切对，
   而 `【词义】` 之类的中文行不会被误判成词头。
2. **标记解析容忍 OCR 退化**。`【】` 常被认成 `[]()`、`【词义]`、`【词义]】`、
   `[词义`；名字丢了就靠标记名本身，名字前有 1–2 个粘连字母（`【s词义】`）也要认。
   标记后紧跟 `】]）`、圈码或行尾才算标记，避免把「本题是词义辨析题」当成标记。
3. **不编造中文释义**。解析不到就留空；deriv/syn/ant 的英文词必须在该词条 OCR
   原文里能回溯（大小写不敏感），否则打 `hallucinated_*`。
4. **置信度是扣分制**（见 score_confidence），没有 1.0——OCR 本身就不完美。

用法：
    python3 round2/tools/parse_entries.py                # 解析全量
    python3 round2/tools/parse_entries.py --units         # 只重建 units.json
    python3 round2/tools/parse_entries.py --limit-pages 30  # 只解析前 30 页（调试）
    python3 round2/tools/parse_entries.py --self-test     # 内置样本单测
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OCR_DIR = ROOT / "round2" / "ocr"
DATA_DIR = ROOT / "round2" / "data"
UNITS_JSON = OCR_DIR / "units.json"
ROUND1_JSON = ROOT / "all_entries_v2.json"

CJK_CLS = "\u4e00-\u9fff"
CJK_RE = re.compile(f"[{CJK_CLS}]")
CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳❶❷❸❹❺❻❼❽❾❿➀➁➂➃➄➅➆➇➈➉"
CIRCLED_RE = re.compile(f"[{CIRCLED}]")
# 页眉页脚/装饰行
NOISE_RE = re.compile(r"^\s*(?:[·•.…\-—_=~*\s]*\d{1,4}[·•.…\-—_=~*\s]*|红宝书?)\s*$")

POS_ALIAS = {
    "adj": "adj.", "ag": "adj.", "adi": "adj.", "ad": "adj.", "a": "adj.",
    "adv": "adv.", "adu": "adv.", "ad": "adv.",
    "n": "n.", "m": "n.",
    "v": "v.", "w": "v.", "u": "v.", "ut": "vt.", "ot": "vt.",
    "vt": "vt.", "vi": "vi.", "prep": "prep.", "conj": "conj.",
    "pron": "pron.", "num": "num.", "art": "art.", "int": "int.",
    "aux": "aux.", "pl": "pl.",
}
POS_KEYS = sorted(POS_ALIAS, key=len, reverse=True)
POS_TOKEN_RE = re.compile(r"(?<![A-Za-z])(" + "|".join(POS_KEYS) + r")(?![A-Za-z])\.?", re.I)
# 严格词性：要求带点号（预览行里末尾的 `u` 复选框/列标记会被宽松版误判成 v.）
POS_STRICT_RE = re.compile(
    r"(?<![A-Za-z])(adj|adv|vi|vt|prep|conj|pron|num|art|n|v)\.", re.I)
# 单词后紧跟词性、没有点号的情形（`unreliableadj`）
POS_GLUED_RE = re.compile(r"(" + "|".join(POS_KEYS) + r")\.?$", re.I)

# 标记名（长的先匹配），名字→槽位
MARKER_NAMES = [
    "真题例句", "典型考题", "典型真题", "试题分析", "词汇辨析", "习惯用语",
    "助记", "词性", "词义", "同义", "反义", "派生", "词组", "搭配",
    "辨析", "例句", "扩展", "谚语", "句意", "解析", "考点",
]
MARKER_SLOT = {
    "助记": "mnemonic",
    "词性": "pos", "词义": "def",
    "同义": "syn", "反义": "ant", "派生": "deriv",
    "词组": "phrase", "搭配": "phrase", "习惯用语": "phrase",
    "例句": "examples", "真题例句": "examples",
    "辨析": "notes", "词汇辨析": "notes", "扩展": "notes", "解析": "notes",
    "谚语": "notes", "句意": "notes", "考点": "notes",
    "典型考题": "exam", "典型真题": "exam", "试题分析": "exam",
}
CLOSERS = "】]］〕)）:："
SUFFIXES = ("ed", "d", "s", "ing", "er", "est", "ly", "al", "y", "ies",
            "able", "ness", "ment", "ion", "tion", "es")


# ------------------------------------------------------------------ 基础工具

def clean_spaces(s: str) -> str:
    return re.sub(r"[ \t\u00a0\u3000]+", " ", s).strip()


def letters_only(s: str) -> str:
    return re.sub(r"[^a-z]", "", s.lower())


def join_lines(lines: list[str]) -> str:
    """中文行折行不加空格，拉丁两侧加空格。"""
    out = ""
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        if not out:
            out = ln
        elif CJK_RE.search(out[-1]) and CJK_RE.search(ln[0]):
            out += ln
        else:
            out += " " + ln
    return out


def glue_word_spaces(s: str) -> str:
    """`t ra nsoferabrle` → `transoferabrle`：拉丁字母之间的空格是 OCR 拆字。

    但 `relaxation n。松驰` 里的 `n` 是词性缩写，粘上去就毁了，所以右侧若是
    词性别名就不粘。
    """
    out = []
    i = 0
    for m in re.finditer(r"(?<=[A-Za-z])(\s+)(?=[a-z])", s):
        if m.start() < i:
            continue
        right = s[m.end():]
        tok = re.match(r"[a-z]+", right).group(0) if re.match(r"[a-z]+", right) else ""
        if tok.lower() in POS_ALIAS:
            continue
        out.append(s[i:m.start()])
        i = m.end()
    out.append(s[i:])
    return "".join(out)


def glue_tilde(s: str) -> str:
    """`~ ed` → `~ed`（只粘后缀，`~ one's eyes` 不动）。"""
    def rep(m):
        return "~" + m.group(1)
    pat = r"~[ \t]+(" + "|".join(SUFFIXES) + r")\b"
    return re.sub(pat, rep, s)


def edist(a: str, b: str) -> int:
    if a == b:
        return 0
    if abs(len(a) - len(b)) > 3:
        return 9
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


# ------------------------------------------------------------------ 标记

def marker_of(line: str):
    """行首是不是标记；返回 (名字, 去掉标记后的剩余串) 或 (None, line)。"""
    s = line.lstrip()
    # 去掉行首 0–3 个标点/括号（！【[（ 等）
    i = 0
    while i < len(s) and i < 4 and not (s[i].isalnum() or CJK_RE.match(s[i])):
        i += 1
    s = s[i:]
    cands = [s]
    # 标记名前粘连 1–2 个洋文垃圾：`s词义`、`o助记`
    for k in (1, 2):
        if len(s) > k and s[:k].isascii() and s[:k].isalpha():
            cands.append(s[k:])
    for cand in cands:
        for name in MARKER_NAMES:
            if not cand.startswith(name):
                continue
            rest = cand[len(name):].lstrip()
            if not rest or rest[0] in CLOSERS or rest[0] in CIRCLED:
                # 允许 `】】`、`]】` 之类重复括号
                while rest and rest[0] in CLOSERS:
                    rest = rest[1:].lstrip()
                return name, rest
    return None, line


def split_blocks(lines: list[str]):
    """切 (marker_slot, name, lines[])；首个块 slot 为 None（词头行）。"""
    blocks = []
    cur_name, cur_lines = None, []
    for ln in lines:
        name, rest = marker_of(ln)
        if name:
            blocks.append((cur_name, cur_lines))
            cur_name, cur_lines = name, ([rest] if rest else [])
        else:
            cur_lines.append(ln)
    blocks.append((cur_name, cur_lines))
    return blocks


# ------------------------------------------------------------------ 音标/词性

PHON_BRACKETS = [("[", "]"), ("［", "］"), ("【", "】"), ("「", "】"), ("{", "}")]
IPA_OK = set("abcdefghijklmnopqrstuvwxyzæɑɒɔəɜɪʊʌʃʒθðŋˈˌː'’()-,;:.������ɡ")


def parse_head_phon_pos(line: str, word: str):
    """从词头行抠音标与词性。"""
    rest = line.strip()
    # 去掉词头（容 OCR 把词形认长一点，取最长公共前缀长度）
    low, wl = rest.lower(), word.lower()
    k = 0
    while k < len(wl) and k < len(low) and low[k] == wl[k]:
        k += 1
    body = rest[k:] if k >= len(wl) - 1 else rest
    phon = None
    m = re.search(r"[\[［【「]\s*([^\]］】」\n]{1,45}?)\s*[\]］】」]", body)
    if m:
        raw = m.group(1).strip()
        if raw and all((c in IPA_OK) or c.isalpha() for c in raw):
            phon = clean_spaces(raw)
    pos = None
    body_nophon = re.sub(r"[\[［【「][^\]］】」]*[\]］】」]?", " ", body)
    m2 = POS_TOKEN_RE.search(body_nophon)
    if m2:
        pos = POS_ALIAS.get(m2.group(1).lower())
    return phon, pos


def parse_pos_block(lines: list[str]):
    """【词性】块 → 词性串（可能为空）。"""
    t = glue_word_spaces(join_lines(lines))
    for m in POS_TOKEN_RE.finditer(t):
        return POS_ALIAS.get(m.group(1).lower())
    m = POS_GLUED_RE.search(t.strip())
    if m:
        return POS_ALIAS.get(m.group(1).lower())
    return None


# ------------------------------------------------------------------ 各字段解析

def parse_senses(def_blocks):
    """[(pos, lines)] → senses；一个 def 块内部按圈码切 items。"""
    senses = []
    for pos, lines in def_blocks:
        text = glue_tilde(join_lines([re.sub(r"の", "②", ln) for ln in lines]))
        text = clean_spaces(text)
        if not text:
            continue
        parts = []
        cur = ""
        for ch_i, ch in enumerate(text):
            if ch in CIRCLED:
                if cur.strip():
                    parts.append(cur.strip())
                cur = ch
            else:
                cur += ch
        if cur.strip():
            parts.append(cur.strip())
        if not parts:
            continue
        items = [clean_spaces(p) for p in parts if clean_spaces(p)]
        target = None
        for s in senses:
            if s["pos"] == pos:
                target = s
                break
        if target is None:
            target = {"pos": pos, "items": []}
            senses.append(target)
        target["items"].extend(items)
    return senses


EN_STARTERS = set("""the a an it we they he she i you in on to for if when
do does did not this that these those there what how why while although
because but and or as at by from of with without after before during one
two all some many most more no can could will would should may might must
have has had be is are was were being her his their our my your its us them
me him who whom which whose so such then than too very just only even both
each every either neither another other same own few little much several""".split())
EN_RUN_RE = re.compile(r"[A-Za-z0-9'’\"~\-.,;:!?()/\[\]？。 ]{12,}")
ZH_RUN_RE = re.compile(f"[{CJK_CLS}，。；：、（）“”‘’！？…—·]{{4,}}")


def split_example(item: str):
    """从一条「释义：英文例句 中文翻译」里尽力抠出 (en, zh)。"""
    best = None
    for m in EN_RUN_RE.finditer(item):
        seg = m.group(0).strip(" ,;:/")
        if len(seg) < 12 or len(seg.split()) < 3:
            continue
        if not re.search(r"[.?!？。…\"”]$", seg):
            continue  # 折行被截断的碎片，别当例句
        first = re.match(r"[A-Za-z]+", seg)
        if not seg[0].isupper() and (first is None or first.group(0).lower() not in EN_STARTERS):
            continue  # 以小写碎片开头（`ed by the show…`）说明前半句被吃了
        if not re.search(r"[A-Za-z]{3}", seg):
            continue
        if not re.search(r"[a-z]{3}", seg):
            continue  # 全大写/全噪声
        if best is None or len(seg) > len(best[1]):
            best = (m.start(), seg, m.end())
    if not best:
        return None
    start, en, end = best
    rest = item[end:]
    zh = ""
    m = ZH_RUN_RE.search(rest)
    if m:
        zh = m.group(0).strip()
    if not zh:
        # 英文前后可能夹着中文释义，退一步找英文段后面的中文
        m = ZH_RUN_RE.search(item[start + len(en):])
        if m:
            zh = m.group(0).strip()
    if not zh or len(zh) < 4:
        return None
    return en, zh


def parse_def_examples(senses):
    out = []
    for s in senses:
        for it in s["items"]:
            r = split_example(it)
            if r:
                out.append({"en": r[0], "zh": r[1]})
    return out


def parse_example_block(lines):
    """【真题例句】/【例句】块：英文 + 中文（+【2024年考研阅读】）。"""
    text = clean_spaces(join_lines(lines))
    if not text:
        return []
    text = re.sub(r"【[^】]*年考研[^】]*】", "", text).strip()
    m = re.search(f"[{CJK_CLS}]", text)
    if not m:
        return [{"en": text, "zh": None}] if len(text) > 10 else []
    i = m.start()
    en, zh = text[:i].strip(" ,.;:"), text[i:].strip()
    if len(en) < 8:
        return []
    return [{"en": glue_tilde(en), "zh": clean_spaces(zh)}]


SYN_STOP = set(POS_KEYS) | {"and", "or", "the", "of", "to", "in", "on", "with",
                            "sth", "sb", "pl", "esp"}


def parse_syn(lines):
    t = clean_spaces(glue_word_spaces(join_lines(lines)))
    words = []
    for m in re.finditer(r"[A-Za-z][A-Za-z'\-]*", t):
        w = m.group(0)
        lw = w.lower()
        if len(letters_only(w)) < 3:
            continue
        if lw in SYN_STOP:
            continue
        words.append(w)
    # 折行把词拆成两段（`adva`+`ntage` = advantage）：拼起来是词表里的词就合并
    merged = []
    for w in words:
        if merged and words is not None:
            joined = merged[-1] + w
            if (letters_only(merged[-1]) not in KNOWN_WORDS
                    and letters_only(w) not in KNOWN_WORDS
                    and letters_only(joined) in KNOWN_WORDS):
                merged[-1] = joined
                continue
        merged.append(w)
    out = []
    for w in merged:
        if w not in out:
            out.append(w)
    return out


KNOWN_WORDS: set[str] = set()


def _split_word_pos_meaning(tok: str):
    """`unreliableadj` → ('unreliable', 'adj.')。

    只在前缀确实是一轮词表里的词时才切——否则 `roundabout` 会被切成
    `roundabo`+`ut.(vt.)`，`shut`/`about` 同理。
    """
    lw = tok.lower()
    if lw in KNOWN_WORDS:
        return tok, None
    for alias in POS_KEYS:
        if len(alias) < 2 or not lw.endswith(alias):
            continue
        head = tok[: -len(alias)]
        if len(head) >= 3 and head.lower() in KNOWN_WORDS:
            return head, POS_ALIAS[alias]
        # 派生词（unreliable）不在词表里：`ut`/`ot` 会误伤 about/shut，排除掉
        if len(head) >= 4 and alias not in ("ut", "ot"):
            return head, POS_ALIAS[alias]
    return tok, None


POS_PUNCT = ".．。：:，,、；;"


def parse_ant(lines):
    """【反义】→ [{"word","pos","meaning"}]。

    书上写法很不统一：`unreliableadj不可靠的，不能信赖的`（词性黏在词后）、
    `roundabout adj：迁回的，拐弯抹角的`（词性单独成词）、`relaxation n。松驰`。
    做法：按拉丁词扫描，词性是别名就并入上一段的释义，否则算新词。
    """
    t = clean_spaces(glue_word_spaces(join_lines(lines)))
    out = []
    if not t:
        return out
    toks = [(m.start(), m.end(), m.group(0))
            for m in re.finditer(r"[A-Za-z][A-Za-z'\-]*", t)]
    accepted = []
    for st, en, tok in toks:
        if tok.lower() in POS_ALIAS and len(tok) <= 4:
            continue
        if len(letters_only(tok)) < 3:
            continue
        accepted.append((st, en, tok))
    for i, (st, en, tok) in enumerate(accepted):
        seg_end = accepted[i + 1][0] if i + 1 < len(accepted) else len(t)
        word, pos = _split_word_pos_meaning(tok)
        tail = t[en:seg_end]
        mp = re.match(r"\s*([A-Za-z]{1,4})[.．。：:]?\s*(.*)$", tail, re.S)
        if mp and mp.group(1).lower() in POS_ALIAS:
            pos = pos or POS_ALIAS.get(mp.group(1).lower())
            tail = mp.group(2)
        meaning = clean_spaces(tail.strip(" \t" + POS_PUNCT)) or None
        if meaning and not CJK_RE.search(meaning):
            meaning = None
        if out and out[-1]["word"].lower() == word.lower():
            continue
        out.append({"word": word, "pos": pos, "meaning": meaning})
    return out


DERIV_RE = re.compile(
    r"([A-Za-z][A-Za-z'’\-]{1,24})\s*"
    r"(?:[\[［【「]\s*([^\]］】」\n]{0,45}?)\s*[\]］】」])?\s*"
    r"(adj|adv|vi|vt|prep|conj|n|v|u|w)\.?\s*(真的)?",
    re.I,
)


def parse_deriv(lines):
    t = clean_spaces(glue_word_spaces(join_lines(lines)))
    if not t:
        return []
    t = re.sub(r"派\s*生\s*】", "", t)  # 【派~生】
    out = []
    matches = list(DERIV_RE.finditer(t))
    for i, m in enumerate(matches):
        word = m.group(1)
        if len(letters_only(word)) < 3:
            continue
        phon = clean_spaces(m.group(2)) if m.group(2) else None
        if phon is not None:
            phon = phon.strip("［［[]］]】「」 ")
            if phon and not all((c in IPA_OK) or c.isalpha() for c in phon):
                phon = None
        pos = POS_ALIAS.get(m.group(3).lower())
        seg_end = matches[i + 1].start() if i + 1 < len(matches) else len(t)
        tail = t[m.end():seg_end]
        meaning = clean_spaces(tail.strip(" ：:。，,／/")) or None
        if meaning and not CJK_RE.search(meaning):
            meaning = None
        if out and out[-1]["word"].lower() == word.lower():
            continue
        out.append({"word": word, "phonetic": phon, "pos": pos, "meaning": meaning})
    return out


def _split_circled(text: str):
    parts, cur = [], ""
    for ch in text:
        if ch in CIRCLED:
            if cur.strip():
                parts.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        parts.append(cur.strip())
    return parts


def _first_cjk_outside_paren(text: str):
    depth = 0
    for i, ch in enumerate(text):
        if ch in "（(":
            depth += 1
        elif ch in "）)":
            depth = max(0, depth - 1)
        elif depth == 0 and CJK_RE.match(ch):
            return i
    return -1


def parse_phrases(lines):
    text = clean_spaces(glue_tilde(join_lines(lines)))
    if not text:
        return []
    out = []
    for seg in _split_circled(text):
        i = _first_cjk_outside_paren(seg)
        if i <= 0:
            if re.search(r"[A-Za-z]{2}", seg):
                out.append({"en": clean_spaces(seg), "zh": None})
            continue
        en = clean_spaces(seg[:i].rstrip(" ：:，,"))
        zh = clean_spaces(seg[i:])
        if re.search(r"[A-Za-z]{2}", en):
            out.append({"en": en, "zh": zh or None})
    return out


# ------------------------------------------------------------------ 词头对齐

CHECKBOX = "口□■▢▪"


def is_preview_line(line: str) -> bool:
    """清单页上四栏预览词表的行：纯英文、没有音标、没有词性、没有标记。"""
    s = line.strip()
    # 勾选框字形 `口` 会被当成汉字，先当空白
    s = re.sub(f"[{CHECKBOX}]", " ", s).strip()
    if not s or CJK_RE.search(s):
        return False
    name, _ = marker_of(s)
    if name:
        return False
    if re.search(r"[\[［【「][^\]］】」]{2,}[\]］】」]", s):
        return False
    if POS_STRICT_RE.search(s):
        return False
    if not re.match(r"^[A-Za-z]", s):
        return False
    toks = [t for t in s.split() if re.search(r"[A-Za-z]", t)]
    # 预览行要么一行挤好几个词，要么是一个长串粘起来的词（`removalcontemptdiverseexecut`）；
    # 正文词头是短词，且后面常跟音标行，所以不会被这里误杀。
    if len(toks) >= 2:
        return all(len(letters_only(t)) >= 2 for t in toks)
    # 单 token 的长串（`lamboathpairpar`）也是预览行；正文词头若音标在下一行，
    # 下一行以 `[`/`［` 开头、不是拉丁行，所以孤立的长词头不会被误杀。
    return len(letters_only(s)) >= 10


def find_body_start(lines: list[str]) -> int:
    """清单页：左栏开头是预览词表，正文从第一个「后面 2 行内出标记」的词头开始。"""
    for i, ln in enumerate(lines):
        if CJK_RE.search(re.sub(f"[{CHECKBOX}]", " ", ln)) or not re.match(r"^[A-Za-z]", ln.strip()):
            continue
        if is_preview_line(ln):
            continue
        for j in range(i + 1, min(i + 3, len(lines))):
            name, _ = marker_of(lines[j])
            if name:
                return i
    return 0


def strip_preview(lines: list[str], min_run: int = 2) -> list[str]:
    """丢掉清单页里的预览词表块（连续 ≥3 行预览行）。

    预览块在左栏开头和右栏开头各有一段（同一页），会污染词头对齐：`p9`
    的 `remindcontradict document] exotic` 会被当成 `remind` 的词头。
    """
    drop = [False] * len(lines)
    i = 0
    while i < len(lines):
        if not is_preview_line(lines[i]):
            i += 1
            continue
        j = i
        while j < len(lines) and is_preview_line(lines[j]):
            j += 1
        if j - i >= min_run:
            for k in range(i, j):
                drop[k] = True
        i = j
    return [ln for ln, d in zip(lines, drop) if not d]


def is_headword_line(line: str) -> bool:
    s = line.strip()
    if not s or len(s) > 60:
        return False
    if CJK_RE.search(s):
        return False
    if not re.match(r"^[A-Za-z]", s):
        return False
    if NOISE_RE.match(s):
        return False
    # 4 个以上英文词的整行必然是例句/考题碎片，不是词头
    toks = [t for t in s.split() if re.search(r"[A-Za-z]", t)]
    if len(toks) >= 4 and not POS_STRICT_RE.search(s) and \
            not re.search(r"[\[［【「][^\]］】」]{2,}[\]］】」]", s):
        return False
    return True


def head_lead(line: str) -> str:
    """行首拉丁串（可能粘着音标前的垃圾），返回纯字母。"""
    m = re.match(r"^[A-Za-z][A-Za-z'’\-]*", line.strip())
    return letters_only(m.group(0)) if m else ""


def match_headword(line: str, words: list[str], ptr: int, used=None):
    """在 words[ptr-1 : ptr+25] 里找该行的词头。返回 (index, how, matched_word)。

    书上正文顺序与一轮词表顺序一致（清单页是同一顺序的四栏预览），所以先用
    顺序窗口；窗口内找不到再全局找一次（`used` 里已切过的词跳过），打完
    `*_out_of_order` 标记，避免因个别错序吞掉后面的词条。
    """
    lead = head_lead(line)
    if not lead:
        return None
    hit = _match_in_window(line, lead, words, max(0, ptr - 1), min(len(words), ptr + 25))
    if hit:
        return hit
    if used:
        hit = _match_in_window(line, lead, words, 0, len(words), used)
        if hit:
            return hit[0], hit[1] + "_out_of_order", hit[2]
    return None


def _match_in_window(line, lead, words, lo, hi, used=None):
    idx = list(range(lo, hi))
    if used:
        idx = [j for j in idx if j not in used]
    # 1) 精确前缀
    for j in range(lo, hi):
        w = letters_only(words[j])
        if w and lead.startswith(w):
            # 判边界：`strain` 不能吃 `straight`
            nxt = line.strip()[len(re.match(r'^[A-Za-z\'’\-]*', line.strip()).group(0)):]
            if lead == w or nxt[:1] in ("", " ", "[", "［", "\t") or not nxt[:1].isalpha():
                return j, "exact", words[j]
    # 2) 词头被 OCR 认长/认短：词形是 lead 的前缀（`strainstreim`）
    for j in idx:
        w = letters_only(words[j])
        if len(w) >= 4 and lead.startswith(w[: max(4, len(w) - 1)]):
            return j, "prefix", words[j]
    # 3) 模糊：短词（≤4 字母）用编辑距离配任何短串都会误中（`his` 能配上 `zip`），
    #    所以只对 ≥5 字母、首字母相同、且距离很小的词做模糊匹配。
    best = None
    for j in idx:
        w = letters_only(words[j])
        if len(w) < 5 or not lead or lead[0] != w[0]:
            continue
        cand = lead[: len(w) + 1]
        d = edist(cand, w)
        lim = 1 if len(w) <= 6 else 2
        if d <= lim and (best is None or d < best[0]):
            best = (d, j)
    if best:
        return best[1], "fuzzy", words[best[1]]
    return None


def head_score(line: str, word: str) -> int:
    """该行当 `word` 的词头有多像：3 精确 / 2 粘字 / 1 模糊 / 0 不像。"""
    lead = head_lead(line)
    w = letters_only(word)
    if not lead or not w:
        return 0
    if lead.startswith(w):
        run = re.match(r"^[A-Za-z'\u2019\-]*", line.strip()).group(0)
        nxt = line.strip()[len(run):]
        if lead == w or not nxt[:1].isalpha():
            return 3
    if len(w) >= 4 and lead.startswith(w[: max(4, len(w) - 1)]):
        return 2
    if len(w) >= 5 and lead[0] == w[0]:
        lim = 1 if len(w) <= 6 else 2
        # 取两种截断的最小距离：OCR 多认一个字母（shuuttle）、或多认又替错
        # 几个字母（relanceTrilarens ← reliance）
        d = min(edist(lead[: len(w)], w), edist(lead[: len(w) + 1], w))
        if d <= lim:
            return 1
    return 0


def followed_by_marker(pages_lines, i: int) -> bool:
    """第 i 行后面紧跟标记行（【词义】…）——本书里这就是词头行的排版规律。"""
    for j in range(i + 1, min(i + 3, len(pages_lines))):
        name, _ = marker_of(pages_lines[j][1])
        if name:
            return True
    return False


def segment_unit(pages_lines, words):
    """把某单元的正文行切成 [{idx, how, lines}]（idx=None 表示认不出的词头）。

    用**单调对齐**（LCS 式 DP）而不是「指针推进」：清单页上残留的预览行
    （`surround` 单独成行）会命中序号 87，指针一推进，后面整段正文就全变成
    「乱序」。DP 以「全局对上的词最多」为目标，自动把这类孤立行丢掉。
    """
    cands = [(i, ln) for i, (pg, ln) in enumerate(pages_lines) if is_headword_line(ln)]
    n, m = len(cands), len(words)
    if not n:
        return []
    score = [[0] * m for _ in range(n)]
    for a, (_, ln) in enumerate(cands):
        for b in range(m):
            sc = head_score(ln, words[b])
            if sc:
                score[a][b] = sc
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for a in range(1, n + 1):
        row, prev_row, srow = dp[a], dp[a - 1], score[a - 1]
        for b in range(1, m + 1):
            best = prev_row[b] if prev_row[b] > row[b - 1] else row[b - 1]
            if srow[b - 1]:
                cand = prev_row[b - 1] + srow[b - 1]
                if cand > best:
                    best = cand
            row[b] = best
    pairs = []
    a, b = n, m
    while a > 0 and b > 0:
        if score[a - 1][b - 1] and dp[a][b] == dp[a - 1][b - 1] + score[a - 1][b - 1]:
            pairs.append((cands[a - 1][0], b - 1, score[a - 1][b - 1]))
            a -= 1
            b -= 1
        elif dp[a][b] == dp[a - 1][b]:
            a -= 1
        else:
            b -= 1
    pairs.reverse()
    how_of = {3: "exact", 2: "prefix", 1: "fuzzy"}
    starts = {line_i: (j, how_of[sc]) for line_i, j, sc in pairs}

    chunks, cur = [], None
    for i, (page, line) in enumerate(pages_lines):
        if i in starts:
            j, how = starts[i]
            if cur is not None and cur["idx"] == j:
                cur["lines"].append((page, line))  # 同词重复词头（多词性分条印）
                continue
            cur = {"idx": j, "how": how, "lines": [(page, line)]}
            chunks.append(cur)
            continue
        if cur is None:
            continue
        if is_headword_line(line) and followed_by_marker(pages_lines, i):
            same = cur["idx"] is not None and head_lead(line) == letters_only(words[cur["idx"]])
            if same:
                cur["lines"].append((page, line))
                continue
            # 认不出词头的词条：照样断句，内容留给 assign_orphans
            cur = {"idx": None, "how": "lost", "lines": [(page, line)]}
            chunks.append(cur)
            continue
        cur["lines"].append((page, line))
    return chunks


# ------------------------------------------------------------------ 词条组装

def assemble(word, section, unit, chunk, raw_chunk_text, unit_words):
    flags = []
    pages = []
    lines = chunk["lines"] if chunk else []
    for p, _ in lines:
        if p not in pages:
            pages.append(p)
    head_line = lines[0][1] if lines else ""
    phon, head_pos = parse_head_phon_pos(head_line, word)
    how = chunk["how"] if chunk else ""
    if how == "lost":
        flags.append("headword_unverified")
    if how.startswith("fuzzy"):
        flags.append("fuzzy_headword")
    if how.startswith("prefix"):
        flags.append("glued_headword")
    if how.endswith("out_of_order"):
        flags.append("out_of_order_headword")

    blocks = split_blocks([ln for _, ln in lines[1:]]) if lines else []
    def_blocks, mnemonic, syn, ant, deriv, phrases, examples = [], None, [], [], [], [], []
    pos_seq = []
    for name, blines in blocks:
        slot = MARKER_SLOT.get(name) if name else None
        if slot == "mnemonic":
            m = clean_spaces(join_lines(blines))
            if m:
                mnemonic = (mnemonic + " " + m) if mnemonic else m
        elif slot == "pos":
            p = parse_pos_block(blines)
            if p:
                pos_seq.append(p)
        elif slot == "def":
            def_blocks.append((pos_seq[-1] if pos_seq else head_pos, blines))
        elif slot == "syn":
            syn.extend(parse_syn(blines))
        elif slot == "ant":
            ant.extend(parse_ant(blines))
        elif slot == "deriv":
            deriv.extend(parse_deriv(blines))
        elif slot == "phrase":
            phrases.extend(parse_phrases(blines))
        elif slot == "examples":
            examples.extend(parse_example_block(blines))
        elif slot == "exam":
            flags.append("has_exam_block")

    senses = parse_senses(def_blocks)
    examples.extend(parse_def_examples(senses))

    # 去重
    seen = set()
    phrases = [p for p in phrases
               if not ((p["en"] or "").lower() in seen or seen.add((p["en"] or "").lower()))]
    seen = set()
    examples = [e for e in examples
                if not ((e["en"] or "").lower() in seen or seen.add((e["en"] or "").lower()))]

    if not chunk:
        flags.append("no_body")
    elif not senses:
        flags.append("no_senses")
    elif not any(CJK_RE.search(it) for s in senses for it in s["items"]):
        flags.append("no_chinese_in_senses")

    # 回溯校验
    raw_letters = letters_only(raw_chunk_text) if raw_chunk_text else ""
    for d in deriv:
        lw = letters_only(d["word"])
        if lw and lw not in raw_letters:
            flags.append("hallucinated_deriv")
            break
    for a in ant:
        if letters_only(a["word"]) not in raw_letters:
            flags.append("hallucinated_ant")
            break
    for s in syn:
        if letters_only(s) not in raw_letters:
            flags.append("hallucinated_syn")
            break
    if any(len(letters_only(x)) >= 14 and letters_only(x) not in KNOWN_WORDS for x in syn):
        flags.append("syn_glued")

    pos_all = []
    for p in ([head_pos] + pos_seq):
        if p and p not in pos_all:
            pos_all.append(p)
    pos = "/".join(pos_all) if pos_all else None

    entry = {
        "word": word,
        "phonetic": phon,
        "pos": pos,
        "section": section,
        "unit": unit,
        "pdf_pages": pages,
        "mnemonic": mnemonic,
        "senses": senses,
        "syn": syn,
        "ant": ant,
        "deriv": deriv,
        "phrases": phrases,
        "examples": examples,
        "ocr_confidence": None,
        "flags": flags,
    }
    entry["ocr_confidence"] = score_confidence(entry)
    return entry


def score_confidence(e):
    """可解释的扣分制：0.55 起始分。"""
    s = 0.55
    fl = e["flags"]
    if "no_body" in fl:
        return 0.0
    if "fuzzy_headword" not in fl and "glued_headword" not in fl:
        s += 0.10
    if e["phonetic"]:
        s += 0.06
    if e["senses"]:
        s += 0.10
        s += 0.04 * min(3, len(e["senses"]))
    if any(CJK_RE.search(it) for s in e["senses"] for it in s["items"]):
        s += 0.06
    if e["deriv"]:
        s += 0.03
    if e["phrases"]:
        s += 0.03
    if e["syn"] or e["ant"]:
        s += 0.02
    if e["mnemonic"]:
        s += 0.02
    for bad in ("fuzzy_headword", "no_senses", "no_chinese_in_senses",
                "hallucinated_deriv", "hallucinated_ant", "hallucinated_syn",
                "has_exam_block"):
        if bad in fl:
            s -= 0.12 if bad.startswith("hallucinated") else 0.06
    return round(max(0.05, min(0.95, s)), 2)


# ------------------------------------------------------------------ units.json

def build_units(entries, pages):
    """单元 → PDF 页区间。

    做法（对 444 页实测精度：56/56 单元与书上「本单元词汇」清单页吻合）：

    1. 统计每页命中每个单元词表的词数（词表来自一轮 all_entries_v2.json）。
    2. 按页顺序走指针 p：只有当下一页里 p+1 单元的命中数 ≥6 且明显高于 p 单元时
       才把指针推进一格——保证单调、不越级（正文里偶发出现后面单元的词，如 p27
       命中「必考词 20」4 个词，不是该单元的起点）。
    3. 页码里全零命中的「空页」（OCR 整页丢失，如 p357）默认归上一单元；但若它的
       下一页正好是新单元的起点，它其实是被 OCR 吃掉的清单页，改归新单元。
    4. 附录页（p406 起的「简单基础」/p414 起的两栏索引）用版式识别剔出，正文到
       p405 结束。
    """
    from collections import OrderedDict
    units = OrderedDict()
    for e in entries:
        units.setdefault((e["section"], e["unit"]), []).append(e["word"].lower())
    keys = [("必考词", u) for u in range(1, 27)] + [("基础词", u) for u in range(1, 31)]
    toks = {n: set(re.sub(r"[^a-z]", " ", t.lower()).split()) for n, t in pages.items()}
    hits = {k: {n: sum(1 for w in units.get(k, []) if w in tk) for n, tk in toks.items()}
            for k in keys}
    # 附录起点：页码 >400 且过半行以页码数字结尾（两栏索引）或出现「简单基础」
    appendix = max(pages)
    for n in sorted(pages):
        if n < 390:
            continue
        lines = [ln.strip() for ln in pages[n].splitlines() if ln.strip()]
        if not lines:
            continue
        idx_like = sum(1 for ln in lines if re.search(r"\s\d{1,3}$", ln))
        if idx_like >= 0.3 * len(lines) or "简单基础" in pages[n]:
            appendix = n
            break
    body_pages = [n for n in sorted(pages) if 9 <= n < appendix]

    assign = {}
    p = 0
    first = {}

    def is_list_page(txt: str) -> bool:
        """清单页：页首是 `Uni`/`Jni` 之类，或开头有「本单元词」。"""
        head = [ln.strip() for ln in txt.splitlines() if ln.strip()][:2]
        if head and re.match(r"^(Unit?|Uni|Un|Jni|Unl)\s*$", head[0]):
            return True
        return "单元" in txt[:300]

    for n in body_pages:
        while p + 1 < len(keys):
            cur_h, nxt_h = hits[keys[p]][n], hits[keys[p + 1]][n]
            if (nxt_h >= 6 and nxt_h > cur_h + 2) or \
                    (is_list_page(pages[n]) and nxt_h >= 3 and nxt_h > cur_h):
                p += 1
            else:
                break
        assign[n] = p
        first.setdefault(keys[p], n)
    # 空页修正：全零命中且下一页是新单元的起点 → 归新单元
    for k, n0 in list(first.items()):
        if k == keys[0]:
            continue
        prev_page = n0 - 1
        if prev_page in assign and assign[prev_page] == assign[n0] - 1:
            if all(hits[kk][prev_page] == 0 for kk in keys):
                first[k] = prev_page
                assign[prev_page] = assign[n0]

    out = {"必考词": [], "基础词": []}
    for i, k in enumerate(keys):
        start = first[k]
        end = (first[keys[i + 1]] - 1) if i + 1 < len(keys) else (appendix - 1)
        out[k[0]].append({"unit": k[1], "pdf_start": start, "pdf_end": end})
    return out


# ------------------------------------------------------------------ 主流程

def load_pages(limit=None):
    pages = {}
    for p in sorted(OCR_DIR.glob("page_*.txt")):
        n = int(re.search(r"(\d+)", p.name).group(1))
        if limit and n > limit:
            continue
        pages[n] = p.read_text(encoding="utf-8")
    return pages


def read_entries():
    return json.loads(ROUND1_JSON.read_text(encoding="utf-8"))


def assign_orphans(chunks, n_words):
    """把认不出词头的块，配给被跳过的词条。

    只在「两侧都匹配上、中间跳过的词数 == 中间孤立块数」时才配——相邻两个已
    匹配词把位置钉死了，这种配对几乎不可能错。否则保持 idx=None，写入
    unmatched.json 供人工看。
    """
    out = []
    i = 0
    while i < len(chunks):
        if chunks[i]["idx"] is not None:
            out.append(chunks[i])
            i += 1
            continue
        j = i
        while j < len(chunks) and chunks[j]["idx"] is None:
            j += 1
        run = chunks[i:j]
        prev_idx = out[-1]["idx"] if out else -1
        next_idx = chunks[j]["idx"] if j < len(chunks) else n_words
        if next_idx is not None and len(run) == next_idx - prev_idx - 1:
            for k, c in enumerate(run):
                c = dict(c)
                c["idx"] = prev_idx + 1 + k
                out.append(c)
        else:
            out.extend(run)
        i = j
    return out


def parse_all(limit=None):
    pages = load_pages(limit)
    r1 = read_entries()
    units_cfg = json.loads(UNITS_JSON.read_text(encoding="utf-8"))
    ranges = {}
    for sec, lst in units_cfg.items():
        for u in lst:
            ranges[(sec, u["unit"])] = (u["pdf_start"], u["pdf_end"])

    by_unit = {}
    for e in r1:
        by_unit.setdefault((e["section"], e["unit"]), []).append(e)

    KNOWN_WORDS.clear()
    KNOWN_WORDS.update(e["word"].lower() for e in r1)
    entries, unmatched = [], []
    for key in sorted(by_unit, key=lambda k: (k[0] != "必考词", k[1])):
        words = [e["word"].lower() for e in by_unit[key]]
        lo, hi = ranges.get(key, (1, max(pages)))
        plines = []
        for n in range(lo, hi + 1):
            if n not in pages:
                continue
            page_lines = [ln for ln in pages[n].splitlines()
                          if ln.strip() and not NOISE_RE.match(ln)]
            if n == lo and len(page_lines) > 20:
                # 清单页：先砍掉正文前的四栏预览词表，再清理右栏里残留的预览块
                k = find_body_start(page_lines)
                page_lines = strip_preview(page_lines[k:] if k else page_lines)
            plines.extend((n, ln) for ln in page_lines)
        chunks = assign_orphans(segment_unit(plines, words), len(words))
        by_idx = {}
        for c in chunks:
            if c["idx"] is not None:
                by_idx.setdefault(c["idx"], []).append(c)
        for i, r1e in enumerate(by_unit[key]):
            cs = by_idx.get(i, [])
            if len(cs) > 1:  # 同一个词被切了两段（多词性分条印）→ 合并
                merged = {"idx": i, "how": cs[0]["how"],
                          "lines": [ln for c in cs for ln in c["lines"]]}
                cs = [merged]
            chunk = cs[0] if cs else None
            raw = "\n".join(ln for _, ln in chunk["lines"]) if chunk else ""
            entries.append(assemble(r1e["word"], key[0], key[1], chunk, raw, words))
        for i, w in enumerate(words):
            if i not in by_idx:
                unmatched.append({"word": w, "section": key[0], "unit": key[1],
                                  "reason": "no_headword_found"})
        for c in chunks:
            if c["idx"] is None:
                unmatched.append({"word": None, "section": key[0], "unit": key[1],
                                  "reason": "orphan_block",
                                  "head_line": c["lines"][0][1][:80],
                                  "pdf_page": c["lines"][0][0]})
    return entries, unmatched


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--units", action="store_true", help="只重建 units.json")
    ap.add_argument("--limit-pages", type=int, default=None)
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--out-entries", default=str(DATA_DIR / "entries_r2.json"))
    ap.add_argument("--out-unmatched", default=str(DATA_DIR / "unmatched.json"))
    args = ap.parse_args(argv)

    if args.self_test:
        return run_self_test()

    if args.units:
        pages = load_pages()
        units = build_units(read_entries(), pages)
        UNITS_JSON.write_text(json.dumps(units, ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8")
        print(f"wrote {UNITS_JSON}")
        return 0

    entries, unmatched = parse_all(args.limit_pages)
    payload = {
        "meta": {
            "source": "2026 红宝书考研英语词汇",
            "pdf": "00-红宝书.pdf",
            "pages_ocr": len(load_pages()),
            "generated": _dt.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        },
        "entries": entries,
    }
    Path(args.out_entries).write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n",
                                      encoding="utf-8")
    Path(args.out_unmatched).write_text(json.dumps(unmatched, ensure_ascii=False, indent=1) + "\n",
                                        encoding="utf-8")
    print(f"entries={len(entries)} unmatched={len(unmatched)}")
    return 0


# ------------------------------------------------------------------ self-test

def run_self_test():
    KNOWN_WORDS.update(["reliable", "reliance", "unreliable", "relaxation"])
    words = ["straight", "strain", "strategy", "reliable", "reliance"]
    lines = [
        (40, "straight streit"),
        (40, "【词性】adj"),
        (40, "【词义】①直的，笔直的：The streets were～and narrow.这些"),
        (40, "街道笔直狭窄。"),
        (40, "【词组】①straight away/off立刻，马上"),
        (40, "②talk straight直言不讳③put things straight整顿局面"),
        (40, "strainstreim"),
        (40, "【助记】train（火车）前面放“s”，司机很strain（紧张）"),
        (40, "【词性】v"),
        (40, "【词义】①使紧张，尽力使用：～one'seyes瞪大眼晴看／，"),
        (40, "one'svoice扯着噪门叫"),
        (40, "【同义】①tension③injury"),
        (40, "【反义】relaxation n。松驰，缓和"),
        (40, "【派生】strained［streind】adj.紧张的；勉强的，不自然的"),
        (40, "strategy[straetod3i] n."),
        (40, "reliable[rr'laiobl] adj."),
        (40, "[词义]可靠的:It's not ~ to judge a man only by his clothes and"),
        (40, "appearance。单凭衣着和容貌来判断一个人是不可靠的。"),
        (40, "relanceTrilarens"),
        (40, "【词义】（on）依靠，依赖（u）：Long terms of ~ on sleeping pills"),
        (40, "is dangerous。长期依赖安眠药是危险的。"),
    ]
    chunks = segment_unit(lines, words)
    got = [words[c["idx"]] for c in chunks if c["idx"] is not None]
    assert got[:3] == ["straight", "strain", "strategy"], got
    assert "reliable" in got and "reliance" in got, got
    def raw_of(c):
        return "\n".join(ln for _, ln in c["lines"])

    strain = assemble("strain", "必考词", 1, chunks[1], raw_of(chunks[1]), words)
    assert strain["senses"] and strain["senses"][0]["items"], strain["senses"]
    assert strain["senses"][0]["items"][0].startswith("①使紧张"), strain["senses"]
    assert strain["syn"] == ["tension", "injury"], strain["syn"]
    assert strain["ant"][0]["word"] == "relaxation", strain["ant"]
    assert strain["deriv"][0]["word"] == "strained", strain["deriv"]
    assert strain["deriv"][0]["phonetic"] == "streind", strain["deriv"]
    straight = assemble("straight", "必考词", 1, chunks[0], raw_of(chunks[0]), words)
    assert straight["phrases"][0]["en"].startswith("straight away"), straight["phrases"]
    assert straight["senses"][0]["items"][0].startswith("①直的"), straight["senses"]
    assert "hallucinated_deriv" not in strain["flags"]
    rel = assemble("reliance", "必考词", 1, chunks[4], raw_of(chunks[4]), words)
    assert rel["flags"] and "fuzzy_headword" in rel["flags"], rel["flags"]
    print("self-test OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
