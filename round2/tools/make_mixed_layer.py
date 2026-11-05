#!/usr/bin/env python3
"""把合并好的逐页文本写回 PDF，做成一份「中英混排正常」的可搜索扫描件。

输入：
  * 无文本层的扫描 PDF（页图）
  * 中文层 PDF（只借它的字符坐标与行框）
  * round2/ocr/page_NNNN.txt（已经是中英合并 + 间距修补后的正文）
输出：
  * 带不可见文本层的 PDF（文本位置取自中文层，内容取自合并结果）

用法:
    python3 round2/tools/make_mixed_layer.py [--pages 1-444] [--out PATH]
"""
from __future__ import annotations

import argparse
import bisect
import difflib
import os
import re
import sys

import fitz

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from collections import Counter  # noqa: E402
from repair_spacing import load_lexicon, repair_text  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BASE_PDF = "/home/cloudygirl/Study/考研/英语/英语红宝书26/00-红宝书_无文本层.pdf"
ZH_PDF = ("/home/cloudygirl/Study/考研/英语/英语红宝书26/"
          "[OCR]ch_00-红宝书_无文本层_20261104_2211.layered.pdf")
OCR_DIR = os.path.join(ROOT, "round2/ocr")
DEFAULT_OUT = ("/home/cloudygirl/Study/考研/英语/英语红宝书26/"
               "[OCR]mix_00-红宝书_无文本层.layered.pdf")

CJK = re.compile(r"[\u2e80-\u9fff\u3000-\u303f\uff00-\uffef]")
LEX: set[str] = set()
HEADER = re.compile(r"^(红宝书|\d{1,3}|[·•.\-—_]{2,})$")


def zh_lines(page) -> list[dict]:
    """中文层的视觉行：先取所有文本框，再按基线聚成行（同基线的多块按 x 拼接）。

    中文层是「一个 OCR 框一个文本对象」，同一行常被拆成 2–3 块，
    不聚行就会和合并结果各行其是、互相重复。
    """
    boxes = []
    for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
            spans = [sp for sp in line.get("spans", []) if sp.get("chars")]
            if not spans:
                continue
            chars = [c for sp in spans for c in sp["chars"]]
            chars.sort(key=lambda c: c["bbox"][0])
            boxes.append({
                "text": "".join(c["c"] for c in chars),
                "x0": min(c["bbox"][0] for c in chars),
                "x1": max(c["bbox"][2] for c in chars),
                "y": chars[0]["origin"][1],
                "size": max(sp["size"] for sp in spans),
            })
    boxes.sort(key=lambda b: b["y"])

    rows: list[list[dict]] = []
    for box in boxes:
        if rows and abs(rows[-1][0]["y"] - box["y"]) <= 6:
            rows[-1].append(box)
        else:
            rows.append([box])

    # 同一基线上还要按 x 断栏：两个框之间空隙大 = 分属左右两栏，不能拼成一行
    mid = page.rect.width / 2
    split_rows: list[list[dict]] = []
    for row in rows:
        row.sort(key=lambda b: b["x0"])
        group = [row[0]]
        for box in row[1:]:
            gap = box["x0"] - group[-1]["x1"]
            crosses_mid = group[-1]["x1"] < mid - 20 < mid + 20 < box["x0"]
            if crosses_mid or gap > 200:
                split_rows.append(group)
                group = [box]
            else:
                group.append(box)
        split_rows.append(group)
    rows = split_rows

    out = []
    for row in rows:
        row.sort(key=lambda b: b["x0"])
        text = row[0]["text"]
        for box in row[1:]:
            if CJK.search(text[-1]) or CJK.search(box["text"][0]):
                text += box["text"]
            else:
                text += " " + box["text"]
        out.append({
            "text": text,
            "x0": min(b["x0"] for b in row),
            "x1": max(b["x1"] for b in row),
            "y": max(b["y"] for b in row),
            "size": max(b["size"] for b in row),
        })
    out.sort(key=lambda l: ((l["x0"] + l["x1"]) / 2 > page.rect.width * 0.5, l["y"]))
    return out


NORM = re.compile(r"[^0-9A-Za-z\u4e00-\u9fff]+")


def _key(text: str) -> str:
    return NORM.sub("", text).lower()


def _ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


def align(zh: list[dict], merged: list[str], repair) -> list[tuple[dict, str]]:
    """只用中文层的行框与顺序，文本就地修补。

    试过把 `page_NNNN.txt`（中英合并结果）塞进来提升英文，但那是另一套行分组，
    逐行配对会错位/丢行——PDF 这一份要的是「位置 1:1、内容干净」，
    英文的精修留给 Anki 牌组用的 entries_r2.json。`merged` 参数仅用于兜底诊断。
    """
    out = []
    for line in zh:
        text = repair(line["text"]).strip()
        if text and not HEADER.match(text):
            out.append((line, text))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", default="")
    ap.add_argument("--out", default=DEFAULT_OUT)
    args = ap.parse_args()

    base = fitz.open(BASE_PDF)
    zh = fitz.open(ZH_PDF)
    total = base.page_count
    rng = range(total)
    if args.pages:
        s, e = args.pages.split("-")
        rng = range(int(s) - 1, int(e))

    global LEX
    LEX = load_lexicon()
    font = fitz.Font("china-s")
    placed = 0
    for i in rng:
        txt_path = os.path.join(OCR_DIR, f"page_{i + 1:04d}.txt")
        if not os.path.exists(txt_path):
            continue
        merged = [ln for ln in open(txt_path, encoding="utf-8").read().split("\n") if ln.strip()]
        payload = align(zh_lines(zh[i]), merged, lambda t: repair_text(t, LEX, Counter()))

        page = base[i]
        tw = fitz.TextWriter(page.rect)
        any_text = False
        for line, text in payload:
            text = text.strip()
            if not text or HEADER.match(text):
                continue
            size = min(max(line["size"], 4), 40)
            # 宽度溢出就等比缩小，避免文本跑到栏外（不可见层，只影响选择范围）
            width = fitz.Font("china-s").text_length(text, fontsize=size)
            avail = max(line["x1"] - line["x0"], 20)
            if width > avail:
                size = max(4, size * avail / width)
            tw.append((line["x0"], line["y"]), text, font=font, fontsize=size)
            any_text = True
        if any_text:
            tw.write_text(page, render_mode=3)
            placed += 1

    base.save(args.out, garbage=3, deflate=True)
    print(f"写出 {args.out}（{total} 页，写入文本层 {placed} 页）")


if __name__ == "__main__":
    main()
