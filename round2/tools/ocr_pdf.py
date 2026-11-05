#!/usr/bin/env python3
"""扫描版 PDF -> 逐页 OCR 文本（双栏切分 + 中英双语言 TSV 合并）。

用法::

    # 全量（默认 444 页，12 并发）
    python3 round2/tools/ocr_pdf.py ocr --pages 1-444 --jobs 12

    # 试点 + 保存切栏图供人工核对
    python3 round2/tools/ocr_pdf.py ocr --pages 9-36 --jobs 8 --keep /tmp/r2/pilot

    # 由已 OCR 的页文本推导 56 个单元的 PDF 页区间
    python3 round2/tools/ocr_pdf.py units --entries all_entries_v2.json

流程（每页）：
  1. `pdfimages -j` 直接抽内嵌扫描图（比 pdftoppm 渲染快两个数量级，且保留
     原始像素）；抽不到位图时退回 `pdftoppm -r 300`。
  2. 栏切点用像素投影确定：正文条带的墨迹密度做 ±1.2% 页宽的滑窗平滑
     （避免「字间隙假白缝」），在中央 0.35–0.66 区间取最小；
     该处密度 < 0.10 判为双栏，否则按单栏整页识别。不做 50% 硬编码。
  3. 单元首页（单词勾选清单，5 列网格）单独处理：检测顶部横线（横贯页宽
     的实线）与网格条带数，把「清单块」整幅横向识别，正文块再双栏切。
  4. 每个区域跑两次 tesseract：`-l chi_sim` 与 `-l eng`，各出 TSV；
     按 bbox 把同一位置的汉字 token 与拉丁 token 对齐，重叠时保留置
     信度高的那个 —— 汉字取 chi_sim 结果（准），英文取 eng 结果（准），
     避免 `chi_sim+eng` 双模型互相抢词造成的乱码。
  5. 左栏在前、右栏在后拼接；丢页眉（红宝书 / 考研英语词汇）与页码行。
  6. 已存在且非空的 page_XXXX.txt 直接跳过（断点续跑）；输出先写 .tmp 再
     rename；临时图用完即删。

依赖：标准库 + PIL + 外部命令 pdfimages / pdftoppm / tesseract。
tesseract 数据目录：默认取 $TESSDATA_PREFIX，若 /tmp/r2/tessdata_best 存在
则优先用它（tessdata_best 的 chi_sim/eng 比 tessdata_fast 明显更准）。下载：
    curl -O https://raw.githubusercontent.com/tesseract-ocr/tessdata_best/main/chi_sim.traineddata
    curl -O https://raw.githubusercontent.com/tesseract-ocr/tessdata_best/main/eng.traineddata
"""

import argparse
import concurrent.futures
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from PIL import Image

# ------------------------------------------------------------------ 默认参数
DEFAULT_PDF = "/home/cloudygirl/Study/考研/英语/英语红宝书26/00-红宝书.pdf"
DEFAULT_OUT = "round2/ocr"
INK_THR = 150           # 灰度 < 此值视为墨迹
PSM = "6"               # 每栏视为一个均匀文本块
FALLBACK_DPI = 300
BODY_TOP = 0.32         # 求栏切点用的正文条带上界
BODY_BOT = 0.97
CENTER_LO, CENTER_HI = 0.35, 0.66
SMOOTH = 0.012          # 滑窗半宽（页宽比例）
TWO_COL_MAX = 0.10      # 切点墨迹密度 < 此值 -> 双栏
COL_PAD = 6             # 每栏左右留白像素
RULE_RANGE = (0.15, 0.42)   # 单元首页清单块下沿那条横线所在高度范围
GRID_MIN_BANDS = 4      # 清单块里至少几列才认为是网格
CJK_RE = re.compile(r"[\u2e80-\u9fff\uf900-\ufaff\u3000-\u303f\uff00-\uffef]")
LATIN_RE = re.compile(r"[A-Za-z0-9]")
PAGE_NO_RE = re.compile(r"^[\s·•.。\-—_*\\/|()（）\[\]]*\d{1,3}[\s·•。\-—_*\\/|()（）\[\]]*$")
HEADER_WORDS = ("红宝书", "考研英语词汇")
NOISE_LINE_RE = re.compile(r"^[\s\W_]{0,12}$")


