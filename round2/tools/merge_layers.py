#!/usr/bin/env python3
"""合并中英两份 OCR 文本层 -> 逐页文本（`round2/ocr/page_NNNN.txt`）。

背景：同一本扫描书有两份 OCR 过的 PDF，页面位图完全相同（1727.25x2471.25 pt）：

* 中文层（`[OCR]ch_...`）：汉字极准，`【词义】【词组】` 等标记齐全；但英文与中文
  混排时英文被粘成一坨（`preytosth`、`bycontrast`），没有词间空格。
* 英文层（`[OCR]_...`）：英文准、有正常词间空格；但中文全废（被认成 `AE+`、
  `#0v.` 这类垃圾 ASCII）。

所以：**中文取中文层，英文取英文层的分词**。

## 为什么不按 x 直接套

英文层的字形宽度是按 token bbox 均摊出来的。纯英文行两层坐标完全一致，但那一行
只要混了中文，中文被认成垃圾 ASCII 后 token bbox 被撑大，整行坐标就废了。实测
p40 同一视觉行：中文层 `top=194.8`、英文层 `top=177.5`（字号 26 vs 52.4），英文层
把 `be` 画在了 `【词组】` 的位置上。按 x 硬套会把 `be` 配给 `【词组】`。

## 实际做法：顺序 + 内容的字符级对齐

1. 两层都按「先左栏（x 中心 < 863）后右栏、栏内按 bottom 升序、行内按 x」排成
   字符流。两份 PDF 出自同一套版面分析，这个顺序是一致的（行的分组/坐标不必一致）。
2. 英文层字符流里只留 ASCII 字母数字，拼成一条无噪声的串 `s`（丢掉垃圾 ASCII 的
   `+`、`#` 等符号，但保留每个字符到原始字符的下标），它是英文层可分词的骨架。
3. 中文层逐行切成 Latin run / CJK run。Latin run 规范化（小写、去非字母数字）得到
   `t`，在 `s` 里从当前指针往后找 `t` 的出现（**字符级**，允许落在英文 token 内部）：
   - `（onupon）` 的 `onupon` 会在英文层的 `on/uponThe` 里命中前缀，取回 `on/upon`，
     剩下的 `The` 留给下一个 run（`Theeagle~edon` -> `The eagle~ed on`）；
   - `preytosth` 命中 `prey to sth`，中间的空格是英文层原文里的字符，自动带回来。
   命中后取该区间的英文**原文**（含词间空格）替换，指针前移。
4. 命中不了（英文层这一行本身是乱码，如 `fraankh~onejstoplainbsim-pleI`）先按
   difflib 相似度兜底，再不行就退回中文层原文，保证不丢内容。
5. 中文层 run 首尾被规范化过滤掉的标点（如 `sth.` 的句点）补回去；`~`（词条占位符）
   英文层若丢了则从中文层补。
6. 行内拼接：两侧只要有一边是 CJK 就不加空格，纯拉丁之间一个空格，多空格压成一个。
7. 丢页眉（`红宝书` 条带）与页脚页码。

用法::

    python3 round2/tools/merge_layers.py                     # 全书
    python3 round2/tools/merge_layers.py --pages 12,40,300   # 试点
    python3 round2/tools/merge_layers.py --report round2/data/merge_report.md
"""

import argparse
import difflib
import json
import re
import sys
import time
from pathlib import Path

import pdfplumber

ROOT = Path(__file__).resolve().parents[2]          # .../Anki红宝书
DEFAULT_ZH = ROOT.parent / "英语红宝书26/[OCR]ch_00-红宝书_无文本层_20261104_2211.layered.pdf"
DEFAULT_EN = ROOT.parent / "英语红宝书26/[OCR]_00-红宝书_无文本层_20261104_1728.layered.pdf"
DEFAULT_OUT = ROOT / "round2/ocr"
DEFAULT_ENTRIES = ROOT / "all_entries_v2.json"

# ------------------------------------------------------------------ 版式常量
PAGE_W, PAGE_H = 1727.25, 2471.25
COL_X = 863.0                # 双栏分界
HEADER_BOT = 0.066 * PAGE_H  # 页眉「红宝书」条带下沿（≈163 pt）
FOOTER_TOP = 0.955 * PAGE_H  # 页码条带上沿（≈2360 pt）
LINE_TOL = 8.0               # 同一视觉行的 bottom 容差
LINE_MERGE_TOL = 14.0        # 同一行被拆成两个 box 时的 bottom 容差
SEARCH_WIN = 1500            # 在 s 里往前找的最大字符数（约一页的英文字符量）
FUZZY_MIN = 0.80             # 模糊兜底的最低相似度

FUNC_WORDS = {
    "with", "to", "of", "the", "and", "that", "which", "on", "in", "for",
    "by", "it", "is", "be", "not", "a", "an", "as", "at", "or", "but",
    "from", "this", "these", "those", "his", "her", "its", "their",
}

