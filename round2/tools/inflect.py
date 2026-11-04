#!/usr/bin/env python3
"""英语词形变形模块（红宝书二轮牌组用）。

规则变化由后缀规则生成；不规则表**自建**（不是从 lemminflect / NLTK 拷来的），
只收录考研英语范围内常见的不规则动词、名词、形容词。表可以直接 import：

    from inflect import IRREGULAR_VERBS, IRREGULAR_NOUNS, IRREGULAR_ADJ

对外 API：
    forms(word, pos)        -> {"past": ..., "pp": ..., "3sg": ..., "ing": ...}
                               / {"plural": ...} / {"comparative": ..., "superlative": ...}
                               只返回与词性相关的键；pos 可为 "v./n." 形式或 None。
    is_irregular(word, pos) -> 同结构的 {键: bool}，True 表示该形式靠不规则表得到。
    irregular_forms(w, pos) -> forms 的子集，只留 is_irregular 为 True 的项（卡片用）。
    guess_pos(word, meaning) -> 从中文释义开头的 "adj." / "v." 等猜词性，猜不出返回 None。

约定：
* 多 variant 用 " / " 连接，如 strive 的过去式 "strove / strived"。
* 拼写按美式（travel -> traveling），不规则表里英式变体也保留（learnt / learned）。
* 直接运行本文件会做一轮抽查校验（python3 inflect.py）。
"""

from __future__ import annotations

import re

VOWELS = "aeiou"

