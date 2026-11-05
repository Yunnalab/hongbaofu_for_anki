#!/usr/bin/env python3
"""二轮词条的英文间�距修补。

OCR 在「中文 + 英文」混排行里常把英文单词粘成一坨（`oldkindrope`、`surpriseshockamaze`、
`contendwith sth`）。这里用词表 + DP 切分把它们拆回正常词形，只动英文 run，
中文与其它字段一律不碰。

用法:
    python3 round2/tools/repair_spacing.py --data round2/data/entries_r2.json [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import inflect  # noqa: E402

R1 = os.path.join(ROOT, "all_entries_v2.json")
EN_PDF = ("/home/cloudygirl/Study/考研/英语/英语红宝书26/"
          "[OCR]_00-红宝书_无文本层_20261104_1728.layered.pdf")

FUNCTION = set("""
a an the of to in on at for with from by as and or but if it is are was were be been being
not no nor that this these those his her its their our your my he she they we you i them us him
do does did done has have had having will would shall should can could may might must
there here who whom whose which what when where why how than then so such very more most much many
up out off over into about after before again all any some both each other another one two three
first last own same only just also even still yet well back down away through between among against
along across behind beyond toward towards under above below near beside besides except including
despite regarding according whereas while because though although unless until since whether either
neither per via upon during without within sth sb etc vs ie eg mr mrs dr st re
""".split())


KNOWN: set[str] = set()      # 只用于「这个词别动」的判定（宽松）
HEADWORDS: set[str] = set()  # 书上的 4292 个词条原形
TILDE_SUFFIX = re.compile(r"~[ \t]+(?=(?:s|es|ed|d|ing|er|est|ly|al|ion|ness|ment)\b)")

BASE_LEX: set[str] = set()


def load_lexicon() -> set[str]:
    """4292 词条 + 各词性变形 + 功能词；英文层词只补「干净且高频」的（去粘连垃圾）。"""
    lex: set[str] = set(FUNCTION)
    r1 = json.load(open(R1, encoding="utf-8"))
    for e in r1:
        w = (e.get("word") or "").lower()
        if not w:
            continue
        lex.add(w)
        HEADWORDS.add(w)
        for p in ("v", "n", "adj"):
            for value in inflect.forms(w, p).values():
                for piece in inflect.split_forms(value):
                    if len(piece) >= 2:
                        lex.add(piece.lower())
    if os.path.exists(EN_PDF):
        txt = subprocess.run(["pdftotext", "-layout", EN_PDF, "-"],
                             capture_output=True, text=True).stdout.lower()
        cnt = Counter(t for t in re.findall(r"[a-z][a-z'\-]{2,}", txt))
        KNOWN.update(cnt.keys())            # 英文层出现过的任何 token：绝不拿来拆
        BASE_LEX.update(lex)
        for word, n in cnt.items():
            if n < 10 or len(word) > 12:
                continue
            if word in lex:
                continue
            if split_token(word, BASE_LEX):     # 自己能拆 = 英文层也粘连了，别当词收
                continue
            lex.add(word)
    return lex


TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z'\-]*")
MIN_GLUE = 7          # 短于这个长度一律不拆（避免 a/the 之类误拆）
MAX_PARTS = 4


def split_token(token: str, lex: set[str]) -> list[str] | None:
    """把粘连 token 切成词表中的词；切不动返回 None。"""
    low = token.lower()
    if "-" in low or "'" in low:
        return None
    if low in lex or low in KNOWN or len(low) < MIN_GLUE:
        return None
    n = len(low)
    best: list[list[str]] | None = None

    def walk(pos: int, acc: list[str]) -> None:
        nonlocal best
        if best is not None and len(acc) >= len(best):
            return
        if pos == n:
            if len(acc) >= 2:
                best = list(acc)
            return
        if len(acc) >= MAX_PARTS - 1:
            return
        for end in range(n, pos + 1, -1):          # 贪长，先试长词
            piece = low[pos:end]
            if len(piece) < 2 or piece not in lex:
                continue
            if len(piece) < 4 and piece not in FUNCTION and piece not in HEADWORDS:
                continue        # 2–3 字母碎片只允许功能词或书上词条（old/new/day…）
            acc.append(piece)
            walk(end, acc)
            acc.pop()

    walk(0, [])
    if not best:
        return None
    # 至少一个功能词，或全部片段 ≥3 字母，才认为拆得靠谱
    # 高精度优先：必须含一个功能词，否则多半是把真词（fireflies）硬切
    if not any(p in FUNCTION for p in best):
        return None
    return list(best)


def repair_text(text: str, lex: set[str], stats: Counter) -> str:
    if not text:
        return text
    text = TILDE_SUFFIX.sub("~", text)                       # `~ ed` → `~ed`，`~ of` 不动
    text = re.sub(r"\b(sh|sth|sb)\s*\.", r"\1.", text)

    def repl(m: re.Match) -> str:
        token = m.group(0)
        pieces = split_token(token, lex)
        if not pieces:
            return token
        stats[f"split_{len(pieces)}"] += 1
        # 从原文按同样长度切片，保留大小写
        out, pos = [], 0
        for piece in pieces:
            out.append(token[pos:pos + len(piece)])
            pos += len(piece)
        return " ".join(out)

    return TOKEN_RE.sub(repl, text)


def repair_syn(syn: list[str], lex: set[str], stats: Counter) -> list[str]:
    out: list[str] = []
    for item in syn:
        item = item.strip().strip(",;")
        if not item:
            continue
        pieces = split_token(item, lex) if " " not in item else None
        if pieces:
            stats["syn_split"] += 1
            out.extend(pieces)
        else:
            out.append(item)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.path.join(ROOT, "round2/data/entries_r2.json"))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    lex = load_lexicon()
    print(f"词表规模: {len(lex)}")

    blob = json.load(open(args.data, encoding="utf-8"))
    entries = blob["entries"]
    stats: Counter = Counter()
    touched = 0

    for entry in entries:
        before = json.dumps(entry, ensure_ascii=False, sort_keys=True)

        for sense in entry.get("senses") or []:
            sense["items"] = [repair_text(t, lex, stats) for t in sense.get("items") or []]
        for ex in entry.get("examples") or []:
            ex["en"] = repair_text(ex.get("en"), lex, stats)
        for ph in entry.get("phrases") or []:
            ph["en"] = repair_text(ph.get("en"), lex, stats)
        if entry.get("syn"):
            entry["syn"] = repair_syn(entry["syn"], lex, stats)
        if entry.get("mnemonic"):
            entry["mnemonic"] = TILDE_SUFFIX.sub("~", entry["mnemonic"])

        if json.dumps(entry, ensure_ascii=False, sort_keys=True) != before:
            touched += 1

    print(f"改动词条: {touched}/{len(entries)}")
    print("切分统计:", dict(sorted(stats.items())))

    if args.dry_run:
        print("[dry-run] 未写回")
    else:
        bak = args.data + ".bak"
        shutil.copy2(args.data, bak)
        with open(args.data, "w", encoding="utf-8") as f:
            json.dump(blob, f, ensure_ascii=False, indent=1)
        print(f"已写回 {args.data}（备份 {os.path.basename(bak)}）")


if __name__ == "__main__":
    main()