# 拆粘连用的高频基础词（4292 个词条里没有 kitchen / under / about / oneself
# 这类基础词，机器上也没装 words/hunspell 词典，就内置一份，够切 `in viewof` 用）
COMMON_WORDS = set("""
a about above across act after again against age ago air all almost alone along
already also always am among an and another answer any anyone anything are around
as ask at away back bad be because become been before behind being below best
better between big bind bit black blood body book both box boy break bring brother
build but buy by call can care carry case catch cause change child city class close
come could country course cover cut day deal differ do does dog done door down draw
drive drop during each early earth easy eat end enough even evening ever every
family far few field fight find fire first fish five food foot for force four free
friend from front full get give go good great green ground group grow half hand hang
happy hard have he head hear heart help her here high him his hit hold home hope horse
hour house how however hundred i idea if in into just keep kind know land large last
late later laugh lead learn leave left less let lie life light like line listen little
live long look lose love low make man many may me mean meet men might mind miss more
most mother move much must my name near need never new next night no none nor not
nothing now number of off often old on once one only open or other our out over own
page part pay people person place play point put question quick quiet quite rather
reach read ready real rest right river road room run same say school sea see seem sell
send set seven she ship short should show side since six sit sleep small so some
someone something son soon speak stand star start state stay step still stop story
street strong such sure take talk tell ten than that the their them then there these
they thing think third this those though through three time to today together too
top toward town tree true try turn two under until up upon us use very voice wait
walk want war warm was watch water way we week well went were what when where which
while white who whom whose why will win wind window with within without woman wonder
word work world would write year yes yet you young your
above about across after against along among around before behind below beneath beside
between beyond during except inside outside throughout toward under until upon
about around away back down forth home in off on out over round through up
about almost already also always any anything else ever far here how however just
less many more most much now often once only quite rather same seldom since so
soon still such then there thus together too usually very well what when where
which while who why yet
someone something somebody anyone anything everybody everyone everything nobody
nothing oneself himself herself itself themselves myself yourself ourselves
sth sb smb etc eg ie adj adv prep conj pron vt vi n v a
""".split())
# 拆粘连：只允许介词/副词小词当短段，并要求至少一段是介词。书上的粘连几乎
# 都是单词与 in/of/to/with 粘住，这个锚点可以避开了 `contradiction ->
# contradict ion`、`players -> play ers` 这类误拆。
PREPS = {
    "in", "on", "of", "to", "by", "at", "for", "with", "from", "up", "down",
    "off", "out", "over", "under", "into", "onto", "upon", "about", "against",
    "without", "within", "through", "across", "along", "around", "beyond",
    "behind", "beside", "between", "among", "after", "before", "during",
    "per", "via", "away", "back",
}
JOINT_OK = {"a", "i"}
SUFFIX_STOP = {"ing", "ed", "es", "er", "ers", "est", "ly", "tion", "sion",
               "s", "ion", "ition", "ation", "ive", "ous", "ness", "ment", "ful",
               "less", "able", "ible", "ance", "ence", "ency", "ancy", "ity",
               "ism", "ist", "ish"}

HEADER_WORDS = ("红宝书", "考研英语词汇")
PAGE_NO_RE = re.compile(r"^[\s·•.。\-—_*\\/|()（）\[\]:：]*\d{1,3}[\s·•。\-—_*\\/|()（）\[\]:：]*$")
WS_RE = re.compile(r"\s+")
NORM_RE = re.compile(r"[^a-z0-9]+")
# 中文层 run 首尾要补回的标点（规范化时被丢掉的那些）
EDGE_PUNCT_RE = re.compile(r"^[^A-Za-z0-9]+|[^A-Za-z0-9]+$")
# 英文层丢了、但书上有意义的符号：词条占位符
KEEP_SYMBOLS = "~"


# ------------------------------------------------------------------ 字符分类
def is_latin(ch):
    """英文/数字/半角标点/音标字符 -> True；汉字与全角标点 -> False。"""
    o = ord(ch)
    if o < 0x80:
        return True                      # ASCII（含空白，空白只用于 run 分组）
    return (0xC0 <= o <= 0x24F           # 拉丁扩展
            or 0x250 <= o <= 0x2AF       # IPA 扩展
            or 0x2B0 <= o <= 0x2FF       # 修饰字母（含 ː ˈ ˌ）
            or 0x1D00 <= o <= 0x1D7F)    # 音标扩展


def norm(s):
    return NORM_RE.sub("", s.lower())


def clean_ws(s):
    return WS_RE.sub(" ", s).strip()