# ---------------------------------------------------------------------------
# 自建不规则动词表：base -> (过去式, 过去分词)
# 只收考研常见词；含英/美两种写法的用 " / " 连接。
# 备注见 IRREGULAR_VERB_NOTES（释义有歧义的词：bear / hang / lie / shine）。
# ---------------------------------------------------------------------------
IRREGULAR_VERBS: dict[str, tuple[str, str]] = {
    "abide": ("abode / abided", "abode / abided"),
    "arise": ("arose", "arisen"),
    "awake": ("awoke", "awoken"),
    "be": ("was / were", "been"),
    "bear": ("bore", "borne"),
    "beat": ("beat", "beaten"),
    "become": ("became", "become"),
    "befall": ("befell", "befallen"),
    "beget": ("begot", "begotten"),
    "begin": ("began", "begun"),
    "behold": ("beheld", "beheld"),
    "bend": ("bent", "bent"),
    "beset": ("beset", "beset"),
    "bet": ("bet", "bet"),
    "bid": ("bade / bid", "bidden / bid"),
    "bide": ("bode / bided", "bided"),
    "bind": ("bound", "bound"),
    "bite": ("bit", "bitten"),
    "bleed": ("bled", "bled"),
    "bless": ("blest / blessed", "blest / blessed"),
    "blow": ("blew", "blown"),
    "break": ("broke", "broken"),
    "breed": ("bred", "bred"),
    "bring": ("brought", "brought"),
    "broadcast": ("broadcast", "broadcast"),
    "build": ("built", "built"),
    "burn": ("burnt / burned", "burnt / burned"),
    "burst": ("burst", "burst"),
    "buy": ("bought", "bought"),
    "cast": ("cast", "cast"),
    "catch": ("caught", "caught"),
    "choose": ("chose", "chosen"),
    "cling": ("clung", "clung"),
    "clothe": ("clad / clothed", "clad / clothed"),
    "come": ("came", "come"),
    "cost": ("cost", "cost"),
    "creep": ("crept", "crept"),
    "crow": ("crowed / crew", "crowed"),
    "cut": ("cut", "cut"),
    "deal": ("dealt", "dealt"),
    "dig": ("dug", "dug"),
    "dive": ("dived / dove", "dived"),
    "do": ("did", "done"),
    "draw": ("drew", "drawn"),
    "dream": ("dreamt / dreamed", "dreamt / dreamed"),
    "drink": ("drank", "drunk"),
    "drive": ("drove", "driven"),
    "dwell": ("dwelt / dwelled", "dwelt / dwelled"),
    "eat": ("ate", "eaten"),
    "fall": ("fell", "fallen"),
    "feed": ("fed", "fed"),
    "feel": ("felt", "felt"),
    "fight": ("fought", "fought"),
    "find": ("found", "found"),
    "flee": ("fled", "fled"),
    "fling": ("flung", "flung"),
    "fly": ("flew", "flown"),
    "forbear": ("forbore", "forborne"),
    "forbid": ("forbade / forbad", "forbidden"),
    "forecast": ("forecast", "forecast"),
    "foresee": ("foresaw", "foreseen"),
    "foretell": ("foretold", "foretold"),
    "forget": ("forgot", "forgotten"),
    "forgive": ("forgave", "forgiven"),
    "forsake": ("forsook", "forsaken"),
    "freeze": ("froze", "frozen"),
    "get": ("got", "got / gotten"),
    "gild": ("gilt / gilded", "gilt / gilded"),
    "gird": ("girt / girded", "girt / girded"),
    "give": ("gave", "given"),
    "go": ("went", "gone"),
    "grind": ("ground", "ground"),
    "grow": ("grew", "grown"),
    "hang": ("hung / hanged", "hung / hanged"),
    "have": ("had", "had"),
    "hear": ("heard", "heard"),
    "heave": ("heaved / hove", "heaved / hove"),
    "hew": ("hewed", "hewn / hewed"),
    "hide": ("hid", "hidden"),
    "hit": ("hit", "hit"),
    "hold": ("held", "held"),
    "hurt": ("hurt", "hurt"),
    "keep": ("kept", "kept"),
    "kneel": ("knelt / kneeled", "knelt / kneeled"),
    "knit": ("knit / knitted", "knit / knitted"),
    "know": ("knew", "known"),
    "lade": ("laded", "laden / laded"),
    "lay": ("laid", "laid"),
    "lead": ("led", "led"),
    "lean": ("leant / leaned", "leant / leaned"),
    "leap": ("leapt / leaped", "leapt / leaped"),
    "learn": ("learnt / learned", "learnt / learned"),
    "leave": ("left", "left"),
    "lend": ("lent", "lent"),
    "let": ("let", "let"),
    "lie": ("lay", "lain"),
    "light": ("lit / lighted", "lit / lighted"),
    "lose": ("lost", "lost"),
    "make": ("made", "made"),
    "mean": ("meant", "meant"),
    "meet": ("met", "met"),
    "mislead": ("misled", "misled"),
    "mistake": ("mistook", "mistaken"),
    "misunderstand": ("misunderstood", "misunderstood"),
    "mow": ("mowed", "mown / mowed"),
    "outbid": ("outbid", "outbid"),
    "outdo": ("outdid", "outdone"),
    "outgrow": ("outgrew", "outgrown"),
    "output": ("output", "output"),
    "outrun": ("outran", "outrun"),
    "outsell": ("outsold", "outsold"),
    "outshine": ("outshone", "outshone"),
    "overcome": ("overcame", "overcome"),
    "overdo": ("overdid", "overdone"),
    "overdraw": ("overdrew", "overdrawn"),
    "overeat": ("overate", "overeaten"),
    "overfly": ("overflew", "overflown"),
    "overhang": ("overhung", "overhung"),
    "overhear": ("overheard", "overheard"),
    "overlay": ("overlaid", "overlaid"),
    "overlie": ("overlay", "overlain"),
    "override": ("overrode", "overridden"),
    "overrun": ("overran", "overrun"),
    "oversee": ("oversaw", "overseen"),
    "overshoot": ("overshot", "overshot"),
    "oversleep": ("overslept", "overslept"),
    "overtake": ("overtook", "overtaken"),
    "overthrow": ("overthrew", "overthrown"),
    "overwrite": ("overwrote", "overwritten"),
    "pay": ("paid", "paid"),
    "plead": ("pleaded / pled", "pleaded / pled"),
    "prove": ("proved", "proved / proven"),
    "put": ("put", "put"),
    "quit": ("quit", "quit"),
    "read": ("read", "read"),
    "rebuild": ("rebuilt", "rebuilt"),
    "recast": ("recast", "recast"),
    "redo": ("redid", "redone"),
    "remake": ("remade", "remade"),
    "rend": ("rent", "rent"),
    "repay": ("repaid", "repaid"),
    "rerun": ("reran", "rerun"),
    "reset": ("reset", "reset"),
    "retell": ("retold", "retold"),
    "rethink": ("rethought", "rethought"),
    "rewind": ("rewound", "rewound"),
    "rewrite": ("rewrote", "rewritten"),
    "rid": ("rid", "rid"),
    "ride": ("rode", "ridden"),
    "ring": ("rang", "rung"),
    "rise": ("rose", "risen"),
    "rive": ("rived", "riven / rived"),
    "run": ("ran", "run"),
    "saw": ("sawed", "sawn / sawed"),
    "say": ("said", "said"),
    "see": ("saw", "seen"),
    "seek": ("sought", "sought"),
    "sell": ("sold", "sold"),
    "send": ("sent", "sent"),
    "set": ("set", "set"),
    "sew": ("sewed", "sewn / sewed"),
    "shake": ("shook", "shaken"),
    "shave": ("shaved", "shaven / shaved"),
    "shear": ("sheared", "shorn / sheared"),
    "shed": ("shed", "shed"),
    "shine": ("shone / shined", "shone / shined"),
    "shoe": ("shod", "shod"),
    "shoot": ("shot", "shot"),
    "show": ("showed", "shown / showed"),
    "shrink": ("shrank / shrunk", "shrunk"),
    "shut": ("shut", "shut"),
    "sing": ("sang", "sung"),
    "sink": ("sank / sunk", "sunk"),
    "sit": ("sat", "sat"),
    "slay": ("slew", "slain"),
    "sleep": ("slept", "slept"),
    "slide": ("slid", "slid"),
    "sling": ("slung", "slung"),
    "slink": ("slunk", "slunk"),
    "slit": ("slit", "slit"),
    "smell": ("smelt / smelled", "smelt / smelled"),
    "smite": ("smote", "smitten"),
    "sow": ("sowed", "sown / sowed"),
    "speak": ("spoke", "spoken"),
    "speed": ("sped / speeded", "sped / speeded"),
    "spell": ("spelt / spelled", "spelt / spelled"),
    "spend": ("spent", "spent"),
    "spill": ("spilt / spilled", "spilt / spilled"),
    "spin": ("spun", "spun"),
    "spit": ("spat / spit", "spat / spit"),
    "split": ("split", "split"),
    "spoil": ("spoilt / spoiled", "spoilt / spoiled"),
    "spread": ("spread", "spread"),
    "spring": ("sprang / sprung", "sprung"),
    "stand": ("stood", "stood"),
    "stave": ("staved / stove", "staved / stove"),
    "steal": ("stole", "stolen"),
    "stick": ("stuck", "stuck"),
    "sting": ("stung", "stung"),
    "stink": ("stank / stunk", "stunk"),
    "strew": ("strewed", "strewn / strewed"),
    "stride": ("strode", "stridden"),
    "strike": ("struck", "struck / stricken"),
    "string": ("strung", "strung"),
    "strive": ("strove / strived", "striven / strived"),
    "swear": ("swore", "sworn"),
    "sweep": ("swept", "swept"),
    "swell": ("swelled", "swollen / swelled"),
    "swim": ("swam", "swum"),
    "swing": ("swung", "swung"),
    "take": ("took", "taken"),
    "teach": ("taught", "taught"),
    "tear": ("tore", "torn"),
    "tell": ("told", "told"),
    "think": ("thought", "thought"),
    "thrive": ("throve / thrived", "thriven / thrived"),
    "throw": ("threw", "thrown"),
    "thrust": ("thrust", "thrust"),
    "tread": ("trod", "trodden / trod"),
    "unbend": ("unbent", "unbent"),
    "unbind": ("unbound", "unbound"),
    "underbid": ("underbid", "underbid"),
    "undercut": ("undercut", "undercut"),
    "undergo": ("underwent", "undergone"),
    "underlie": ("underlay", "underlain"),
    "undersell": ("undersold", "undersold"),
    "understand": ("understood", "understood"),
    "undertake": ("undertook", "undertaken"),
    "underwrite": ("underwrote", "underwritten"),
    "undo": ("undid", "undone"),
    "unfreeze": ("unfroze", "unfrozen"),
    "unwind": ("unwound", "unwound"),
    "uphold": ("upheld", "upheld"),
    "upset": ("upset", "upset"),
    "wake": ("woke", "woken"),
    "waylay": ("waylaid", "waylaid"),
    "wear": ("wore", "worn"),
    "weave": ("wove", "woven"),
    "wed": ("wedded / wed", "wedded / wed"),
    "weep": ("wept", "wept"),
    "wet": ("wet / wetted", "wet / wetted"),
    "win": ("won", "won"),
    "wind": ("wound", "wound"),
    "withdraw": ("withdrew", "withdrawn"),
    "withhold": ("withheld", "withheld"),
    "withstand": ("withstood", "withstood"),
    "wring": ("wrung", "wrung"),
    "write": ("wrote", "written"),
}