# ------------------------------------------------------------------ 环境
def tesseract_bin():
    env = os.environ.get("TESSERACT")
    if env and os.path.exists(env):
        return env
    for cand in ("/tmp/r2/tessbin/bin/tesseract", "/tmp/r2/tessbin2/bin/tesseract",
                 "/tmp/r2/tessbin3/bin/tesseract"):
        if os.path.exists(cand):
            return cand
    for cand in sorted(glob.glob("/nix/store/*-tesseract-*/bin/tesseract"), reverse=True):
        if os.access(cand, os.X_OK):
            return cand
    found = shutil.which("tesseract")
    if found:
        return found
    raise SystemExit("找不到 tesseract；请设 TESSERACT=/path/to/tesseract")


def tessdata_dir():
    env = os.environ.get("TESSDATA_PREFIX")
    if env and os.path.isdir(env):
        return env
    for cand in ("/tmp/r2/tessdata_best", "/tmp/r2/tessdata"):
        if os.path.isdir(cand):
            return cand
    return ""


# ------------------------------------------------------------------ 图像分析
def load_gray(path):
    return Image.open(path).convert("L")


def ink_profile(img, axis):
    """墨迹投影：返回每个 x（或 y）上墨迹像素占该列（行）的比例。"""
    mask = img.point(lambda v: 255 if v < INK_THR else 0)
    w, h = mask.size
    small = mask.resize((w, 1), Image.BOX) if axis == "x" else mask.resize((1, h), Image.BOX)
    return [v / 255.0 for v in small.get_flattened_data()]


def find_gutter(img, top=BODY_TOP):
    """双栏切点。返回 (x, 密度)；单栏页返回 (None, 密度)。"""
    w, h = img.size
    band = img.crop((0, int(h * top), w, int(h * BODY_BOT)))
    prof = ink_profile(band, "x")
    half = max(4, int(w * SMOOTH))
    cs = [0.0]
    for v in prof:
        cs.append(cs[-1] + v)
    best = None
    for x in range(int(w * CENTER_LO), int(w * CENTER_HI)):
        s = cs[min(x + half, len(prof))] - cs[max(0, x - half)]
        if best is None or s < best[1]:
            best = (x, s)
    x, s = best
    dens = s / (2 * half)
    return (x if dens < TWO_COL_MAX else None), dens