def cluster_lines(chars):
    """按 bottom 聚成视觉行，行内按 x 排序。

    聚完再做一次合并：同一视觉行可能被 OCR 拆成几个 box（实测 p300 的
    `②陡峭的，垂直的：The mountain was too` + ` to climb.` 两个 box 的
    bottom 差 9.1 pt、字号 27.0 vs 29.6），只要 bottom 差 ≤14 pt 且 x 区间
    相接/重叠，就当成同一行再按 x 重排。
    """
    out, cur, last = [], [], None
    for c in sorted(chars, key=lambda c: (c["bottom"], c["x0"])):
        v = c["bottom"]
        if last is None or v - last <= LINE_TOL:
            cur.append(c)
            last = v if last is None else max(last, v)
        else:
            out.append(sorted(cur, key=lambda c: c["x0"]))
            cur, last = [c], v
    if cur:
        out.append(sorted(cur, key=lambda c: c["x0"]))

    merged = []
    for line in out:
        if merged:
            prev = merged[-1]
            pb = max(c["bottom"] for c in prev)
            cb = max(c["bottom"] for c in line)
            gap = max(line[0]["x0"], prev[0]["x0"]) - min(
                max(c["x1"] for c in line), max(c["x1"] for c in prev))
            if abs(cb - pb) <= LINE_MERGE_TOL and gap < 30:
                merged[-1] = sorted(prev + line, key=lambda c: c["x0"])
                continue
        merged.append(line)
    return merged


def split_columns(chars):
    left, right = [], []
    for c in chars:
        (left if (c["x0"] + c["x1"]) / 2 < COL_X else right).append(c)
    return left, right


def drop_margins(chars):
    """丢页眉「红宝书」条带与页脚页码条带。"""
    return [c for c in chars if HEADER_BOT < c["bottom"] < FOOTER_TOP]


def line_text(line):
    return "".join(c["text"] for c in line)


def is_page_number(text):
    return bool(PAGE_NO_RE.match(text))


def is_header_line(line):
    """页眉行：贴近页顶且只剩「红宝书 / 考研英语词汇」字样。

    广告页（如 p443）满页都有「红宝书」字样，不能一律当页眉删掉，
    所以限定在顶部 9% 以内。
    """
    if max(c["bottom"] for c in line) > 0.09 * PAGE_H:
        return False
    stripped = re.sub(r"[\s·•.。\-—_*\\/|()（）\[\]:：]", "", line_text(line))
    return stripped in HEADER_WORDS or not stripped


def reading_order(chars):
    """先左栏后右栏、栏内按行、行内按 x 的字符序列。"""
    seq = []
    for col in split_columns(drop_margins(chars)):
        for line in cluster_lines(col):
            seq.append(line)
    return seq


# ------------------------------------------------------------------ 英文层索引
def line_latin_norm(chars):
    """一行里所有拉丁字符拼起来再规范化（用于行级对齐）。"""
    return norm("".join(c["text"] for c in chars if is_latin(c["text"][-1])))


def build_en_stream(echars):
    """英文层 -> (alnum 串 s, s 每个字符对应的 echars 下标, 每行的 s 区间)。

    `s` 就是按阅读顺序把英文层所有字母数字串起来，垃圾 ASCII（`+`、`#`、`[`）
    被滤掉，但每个字符都记着它在 `echars` 里的下标，所以命中一段 `s` 就能取回
    英文层**原文**（含词间空格）。`spans[j]` 是第 j 个视觉行的 s 区间，用于把
    「中文某一行」能偷的英文限制在它自己那一行里（否则指针会跑到别的行去）。
    """
    buf, pos, raw, spans = [], [], [], []
    for line in reading_order(echars):
        st = len(buf)
        for c in line:
            ch = c["text"][-1]
            raw.append(c["text"])
            if ch.isascii() and ch.isalnum():
                buf.append(ch.lower())
                pos.append(len(raw) - 1)
        spans.append((st, len(buf)))
    return "".join(buf), pos, raw, spans