# 有歧义的动词：卡片上额外提示
IRREGULAR_VERB_NOTES: dict[str, str] = {
    "bear": "出生义过去分词用 born（be born），其余用 borne",
    "hang": "悬挂义 hung；绞死义 hanged",
    "lie": "躺/位于义 lay-lain；说谎义规则变化 lied-lied",
    "shine": "发光义 shone；擦亮义 shined",
    "wind": "缠绕义 wound；上发条义也可规则加 -ed",
}

# 自建不规则名词复数表（考研常见）
IRREGULAR_NOUNS: dict[str, str] = {
    "analysis": "analyses",
    "axis": "axes",
    "basis": "bases",
    "crisis": "crises",
    "diagnosis": "diagnoses",
    "emphasis": "emphases",
    "hypothesis": "hypotheses",
    "oasis": "oases",
    "parenthesis": "parentheses",
    "synopsis": "synopses",
    "synthesis": "syntheses",
    "thesis": "theses",
    "bacterium": "bacteria",
    "curriculum": "curricula / curriculums",
    "datum": "data",
    "medium": "media / mediums",
    "memorandum": "memoranda / memorandums",
    "phenomenon": "phenomena",
    "stratum": "strata",
    "criterion": "criteria",
    "alumnus": "alumni",
    "cactus": "cacti / cactuses",
    "fungus": "fungi / funguses",
    "nucleus": "nuclei",
    "radius": "radii / radiuses",
    "stimulus": "stimuli",
    "syllabus": "syllabi / syllabuses",
    "appendix": "appendices / appendixes",
    "index": "indices / indexes",
    "matrix": "matrices",
    "vertex": "vertices",
    "vortex": "vortices",
    "formula": "formulae / formulas",
    "larva": "larvae",
    "vertebra": "vertebrae",
    "child": "children",
    "foot": "feet",
    "goose": "geese",
    "louse": "lice",
    "man": "men",
    "mouse": "mice",
    "ox": "oxen",
    "person": "people / persons",
    "tooth": "teeth",
    "woman": "women",
    "aircraft": "aircraft",
    "corps": "corps",
    "crossroads": "crossroads",
    "deer": "deer",
    "fish": "fish / fishes",
    "headquarters": "headquarters",
    "means": "means",
    "offspring": "offspring",
    "salmon": "salmon",
    "series": "series",
    "sheep": "sheep",
    "spacecraft": "spacecraft",
    "species": "species",
    "swine": "swine",
    "trout": "trout",
}