def find_rule(img, lo, hi, frac=0.5):
    """找一条横贯页宽的实线（返回其 y 比例），没有则 None。"""
    w, h = img.size
    mask = img.point(lambda v: 255 if v < INK_THR else 0)
    sw, sh = max(1, w // 8), max(1, h // 8)
    data = list(mask.resize((sw, sh), Image.BOX).get_flattened_data())
    hits = []
    for y in range(int(sh * lo), int(sh * hi)):
        row = data[y * sw:(y + 1) * sw]
        best = cur = 0
        for v in row:
            if v > 50:
                cur += 1
                best = max(best, cur)
            else:
                cur = 0
        if best >= frac * sw:
            hits.append(y)
    if not hits:
        return None
    return hits[len(hits) // 2] / sh


def count_bands(img):
    """竖直方向上的文字带数量（用于识别 5 列网格）。"""
    w, h = img.size
    prof = ink_profile(img, "x")
    half = max(3, int(w * 0.006))
    thr = 0.03
    bands, run = 0, None
    for i in range(w):
        v = sum(prof[max(0, i - half):i + half + 1]) / (2 * half + 1)
        if v > thr:
            if run is None:
                run = i
        else:
            if run is not None and i - run >= int(w * 0.02):
                bands += 1
            run = None
    if run is not None and w - run >= int(w * 0.02):
        bands += 1
    return bands


def plan_regions(img):
    """返回 [(crop, 说明)]，按阅读顺序。"""
    w, h = img.size
    grid_bottom = None
    rule = find_rule(img, *RULE_RANGE)
    if rule is not None:
        top_strip = img.crop((0, int(h * 0.05), w, int(h * rule)))
        if count_bands(top_strip) >= GRID_MIN_BANDS:
            grid_bottom = int(h * rule) + max(4, int(h * 0.006))
    if grid_bottom and grid_bottom < h * 0.55:
        gutter, _ = find_gutter(img.crop((0, grid_bottom, w, h)), top=0.0)
        head = img.crop((0, 0, w, grid_bottom))
        body = img.crop((0, grid_bottom, w, h))
        if gutter:
            return [(head, "grid"), (body.crop((0, 0, min(w, gutter + COL_PAD), h - grid_bottom)), "col0"),
                    (body.crop((max(0, gutter - COL_PAD), 0, w, h - grid_bottom)), "col1")]
        return [(head, "grid"), (body, "full")]
    gutter, _ = find_gutter(img)
    if gutter:
        return [(img.crop((0, 0, min(w, gutter + COL_PAD), h)), "col0"),
                (img.crop((max(0, gutter - COL_PAD), 0, w, h)), "col1")]
    return [(img, "full")]


# ------------------------------------------------------------------ tesseract
def ocr_tsv(path, lang, psm=PSM):
    base = path + "." + lang.replace("+", "_")
    cmd = [tesseract_bin(), path, base, "-l", lang, "--psm", str(psm), "tsv"]
    env = dict(os.environ)
    td = tessdata_dir()
    if td:
        env["TESSDATA_PREFIX"] = td
    res = subprocess.run(cmd, capture_output=True, text=True, env=env)
    tsv = base + ".tsv"
    if res.returncode != 0 or not os.path.exists(tsv):
        raise RuntimeError(f"tesseract 失败({lang}): {res.stderr.strip()[:300]}")
    toks = []
    with open(tsv, encoding="utf-8") as f:
        f.readline()
        for line in f:
            p = line.rstrip("\n").split("\t")
            if len(p) < 12 or p[0] != "5":
                continue
            txt = p[11].strip()
            if not txt:
                continue
            x0, y0, bw, bh = int(p[6]), int(p[7]), int(p[8]), int(p[9])
            toks.append({"t": txt, "x0": x0, "x1": x0 + bw, "y0": y0, "y1": y0 + bh,
                         "cy": y0 + bh / 2, "h": bh,
                         "conf": float(p[10]) if p[10] else 0.0})
    return toks


def merge_tsv(zh, en):
    """汉字 token 取 chi_sim、拉丁 token 取 eng，重叠处按置信度取舍。"""
    zh = [t for t in zh if CJK_RE.search(t["t"])]
    en = [t for t in en if not CJK_RE.search(t["t"]) and LATIN_RE.search(t["t"])]
    if not zh and not en:
        return []
    toks = [dict(t, src="zh") for t in zh] + [dict(t, src="en") for t in en]
    hs = sorted(t["h"] for t in toks)
    mh = hs[len(hs) // 2]
    toks.sort(key=lambda t: t["cy"])
    groups, cur = [], [toks[0]]
    for t in toks[1:]:
        if t["cy"] - cur[-1]["cy"] <= mh * 0.45:
            cur.append(t)
        else:
            groups.append(cur)
            cur = [t]
    groups.append(cur)
    lines = []
    for ln in groups:
        cand = list(ln)
        flag = [True] * len(cand)
        for i in range(len(cand)):
            for j in range(i + 1, len(cand)):
                a, b = cand[i], cand[j]
                if a["src"] == b["src"]:
                    continue
                ov = min(a["x1"], b["x1"]) - max(a["x0"], b["x0"])
                wmin = min(a["x1"] - a["x0"], b["x1"] - b["x0"])
                if ov > 0.4 * max(1, wmin):
                    if a["conf"] >= b["conf"]:
                        flag[j] = False
                    else:
                        flag[i] = False
        kept = sorted([t for t, k in zip(cand, flag) if k], key=lambda t: t["x0"])
        s, prev = "", None
        for t in kept:
            if prev is not None:
                if prev["src"] == "en" and t["src"] == "en":
                    if t["x0"] - prev["x1"] > -0.35 * prev["h"]:
                        s += " "
                elif prev["src"] != t["src"]:
                    s += " "
            s += t["t"]
            prev = t
        lines.append((min(t["cy"] for t in ln), s))
    lines.sort()
    return [txt for _, txt in lines]


# ------------------------------------------------------------------ 文本清理
def clean_text(lines):
    out = []
    for line in lines:
        line = line.replace("\u3000", " ").rstrip()
        line = re.sub(r"[ \t]{2,}", " ", line)
        s = line.strip()
        if not s:
            continue
        if PAGE_NO_RE.match(s):
            continue
        if any(hw in s for hw in HEADER_WORDS) and len(s) <= 30:
            continue
        if NOISE_LINE_RE.match(s):     # 只剩符号的碎片行
            continue
        out.append(line)
    return "\n".join(out)


# ------------------------------------------------------------------ 抽图 / 单页
def extract_page_image(pdf, page, tmpdir, dpi=FALLBACK_DPI):
    prefix = os.path.join(tmpdir, "p")
    subprocess.run(["pdfimages", "-f", str(page), "-l", str(page), "-j", "-p", pdf, prefix],
                   check=True, capture_output=True)
    cands = []
    for name in os.listdir(tmpdir):
        if name.startswith("p-") and name.lower().endswith((".jpg", ".jpeg", ".ppm", ".png", ".tif")):
            p = os.path.join(tmpdir, name)
            cands.append((os.path.getsize(p), p))
    if cands:
        cands.sort(reverse=True)
        return cands[0][1]
    out = os.path.join(tmpdir, "render")
    subprocess.run(["pdftoppm", "-f", str(page), "-l", str(page), "-r", str(dpi),
                    "-gray", "-png", "-singlefile", pdf, out], check=True, capture_output=True)
    return out + ".png"


def ocr_page_regions(img, tmpdir):
    lines = []
    for i, (crop, kind) in enumerate(plan_regions(img)):
        path = os.path.join(tmpdir, "r%d.png" % i)
        crop.save(path)
        zh = ocr_tsv(path, "chi_sim")
        en = ocr_tsv(path, "eng")
        lines.extend(merge_tsv(zh, en))
        os.unlink(path)
        try:
            os.unlink(path + ".chi_sim.tsv")
            os.unlink(path + ".eng.tsv")
        except OSError:
            pass
    return lines


def ocr_one_page(pdf, page, out_dir, force=False, keep=None, dpi=FALLBACK_DPI):
    out_path = Path(out_dir) / f"page_{page:04d}.txt"
    if out_path.exists() and out_path.stat().st_size > 0 and not force:
        return {"page": page, "status": "skip", "secs": 0.0}
    t0 = time.time()
    try:
        with tempfile.TemporaryDirectory(prefix=f"ocr{page}_") as tmp:
            img = load_gray(extract_page_image(pdf, page, tmp, dpi=dpi))
            regions = plan_regions(img)
            if keep:
                Path(keep).mkdir(parents=True, exist_ok=True)
                for i, (crop, kind) in enumerate(regions):
                    crop.save(Path(keep) / f"page_{page:04d}_{i}_{kind}.png")
            lines = ocr_page_regions(img, tmp)
    except Exception as exc:  # noqa: BLE001
        return {"page": page, "status": "error", "secs": time.time() - t0,
                "error": f"{type(exc).__name__}: {exc}"}
    text = clean_text(lines)
    secs = time.time() - t0
    chars = len(re.sub(r"\s", "", text))
    tmp_path = out_path.with_suffix(".txt.tmp")
    tmp_path.write_text(text + "\n", encoding="utf-8")
    os.replace(tmp_path, out_path)
    return {"page": page, "status": "ok" if chars >= 20 else "empty",
            "secs": secs, "chars": chars, "regions": [k for _, k in regions]}


# ------------------------------------------------------------------ 命令
def pdf_page_count(pdf):
    res = subprocess.run(["pdfinfo", pdf], capture_output=True, text=True, check=True)
    for line in res.stdout.splitlines():
        if line.startswith("Pages:"):
            return int(line.split()[1])
    raise SystemExit("无法获取 PDF 页数")


def parse_pages(spec, total):
    pages = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            pages.extend(range(int(a), int(b) + 1))
        else:
            pages.append(int(part))
    return [p for p in pages if 1 <= p <= total]


def cmd_ocr(args):
    total = pdf_page_count(args.pdf)
    pages = parse_pages(args.pages, total)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    print(f"[ocr] {len(pages)} 页 -> {out_dir}  jobs={args.jobs} "
          f"psm={PSM} tessdata={tessdata_dir()}", file=sys.stderr)
    results = []
    if args.jobs <= 1:
        for p in pages:
            r = ocr_one_page(args.pdf, p, out_dir, args.force, args.keep, args.dpi)
            results.append(r)
            print(f"  p{p:04d} {r['status']} {r.get('secs', 0):.1f}s {r.get('chars', '')}",
                  file=sys.stderr)
    else:
        with concurrent.futures.ProcessPoolExecutor(max_workers=args.jobs) as ex:
            futs = [ex.submit(ocr_one_page, args.pdf, p, out_dir, args.force,
                              args.keep, args.dpi) for p in pages]
            done = 0
            for fut in concurrent.futures.as_completed(futs):
                r = fut.result()
                results.append(r)
                done += 1
                if r["status"] != "skip" and (done % 25 == 0 or r["status"] != "ok"):
                    print(f"  [{done}/{len(pages)}] p{r['page']:04d} {r['status']} "
                          f"{r.get('secs', 0):.1f}s", file=sys.stderr)
    wall = time.time() - t0
    ran = [r for r in results if r["status"] != "skip"]
    ok = [r for r in ran if r["status"] == "ok"]
    empty = sorted(r["page"] for r in ran if r["status"] == "empty")
    err = [(r["page"], r.get("error", "")) for r in ran if r["status"] == "error"]
    avg = sum(r["secs"] for r in ran) / len(ran) if ran else 0.0
    grid = sorted(r["page"] for r in ok if "grid" in (r.get("regions") or []))
    summary = {"pages_requested": len(pages), "ocr_ok": len(ok),
               "skipped": len(results) - len(ran), "empty": empty,
               "errors": [{"page": p, "error": e} for p, e in err],
               "grid_pages": grid,
               "avg_secs_per_page": round(avg, 2), "wall_secs": round(wall, 1)}
    (out_dir / "_ocr_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[ocr] ok={len(ok)} skip={summary['skipped']} empty={len(empty)} "
          f"err={len(err)} avg={avg:.2f}s/页 wall={wall:.1f}s", file=sys.stderr)
    if grid:
        print(f"[ocr] 清单页(单元首页): {grid}", file=sys.stderr)
    if empty:
        print(f"[ocr] 空页: {empty}", file=sys.stderr)
    for p, e in err:
        print(f"[ocr] 错误 p{p}: {e}", file=sys.stderr)
    return 0


UNIT_LINE_RE = re.compile(r"^\s*Unit\s*(\d{1,2})\s*$", re.I)
UNIT_ANY_RE = re.compile(r"Unit\s*(\d{1,2})", re.I)


def cmd_units(args):
    """由 OCR 页文本 + 一轮词表推导 56 个单元的 PDF 页区间。"""
    ocr_dir = Path(args.out)
    pages = {}
    for f in sorted(ocr_dir.glob("page_*.txt")):
        pages[int(f.stem.split("_")[1])] = f.read_text(encoding="utf-8")
    entries = json.loads(Path(args.entries).read_text(encoding="utf-8"))
    order = {}
    for e in entries:
        order.setdefault((e["section"], e["unit"]), []).append(e["word"].lower())

    # 1) "Unit N" 独占一行 = 单元首页
    starts = []
    for num in sorted(pages):
        for line in pages[num].splitlines():
            m = UNIT_LINE_RE.match(line.strip())
            if m:
                starts.append((num, int(m.group(1))))
                break
    # 2) 章节分界：正文里出现「基础词」大标题
    section_pages = {"必考词": None, "基础词": None}
    for num in sorted(pages):
        txt = pages[num]
        if "基础词" in txt and "必考词" not in txt and section_pages["基础词"] is None:
            section_pages["基础词"] = num
        if "必考词" in txt and section_pages["必考词"] is None:
            section_pages["必考词"] = num
    print("[units] Unit 标题页:", starts, file=sys.stderr)
    print("[units] 章节出现页:", section_pages, file=sys.stderr)
    if not starts:
        raise SystemExit("没有找到任何 'Unit N' 标题行，无法定位单元（需人工处理）")

    # 3) 用「单元首词出现在页文本」校验并修正每个起点
    def first_words_ok(page, unit, section, n=3):
        txt = pages.get(page, "").lower()
        words = order.get((section, unit), [])[:n]
        return sum(1 for w in words if w in txt)

    first_S = starts[0][1]
    result = {"必考词": [], "基础词": []}
    cur_section = "必考词"
    prev_end = None
    for i, (page, unit) in enumerate(starts):
        end = starts[i + 1][0] - 1 if i + 1 < len(starts) else max(pages)
        section = "必考词"
        if section_pages["基础词"] and page >= section_pages["基础词"] and unit <= 30:
            # 基础词 的 Unit 1 会重新从 1 编号
            if i > 0 and starts[i - 1][1] == 26 and unit == 1:
                section = "基础词"
            elif unit <= starts[i][1] and section_pages["基础词"] and page > section_pages["基础词"]:
                section = "基础词"
        if page >= (section_pages["基础词"] or 10 ** 9):
            section = "基础词"
        result[section].append({"unit": unit, "pdf_start": page, "pdf_end": end,
                                "hit": first_words_ok(page, unit, section)})
        prev_end = end
    print("[units] 检出 %d 个单元起点" % len(starts), file=sys.stderr)
    print(json.dumps(result, ensure_ascii=False, indent=1))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")
    o = sub.add_parser("ocr", help="OCR 指定页范围")
    o.add_argument("--pdf", default=DEFAULT_PDF)
    o.add_argument("--out", default=DEFAULT_OUT)
    o.add_argument("--pages", default="1-444")
    o.add_argument("--jobs", type=int, default=12)
    o.add_argument("--dpi", type=int, default=FALLBACK_DPI)
    o.add_argument("--keep", default=None, help="保存每个识别区域的图（调试用）")
    o.add_argument("--force", action="store_true")
    o.set_defaults(func=cmd_ocr)
    u = sub.add_parser("units", help="由页文本推导单元区间")
    u.add_argument("--out", default=DEFAULT_OUT)
    u.add_argument("--entries", default="all_entries_v2.json")
    u.set_defaults(func=cmd_units)
    args = ap.parse_args(argv)
    if not getattr(args, "func", None):
        ap.print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