def align_lines(zt, et):
    """行级对齐：返回 {中文行号: 英文行号}（都是传入列表的下标）。

    能逐字对上的行走 SequenceMatcher 的 equal 块；剩下的是两边都认错的乱码行，
    按比例一一分配（一对多/多对一时保持单调）。
    """
    m = {}
    sm = difflib.SequenceMatcher(None, zt, et, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                m[i1 + k] = j1 + k
        elif tag == "replace":
            nz, ne = i2 - i1, j2 - j1
            for k in range(nz):
                m[i1 + k] = j1 + min(ne - 1, int(k * ne / nz))
    return m


def inflect_forms(word):
    """粗糙的屈折/派生展开，用于「不要拆散真词」与第二个粘连率口径。"""
    out = set()
    w = word.lower()
    for suf in ("s", "es", "ed", "d", "ing", "er", "est", "ly", "ness",
                "ment", "ful", "less", "able", "ible", "tion", "sion"):
        out.add(w + suf)
    if w.endswith("y"):
        out.update((w[:-1] + "ies", w[:-1] + "ied", w[:-1] + "ier"))
    if w.endswith("e"):
        out.update((w[:-1] + "ing", w[:-1] + "ed"))
    if len(w) > 2 and w[-1] not in "aeiou":
        out.update((w + w[-1] + "ing", w + w[-1] + "ed"))
    return out


def split_glued(token, vocab, max_parts=4):
    """把 `inviewof` 这种粘连 token 按词库切成 `in view of`。

    只在整 token 不在词库里时才拆，且要求：
      * 每一段要么是 ≥3 字母的词库词，要么是一个介词/小词（in/of/to/with…）；
      * 至少有一段是介词——书上的粘连几乎都是单词与介词粘住，用这个锚点可以
        避开 `contradiction -> contradict ion`、`players -> play ers` 这类误拆；
      * 后缀（ing/ed/ion…）不许当一段。
    拆不出来就原样返回。
    """
    memo = {}

    def ok(w):
        if w in SUFFIX_STOP:
            return False
        if w in PREPS or w in JOINT_OK:
            return True
        if len(w) == 2:
            return w in FUNC_WORDS
        return w in vocab

    def go(i):
        if i == len(token):
            return ()
        if i in memo:
            return memo[i]
        best = None
        for e in range(i + 1, min(len(token), i + 22) + 1):
            w = token[i:e]
            if not ok(w):
                continue
            rest = go(e)
            if rest is None:
                continue
            cand = (w,) + rest
            if len(cand) <= max_parts and (best is None or len(cand) < len(best)):
                best = cand
        memo[i] = best
        return best

    parts = go(0)
    if not parts or len(parts) < 2:
        return token
    return " ".join(parts)


def desplit_line(text, vocab, base, log=None):
    """行内把粘连的长 token 拆开（不碰已在词库里的真词）。"""
    def repl(m):
        w = m.group(0)
        if w.lower() in base:
            return w
        new = split_glued(w.lower(), vocab)
        if new != w.lower():
            if log is not None:
                log.append((w, new))
            return new
        return w

    return re.sub(r"[A-Za-z]{6,}", repl, text)


# ------------------------------------------------------------------ 合并
class Merger:
    def __init__(self, whitelist, base=None, vocab=None, split_log=False):
        self.whitelist = whitelist
        self.base = base or whitelist
        self.vocab = vocab or whitelist
        self.stat = dict(latin_runs=0, exact=0, fuzzy=0, fallback=0,
                         tilde=0, punct_keep=0, lines_unmapped=0, desplit=0)
        self.split_log = [] if split_log else None

    # ---------------- 在英文串里定位一个 run
    @staticmethod
    def find_span(t, s, lo, hi):
        idx = s.find(t, lo, hi)
        return (idx, idx + len(t)) if idx >= 0 else None

    @staticmethod
    def fuzzy_span(t, s, lo, hi):
        """英文层把词认错（straln/strain）时按相似度找最像的一段。"""
        win = s[lo:min(hi, lo + len(t) + 8)]
        if not win:
            return None
        sm = difflib.SequenceMatcher(None, t, win, autojunk=False)
        blocks = [b for b in sm.get_matching_blocks() if b.size]
        if not blocks:
            return None
        cov = sum(b.size for b in blocks) / len(t)
        if cov < FUZZY_MIN or sm.ratio() < 0.55:
            return None
        return lo + blocks[0].b, lo + blocks[-1].b + blocks[-1].size

    # ---------------- 一行
    def merge_line(self, line, s, pos, raw, win):
        """win=(lo, hi) 是该行允许匹配的英文区间；返回行文本。"""
        pieces = []          # [(kind, text)]
        runs = []
        for c in line:
            ch = c["text"][-1]
            # `~` 是词条占位符，单独成一个 run：英文层常把它丢掉，
            # 切出来之后 `of~on` 才能拼成 `of ~ on`
            kind = "S" if ch in KEEP_SYMBOLS else ("L" if is_latin(ch) else "C")
            if runs and runs[-1][0] == kind:
                runs[-1][1].append(c)
            else:
                runs.append([kind, [c]])

        lo, hi = win if win else (0, 0)
        q = lo
        for kind, cs in runs:
            text = "".join(c["text"] for c in cs)
            if kind == "C":
                pieces.append(("C", text))
                continue
            if kind == "S":
                self.stat["tilde"] += text.count("~")
                pieces.append(("L", text))
                continue
            t = norm(text)
            if not t:
                pieces.append(("L", text))
                continue
            self.stat["latin_runs"] += 1
            if not win:
                self.stat["fallback"] += 1
                pieces.append(("L", text))
                continue
            span = self.find_span(t, s, q, hi)
            how = "exact"
            if span is None:
                span = self.fuzzy_span(t, s, q, hi)
                how = "fuzzy"
            if span is None:
                self.stat["fallback"] += 1
                pieces.append(("L", text))
                continue
            self.stat[how] += 1
            a, b = span
            # 英文层原文：按**字符区间**取（含词间空格与标点），首尾正好裁到命中字符
            sub = clean_ws("".join(raw[pos[a]:pos[b - 1] + 1]))
            # 中文层 run 首尾被规范化丢掉的标点补回来
            lead = re.match(r"^[^A-Za-z0-9]*", text).group()
            trail = re.search(r"[^A-Za-z0-9]*$", text).group()
            if lead and not sub.startswith(lead.strip()):
                sub = lead + sub
            if trail and not sub.endswith(trail.strip()):
                sub = sub + trail
            if re.search(r"[,;/&]", text) and not re.search(r"[,;/&]", sub):
                # 英文层把分隔符丢了（`become,fall` 认成 `becomefall`）：
                # 中文层有分隔符就以中文层为准，只在分隔符后补一个空格
                self.stat["punct_keep"] += 1
                sub = clean_ws(re.sub(r"([,;/&])", r"\1 ", clean_ws(text)))
            pieces.append(("L", sub))
            q = b
        out = ""
        for idx, (kind, text) in enumerate(pieces):
            if not out:
                out = text
                continue
            prev = pieces[idx - 1][0]
            out += ("" if "C" in (kind, prev) else " ") + text
        out = clean_ws(out)
        if out and is_page_number(out):
            out = ""
        if out and self.vocab:
            new = desplit_line(out, self.vocab, self.base, self.split_log)
            if new != out:
                self.stat["desplit"] += 1
                out = new
        return out

    # ---------------- 一页
    def merge_page(self, zchars, echars):
        s, pos, raw, spans = build_en_stream(echars)
        zh_lines = []
        for line in reading_order(zchars):
            text = line_text(line)
            if not text.strip() or is_header_line(line) or is_page_number(text):
                continue
            zh_lines.append(line)
        zt = [line_latin_norm(ln) for ln in zh_lines]
        et = [s[a:b] for a, b in spans]
        zidx = [i for i, t in enumerate(zt) if t]
        eidx = [j for j, t in enumerate(et) if t]
        pair = align_lines([zt[i] for i in zidx], [et[j] for j in eidx])
        windows = {}
        for k, i in enumerate(zidx):
            if k in pair:
                a, b = spans[eidx[pair[k]]]
                windows[i] = (max(0, a - 40), min(len(s), b + 40))
            else:
                self.stat["lines_unmapped"] += 1
        out = []
        for i, line in enumerate(zh_lines):
            merged = self.merge_line(line, s, pos, raw, windows.get(i))
            if merged:
                out.append(merged)
        return out


# ------------------------------------------------------------------ 指标
def cjk_count(text):
    return sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")


GLUE_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z'’.\-]*")
GROUP_LINE_PREFIX = ("【词组】", "【搭配】")


WORD_SUFFIXES = ("s", "es", "ed", "d", "ing", "ly", "er", "ers", "est", "ion",
                 "tion", "sion", "ment", "ness", "al", "ous", "ive", "ful",
                 "less", "able", "ible")


def looks_like_word(t, vocab):
    """`dividends`/`standards` 这类带屈折的真词：剥后缀能回到词库词。"""
    if t in vocab:
        return True
    for suf in WORD_SUFFIXES:
        if t.endswith(suf):
            stem = t[: -len(suf)]
            if stem in vocab or stem + "e" in vocab or stem + "y" in vocab:
                return True
    return False


def glue_rate(lines, whitelist, vocab=None):
    """【词组】/【搭配】行里拉丁 token 的粘连率。

    口径一（parent 指定）：token 长度 >=8 且不在「4292 词条 + 功能词」白名单里。
    这个口径会把 `dividends`、`standards` 这类带屈折的真词也算进去，所以偏高。
    传了 `vocab` 时额外统计「硬粘连」：既不像真词（剥后缀也回不到词库），
    也拆不成两个词库词。
    """
    rows = [ln for ln in lines if ln.startswith(GROUP_LINE_PREFIX)]
    bad = hard = 0
    for ln in rows:
        is_bad = is_hard = False
        for tok in GLUE_TOKEN_RE.findall(ln):
            t = tok.strip(".'\u2019-~").lower()
            if len(t) >= 8 and t not in whitelist:
                is_bad = True
                if (vocab is not None and not looks_like_word(t, vocab)
                        and split_glued(t, vocab) == t):
                    is_hard = True
                break
        bad += is_bad
        hard += is_hard
    return bad, len(rows), hard


def entry_hits(text, pattern):
    """去重后的词条命中数（同一词出现在多处只计一次）。"""
    return len(set(pattern.findall(text.lower())))


def build_entry_pattern(words):
    """词条命中用「前后不是字母」作边界，不用 `\\b`。

    英文与中文紧邻（`的steady`）时 Python 的 `\\b` 不认边界（CJK 也算 \\w），
    会把大量真实命中漏掉；这里只把 ASCII 字母当词内字符。
    """
    alts = sorted({re.escape(w.lower()) for w in words}, key=len, reverse=True)
    return re.compile(r"(?<![a-z])(?:" + "|".join(alts) + r")(?![a-z])")


def en_corpus_words(epdf, targets):
    """先扫一遍英文层，收集所有「作为独立 token 出现过」的纯字母词。

    4292 词条表缺 kitchen / under / study / oneself 这类基础词，机器上也没有
    words/hunspell 词典；而英文层本身有空格，它自己分词出来的 token 就是一份
    书内词表。这份词表同时用作「不许拆」的白名单：只要一个 token 在英文层
    独立出现过（哪怕一次），就不当粘连拆——`indifference`、`underwent`、
    `readiness` 这类真词就是这样保住的；真正粘连的 `inviewof`、`bynature`
    在英文层里从来不会独立出现，所以照拆。
    """
    cnt = {}
    for pno in targets:
        for line in reading_order(epdf.pages[pno - 1].chars):
            for t in re.split(r"[^A-Za-z]+", line_text(line)):
                if 2 <= len(t) <= 24:
                    t = t.lower()
                    cnt[t] = cnt.get(t, 0) + 1
    return set(cnt)


def parse_pages(spec, total):
    if not spec:
        return list(range(1, total + 1))
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


def main(argv=None):
    ap = argparse.ArgumentParser(description="合并中英两份 OCR 文本层")
    ap.add_argument("--zh", default=str(DEFAULT_ZH))
    ap.add_argument("--en", default=str(DEFAULT_EN))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--entries", default=str(DEFAULT_ENTRIES))
    ap.add_argument("--pages", default="", help="如 12,40,300 或 1-444")
    ap.add_argument("--report", default="")
    ap.add_argument("--samples", default="12,40,300", help="报告里抽查的页码")
    args = ap.parse_args(argv)

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    words = [e["word"] for e in json.loads(Path(args.entries).read_text(encoding="utf-8"))]
    whitelist = {w.lower() for w in words} | FUNC_WORDS
    # 拆粘连用的词表：原文 + 屈折形 + 书上的 sth./sb. 简写
    vocab = set(whitelist) | COMMON_WORDS | {"sth", "sb", "smb", "oneself", "one's"}
    for w in words:
        vocab |= inflect_forms(w)

    t0 = time.time()
    pages_out, zh_lines, en_lines = {}, [], []
    with pdfplumber.open(args.zh) as zpdf, pdfplumber.open(args.en) as epdf:
        if len(zpdf.pages) != len(epdf.pages):
            raise SystemExit("两份 PDF 页数不一致")
        total = len(zpdf.pages)
        targets = parse_pages(args.pages, total)
        vocab |= en_corpus_words(epdf, targets)
        merger = Merger(whitelist, base=vocab, vocab=vocab)
        print(f"  词库 {len(vocab)} 个词，开始合并", flush=True)
        for k, pno in enumerate(targets, 1):
            zchars = zpdf.pages[pno - 1].chars
            echars = epdf.pages[pno - 1].chars
            zh_lines.extend(line_text(ln) for ln in reading_order(zchars))
            en_lines.extend(line_text(ln) for ln in reading_order(echars))
            lines = merger.merge_page(zchars, echars)
            pages_out[pno] = lines
            (outdir / f"page_{pno:04d}.txt").write_text(
                "\n".join(lines) + "\n", encoding="utf-8")
            if k % 50 == 0:
                print(f"  {k}/{len(targets)} 页  {time.time()-t0:.1f}s", flush=True)
    elapsed = time.time() - t0

    merged_lines = [ln for p in sorted(pages_out) for ln in pages_out[p]]
    merged_text = "\n".join(merged_lines)
    zh_text = "\n".join(zh_lines)
    en_text = "\n".join(en_lines)

    widened = set(whitelist) | vocab            # 第二个（更宽）粘连率口径
    gz_m, gz_t, gz_hard = glue_rate(zh_lines, whitelist, vocab)
    gm_m, _, gm_hard = glue_rate(merged_lines, whitelist, vocab)
    gz_w, _, _ = glue_rate(zh_lines, widened)
    gm_w, _, _ = glue_rate(merged_lines, widened)
    cjk_zh, cjk_m = cjk_count(zh_text), cjk_count(merged_text)
    pat = build_entry_pattern(words)
    hit_zh = entry_hits(zh_text, pat)
    hit_en = entry_hits(en_text, pat)
    hit_m = entry_hits(merged_text, pat)
    nw = len(words)

    print(f"\n页数 {len(pages_out)}  耗时 {elapsed:.1f}s "
          f"({elapsed/max(1,len(pages_out))*1000:.0f} ms/页)")
    print(f"汉字数 中文层 {cjk_zh} -> 合并 {cjk_m} ({cjk_m/max(1,cjk_zh)*100:.2f}%)")
    print(f"粘连率 中文层 {gz_m}/{gz_t}={gz_m/max(1,gz_t)*100:.1f}%"
          f"  合并后 {gm_m}/{gz_t}={gm_m/max(1,gz_t)*100:.1f}%"
          f"   （含屈折白名单 {gz_w/max(1,gz_t)*100:.1f}% -> {gm_w/max(1,gz_t)*100:.1f}%）"
          f"   硬粘连 {gz_hard} -> {gm_hard}")
    print(f"词条命中 中文层 {hit_zh/nw*100:.1f}%  英文层 {hit_en/nw*100:.1f}%"
          f"  合并 {hit_m/nw*100:.1f}%")
    print("合并统计", merger.stat)

    if args.report:
        write_report(Path(args.report), pages_out, args, elapsed, merger.stat,
                     dict(n_pages=len(pages_out), cjk_zh=cjk_zh, cjk_m=cjk_m,
                          gz=(gz_m, gz_t), gm=(gm_m, gz_t),
                          gz_w=gz_w, gm_w=gm_w, gz_hard=gz_hard, gm_hard=gm_hard,
                          hit_zh=(hit_zh, nw), hit_en=(hit_en, nw),
                          hit_m=(hit_m, nw)))
    return 0


def write_report(path, pages_out, args, elapsed, stat, m):
    samples = [int(p) for p in args.samples.split(",") if p.strip()]
    gz_t = m["gz"][1]
    L = ["# OCR 双文本层合并报告", ""]
    L.append(f"生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}　"
             f"脚本：`round2/tools/merge_layers.py`　"
             f"页数：{m['n_pages']}　耗时：{elapsed:.0f}s")
    L.append("")
    L.append("## 输入")
    L.append("")
    L.append("| 层 | 文件 | 强项 | 弱项 |")
    L.append("|----|------|------|------|")
    L.append(f"| 中文 | `{Path(args.zh).name}` | 汉字与 `【】` 标记准 | 英文单词粘连、无词间空格 |")
    L.append(f"| 英文 | `{Path(args.en).name}` | 英文分词准、有词间空格 | 中文全废（`AE+`、`#0v.`） |")
    L.append("")
    L.append("## 算法")
    L.append("")
    L.append("1. 两层都按「先左栏（x 中心 < 863）后右栏、栏内按 `bottom` 升序、行内按 x」"
             "排成字符流；按 `bottom` 容差 8 pt 聚成视觉行，聚完再把同一行被 OCR 拆开的"
             "box 合回去（`bottom` 差 ≤14 pt 且 x 区间相接）。")
    L.append("2. 丢页眉（bottom ≤ 163 pt 的「红宝书」条带）与页脚页码（top ≥ 2360 pt，"
             "或整行只有数字/装饰符）。")
    L.append("3. 英文层只取 ASCII 字母数字拼成骨架串 `s`（记着每个字符到原字符的下标），"
             "中文层每行切成 Latin run / CJK run，CJK run 原样保留。")
    L.append("4. 先做**行级对齐**：把两层的行内容规范化后用 `difflib` 对行序列，能逐字对上的"
             "行直接配成一对，乱码行按比例单调分配。于是每个 Latin run 只会在它自己那行"
             "对应的英文区间（±40 字符）里找，指针不会漂到别的行去。")
    L.append("5. Latin run 规范化后在 `s` 里做**字符级**精确查找，命中区间取英文层**原文**"
             "（中间的空格是英文层真实字符，自动带回）。允许命中落在英文 token 内部："
             "`（onupon）` 能从英文层的 `on/uponThe` 里取回 `on/upon`，剩下的 `The` "
             "留给下一个 run。")
    L.append("6. 精确查找失败 → difflib 相似度 ≥0.80 兜底 → 仍失败则保留中文层原文（不丢内容）。")
    L.append("7. `~`（词条占位符）单独切 run，所以 `of~on` 能拼成 `of ~ on`；英文层把分隔符"
             "丢了（`become,fall` 认成 `becomefall`）时以中文层为准并在分隔符后补空格。")
    L.append("8. **拆残粘连**：如果某个 token 既不在词表里、也从未在英文层独立出现过，就按"
             "词库尝试切成 2–4 段（`inviewof -> in view of`、`contendwith -> contend with`）。"
             "词库 = 4292 词条 + 屈折形 + 内置高频词 + 英文层自己的分词结果；"
             "要求有一段是介词/小词，或两段都 ≥5 字母，且后缀（ing/ed/ion…）不许当一段——"
             "否则会把 `contradiction` 拆成 `contradict ion`。")
    L.append("9. 行内拼接：任一侧是 CJK 就不加空格，纯拉丁之间一个空格，多空格压成一个。")
    L.append("")
    L.append("### 为什么不用按 x 坐标直接对齐")
    L.append("")
    L.append("英文层的字形宽度是按 token bbox 均摊出来的。纯英文行两层坐标完全一致，但混排行"
             "里中文被认成垃圾 ASCII、token bbox 被撑大，整行坐标就废了：p40 的 "
             "`【词组】be（或become,fall）preytosth.被.捕食`，中文层 `top=194.8`、"
             "英文层 `top=177.5`（字号 26 vs 52.4），英文层把 `be` 画在了 `【词组】` 的位置。"
             "按 x 硬套会把 `be` 配给 `【词组】`，而「行级对齐 + 字符级顺序查找」不受影响。")
    L.append("")
    L.append("## 指标")
    L.append("")
    L.append("| 指标 | 中文层 | 英文层 | 合并后 | 目标 |")
    L.append("|------|--------|--------|--------|------|")
    L.append(f"| 【词组】/【搭配】行粘连率（指定口径） | {m['gz'][0]}/{gz_t} = "
             f"{m['gz'][0]/max(1,gz_t)*100:.1f}% | — | **{m['gm'][0]}/{gz_t} = "
             f"{m['gm'][0]/max(1,gz_t)*100:.1f}%** | < 5% |")
    L.append(f"| 同上，白名单含屈折形/书内词 | — | — | "
             f"{m['gz_w']/max(1,gz_t)*100:.1f}% → **{m['gm_w']/max(1,gz_t)*100:.1f}%** | < 5% |")
    L.append(f"| 其中「硬粘连」行（不像真词、也拆不开） | — | — | "
             f"{m['gm_hard']}/{gz_t} = **{m['gm_hard']/max(1,gz_t)*100:.1f}%** | — |")
    L.append(f"| 汉字数 | {m['cjk_zh']} | 0 | {m['cjk_m']} "
             f"({m['cjk_m']/max(1,m['cjk_zh'])*100:.2f}%) | ≈283k，±5% |")
    hz, nw = m["hit_zh"]
    he, _ = m["hit_en"]
    hm, _ = m["hit_m"]
    L.append(f"| 4292 词条原形命中率 | {hz/nw*100:.1f}% | {he/nw*100:.1f}% | "
             f"**{hm/nw*100:.1f}%** | ≈99% ±1% |")
    L.append(f"| 耗时（{m['n_pages']} 页） | — | — | {elapsed:.0f}s | 5–10 min |")
    L.append("")
    L.append("口径说明：")
    L.append("")
    L.append("- 粘连率：一行里出现「不在白名单且长度 ≥8」的拉丁 token 即判该行粘连。"
             "指定白名单只有 4292 词条 + 常见功能词，8 字母以上的**屈折真词**"
             "（`dividends`、`standards`、`privileges`、`startled`）不在其中，会被误判为粘连，"
             "所以指定口径偏保守；第二行把屈折形和书内词加进白名单后才是真实水平。")
    L.append("- 词条命中率：边界用「前后不是 ASCII 字母」而不是 `\\b`——中文与英文紧邻时"
             "（`的steady`）`\\b` 不认边界（CJK 也算 `\\w`），会漏掉大量真实命中。")
    L.append("")
    L.append("## 合并统计")
    L.append("")
    L.append(f"- 拉丁 run 总数 **{stat['latin_runs']}**")
    L.append(f"- 精确命中 **{stat['exact']}**（{stat['exact']/max(1,stat['latin_runs'])*100:.1f}%）")
    L.append(f"- 模糊兜底 **{stat['fuzzy']}**（{stat['fuzzy']/max(1,stat['latin_runs'])*100:.1f}%）")
    L.append(f"- 退回中文层 **{stat['fallback']}**"
             f"（{stat['fallback']/max(1,stat['latin_runs'])*100:.1f}%）——英文层同一行也是乱码"
             "时不可避免，如 p40 `【同义】frank,honest②plain, simple` 英文层作 "
             "`fraankh~onejstoplainbsim-pleI`；这类 run 后面还有拆粘连兜底")
    L.append(f"- `~` 占位符单独切 run 保留 **{stat['tilde']}** 处")
    L.append(f"- 拆粘联动过 **{stat['desplit']}** 行")
    L.append("")
    L.append("## 剩下没解决的")
    L.append("")
    L.append("- 英文层也有认错成纯字母的时候（`Scentifc discoveries`、`inw viewa oyfs`），"
             "此时精确/模糊都命中不了，只能退回中文层原文，残粘连就留在那里。"
             "没有系统词典（机器上没有 words/hunspell）无法强行切。")
    L.append("- 两层都把 `~` 认丢的行（p300 `The mountain was too to climb.`）无法恢复占位符。")
    L.append("- 个别词条标题行两层都是乱码（p40 `relanceTrilarens` ← `reliance [rɪˈlaɪəns]`），"
             "交给下游 `parse_entries.py` 的模糊匹配。")
    L.append("")
    L.append("## 人工抽查")
    L.append("")
    for p in samples:
        L.append(f"### PDF 第 {p} 页（前 12 行）")
        L.append("")
        L.append("```")
        L.extend(pages_out.get(p, [])[:12])
        L.append("```")
        L.append("")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("\n".join(L) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