# 自建不规则形容词/副词比较级表：word -> (比较级, 最高级)
IRREGULAR_ADJ: dict[str, tuple[str, str]] = {
    "good": ("better", "best"),
    "well": ("better", "best"),
    "bad": ("worse", "worst"),
    "badly": ("worse", "worst"),
    "ill": ("worse", "worst"),
    "far": ("farther / further", "farthest / furthest"),
    "little": ("less", "least"),
    "many": ("more", "most"),
    "much": ("more", "most"),
    "old": ("older / elder", "oldest / eldest"),
    "late": ("later / latter", "latest / last"),
}

# ---------------------------------------------------------------------------
# 规则变化的辅助数据
# ---------------------------------------------------------------------------

# 多音节但重音在末音节，需要双写尾辅音
_MULTISYLL_DOUBLE = {
    "abet", "acquit", "admit", "allot", "begin", "commit", "compel",
    "concur", "confer", "control", "defer", "deter", "dispel", "emit",
    "equip", "expel", "forbid", "forget", "format", "incur", "infer",
    "kidnap", "occur", "omit", "outbid", "patrol", "permit", "prefer",
    "propel", "rebel", "recur", "refer", "regret", "repel", "submit",
    "transmit", "underbid", "upset",
}

# 注意：travel/cancel/label 等 -l 结尾词按美式拼写不双写（traveling/canceled），
# 英式（travelling/cancelled）需要时由调用方自行处理。

# 以 -c 结尾加 -k 再变化
_C_VERBS = {"panic", "picnic", "mimic", "traffic", "frolic", "critic"}

# 现在分词保留 e 的词
_KEEP_E = {
    "be", "see", "flee", "agree", "free", "knee", "dye", "singe", "tinge",
    "hoe", "toe", "canoe",
}

# 名词 -f/-fe -> -ves
_F_TO_VES = {
    "calf", "elf", "half", "knife", "leaf", "life", "loaf", "self", "sheaf",
    "shelf", "thief", "wife", "wolf", "wharf",
}

# 名词 -o -> -oes
_O_TO_OES = {
    "echo", "embargo", "hero", "mosquito", "potato", "tomato", "torpedo",
    "veto", "volcano",
}

# -ch 读 /k/ 时只加 -s
_CH_HARD = {"epoch", "monarch", "patriarch", "stomach", "tech"}


def _syllables(word: str) -> int:
    return len(re.findall(r"[aeiouy]+", word))


def _ends_cvc(word: str) -> bool:
    """单音节 CVC 结尾（w/x/y 除外，qu 的 u 视为辅音）。"""
    if len(word) < 3:
        return False
    if word[-1] in "wxy" or word[-1] in VOWELS:
        return False
    if word[-2] not in VOWELS:
        return False
    third = word[-3]
    if word.endswith("qu" + word[-1]):
        return True
    # quit / quiz / squat：qu 里的 u 不是音节核心，按 CVC 处理
    if word[-4:-2] == "qu" and word[-2] in VOWELS:
        return True
    return third not in VOWELS


def _needs_double(word: str) -> bool:
    if word in _MULTISYLL_DOUBLE:
        return True
    return _syllables(word) == 1 and _ends_cvc(word)


def _add_ed(word: str) -> str:
    if word in _C_VERBS:
        return word + "ked"
    if word.endswith("e"):
        return word + "d"
    if word.endswith("y") and len(word) > 1 and word[-2] not in VOWELS:
        return word[:-1] + "ied"
    if _needs_double(word):
        return word + word[-1] + "ed"
    return word + "ed"


def _add_ing(word: str) -> str:
    if word.endswith("ie"):
        return word[:-2] + "ying"
    if word in _KEEP_E or word.endswith("ee") or word.endswith("oe"):
        return word + "ing"
    if word in _C_VERBS:
        return word + "king"
    if word.endswith("e"):
        return word[:-1] + "ing"
    if _needs_double(word):
        return word + word[-1] + "ing"
    return word + "ing"


def _add_s(word: str) -> str:
    if word == "be":
        return "is"
    if word == "have":
        return "has"
    if word.endswith(("s", "x", "z", "ch", "sh")):
        if word in _CH_HARD:
            return word + "s"
        return word + "es"
    if word.endswith("o"):
        return word + "es"
    if word.endswith("y") and len(word) > 1 and word[-2] not in VOWELS:
        return word[:-1] + "ies"
    return word + "s"


def _add_er(word: str) -> str:
    if word.endswith("e"):
        return word + "r"
    if word.endswith("y") and len(word) > 1 and word[-2] not in VOWELS:
        return word[:-1] + "ier"
    if _needs_double(word):
        return word + word[-1] + "er"
    return word + "er"


def _add_est(word: str) -> str:
    if word.endswith("e"):
        return word + "st"
    if word.endswith("y") and len(word) > 1 and word[-2] not in VOWELS:
        return word[:-1] + "iest"
    if _needs_double(word):
        return word + word[-1] + "est"
    return word + "est"


def _plural(word: str) -> str:
    if word in _F_TO_VES:
        return word[:-2] + "ves" if word.endswith("fe") else word[:-1] + "ves"
    if word.endswith("y") and len(word) > 1 and word[-2] not in VOWELS:
        return word[:-1] + "ies"
    if word.endswith(("s", "x", "z", "ch", "sh")):
        if word in _CH_HARD:
            return word + "s"
        return word + "es"
    if word.endswith("o"):
        return word + "es" if word in _O_TO_OES else word + "s"
    return word + "s"


def _comparative(word: str) -> str:
    if word.endswith("y") and len(word) > 1 and word[-2] not in VOWELS:
        return word[:-1] + "ier"
    if _syllables(word) <= 1:
        return _add_er(word)
    if _syllables(word) == 2 and word.endswith(("le", "ow", "er")):
        return _add_er(word)
    return "more " + word


def _superlative(word: str) -> str:
    if word.endswith("y") and len(word) > 1 and word[-2] not in VOWELS:
        return word[:-1] + "iest"
    if _syllables(word) <= 1:
        return _add_est(word)
    if _syllables(word) == 2 and word.endswith(("le", "ow", "er")):
        return _add_est(word)
    return "most " + word


# ---------------------------------------------------------------------------
# 词性解析
# ---------------------------------------------------------------------------
_POS_ALIASES = {
    "v": "v", "vt": "v", "vi": "v", "verb": "v",
    "n": "n", "noun": "n",
    "adj": "adj", "a": "adj", "adjective": "adj",
    "adv": "adv", "ad": "adv", "adverb": "adv",
    "prep": "prep", "conj": "conj", "pron": "pron", "num": "num",
    "art": "art", "int": "int", "interj": "int",
}


def parse_pos(pos: str | None) -> list[str]:
    """'v./n.' -> ['v', 'n']；'adj.' -> ['adj']。"""
    if not pos:
        return []
    out: list[str] = []
    for token in re.split(r"[/,、\s]+", pos):
        token = token.strip().strip(".").lower()
        if not token:
            continue
        token = _POS_ALIASES.get(token, token)
        if token in {"v", "n", "adj", "adv"} and token not in out:
            out.append(token)
    return out


def guess_pos(word: str, meaning: str | None = None) -> str | None:
    """从释义开头或词尾猜一个主词性，供 pos 缺失时兜底。"""
    if meaning:
        m = re.match(r"\s*(adj|adv|n|v|vt|vi|prep|conj|pron|num|art|int)\.", meaning)
        if m:
            token = _POS_ALIASES.get(m.group(1).lower())
            if token in {"v", "n", "adj", "adv"}:
                return token
    w = word.lower()
    if w.endswith(("tion", "sion", "ment", "ness", "ity", "ance", "ence",
                   "ship", "ism", "ist", "hood", "age", "ure", "cy")):
        return "n"
    if w.endswith(("ize", "ise", "ify", "ate", "en")):
        return "v"
    if w.endswith("ly"):
        return "adv"
    if w.endswith(("ous", "ful", "less", "able", "ible", "ive", "al", "ic")):
        return "adj"
    return None


# ---------------------------------------------------------------------------
# 对外 API
# ---------------------------------------------------------------------------
def verb_forms(word: str) -> dict[str, str]:
    word = word.lower()
    if word in IRREGULAR_VERBS:
        past, pp = IRREGULAR_VERBS[word]
    else:
        past = _add_ed(word)
        pp = past
    return {
        "past": past,
        "pp": pp,
        "3sg": _add_s(word),
        "ing": _add_ing(word),
    }


def noun_forms(word: str) -> dict[str, str]:
    word = word.lower()
    return {"plural": IRREGULAR_NOUNS.get(word, _plural(word))}


def adj_forms(word: str) -> dict[str, str]:
    word = word.lower()
    if word in IRREGULAR_ADJ:
        comp, sup = IRREGULAR_ADJ[word]
        return {"comparative": comp, "superlative": sup}
    return {"comparative": _comparative(word), "superlative": _superlative(word)}


def forms(word: str, pos: str | None = None) -> dict[str, str]:
    """按词性返回变形；pos 为空时返回 {}。"""
    if not word:
        return {}
    out: dict[str, str] = {}
    for p in parse_pos(pos):
        if p == "v":
            out.update(verb_forms(word))
        elif p == "n":
            out.update(noun_forms(word))
        elif p in {"adj", "adv"}:
            out.update(adj_forms(word))
    return out


def is_irregular(word: str, pos: str | None = None) -> dict[str, bool]:
    """每个变形是否来自不规则表（即「值得在卡片上单独标出」）。"""
    word = (word or "").lower()
    out: dict[str, bool] = {}
    for p in parse_pos(pos):
        if p == "v":
            hit = word in IRREGULAR_VERBS
            out.update({"past": hit, "pp": hit,
                        "3sg": word in {"be", "have"},
                        "ing": word in {"be", "see", "agree", "dye", "singe"}})
        elif p == "n":
            out.update({"plural": word in IRREGULAR_NOUNS})
        elif p in {"adj", "adv"}:
            hit = word in IRREGULAR_ADJ
            out.update({"comparative": hit, "superlative": hit})
    return out


def irregular_forms(word: str, pos: str | None = None) -> dict[str, str]:
    """forms() 的子集，只保留不规则项。"""
    all_forms = forms(word, pos)
    flags = is_irregular(word, pos)
    return {k: v for k, v in all_forms.items() if flags.get(k)}


def split_forms(value: str) -> list[str]:
    return [v.strip() for v in value.split("/") if v.strip()]


# ---------------------------------------------------------------------------
# 抽查校验（python3 inflect.py）
# ---------------------------------------------------------------------------
_SELF_TESTS: list[tuple[str, str, str, str]] = [
    # (word, pos, key, expected)
    ("strive", "v", "past", "strove / strived"),
    ("strive", "v", "pp", "striven / strived"),
    ("bear", "v", "past", "bore"),
    ("bear", "v", "pp", "borne"),
    ("forbid", "v", "pp", "forbidden"),
    ("go", "v", "past", "went"),
    ("go", "v", "3sg", "goes"),
    ("go", "v", "ing", "going"),
    ("lie", "v", "pp", "lain"),
    ("stop", "v", "past", "stopped"),
    ("stop", "v", "ing", "stopping"),
    ("carry", "v", "past", "carried"),
    ("play", "v", "past", "played"),
    ("make", "v", "ing", "making"),
    ("visit", "v", "ing", "visiting"),
    ("prefer", "v", "past", "preferred"),
    ("begin", "v", "ing", "beginning"),
    ("forbid", "v", "ing", "forbidding"),
    ("travel", "v", "ing", "traveling"),
    ("panic", "v", "past", "panicked"),
    ("die", "v", "ing", "dying"),
    ("quit", "v", "ing", "quitting"),
    ("quiz", "v", "past", "quizzed"),
    ("squat", "v", "ing", "squatting"),
    ("crisis", "n", "plural", "crises"),
    ("phenomenon", "n", "plural", "phenomena"),
    ("medium", "n", "plural", "media / mediums"),
    ("child", "n", "plural", "children"),
    ("leaf", "n", "plural", "leaves"),
    ("roof", "n", "plural", "roofs"),
    ("photo", "n", "plural", "photos"),
    ("potato", "n", "plural", "potatoes"),
    ("good", "adj", "comparative", "better"),
    ("far", "adj", "superlative", "farthest / furthest"),
    ("happy", "adj", "comparative", "happier"),
    ("careful", "adj", "comparative", "more careful"),
]


def _self_test() -> None:
    failed = 0
    for word, pos, key, expected in _SELF_TESTS:
        got = forms(word, pos).get(key)
        if got != expected:
            failed += 1
            print(f"FAIL {word} [{pos}] {key}: {got!r} != {expected!r}")
    # is_irregular 抽查
    checks = [
        (is_irregular("strive", "v")["past"] is True, "strive irregular"),
        (is_irregular("work", "v")["past"] is False, "work regular"),
        (is_irregular("crisis", "n")["plural"] is True, "crisis irregular"),
        (is_irregular("good", "adj")["comparative"] is True, "good irregular"),
        (irregular_forms("strive", "v").keys() == {"past", "pp"}, "irregular_forms subset"),
    ]
    for ok, label in checks:
        if not ok:
            failed += 1
            print(f"FAIL {label}")
    print(f"self-test: {len(_SELF_TESTS) + len(checks) - failed} passed, {failed} failed")
    print(f"tables: {len(IRREGULAR_VERBS)} verbs, {len(IRREGULAR_NOUNS)} nouns, "
          f"{len(IRREGULAR_ADJ)} adjectives")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    _self_test()
