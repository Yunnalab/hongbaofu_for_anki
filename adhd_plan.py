#!/usr/bin/env python3
"""把红宝书牌组的「背诵计划」改成 ADHD 友好档：只改牌组选项，不动牌组结构、不动卡片。

改的是牌组选项预设「ADHD · 20分钟」：
  新词 8/天 · 复习 150/天 · 目标记忆率 0.85 · 最长间隔 180 天
  学习步长 1m/10m · 答错重学 10m · 顽固词 4 次打标签（不自动暂停）
  显示计时器 · 不自动藏卡 · 新词混在复习里

为什么这么改（现状数据）：现在实际每天进 100+ 新词（因为 56 个单元牌组各给
40 新词/400 复习，上限按牌组算，不汇总），日均 450~650 次复习，接近一半按
「忘记」。ADHD 友好的核心是「今天的量是有限且可预期的」，所以把单牌组配额
压到 10~20 分钟能做完的规模。

用法：
    python3 adhd_plan.py --dry-run        # 在 /tmp 副本上演练
    python3 adhd_plan.py                  # 真正写入（会先备份 collection）
    python3 adhd_plan.py --tier low       # 低电量档：新词 3 / 复习 60
    python3 adhd_plan.py --tier sprint    # 冲刺档：新词 20 / 复习 200
"""
from __future__ import annotations

import argparse
import glob
import os
import shutil
import sqlite3
import subprocess
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
ANKI_DIR = os.path.expanduser("~/.local/share/Anki2")
COLLECTION = os.path.join(ANKI_DIR, "账户 1", "collection.anki2")
PREFS = os.path.join(ANKI_DIR, "prefs21.db")
BACKUP_ROOT = os.path.join(BASE, "backups")

PRESET_NAME = "ADHD · 20分钟"
TIERS = {
    "low": {"new_per_day": 3, "reviews_per_day": 60, "label": "低电量"},
    "std": {"new_per_day": 8, "reviews_per_day": 150, "label": "标准"},
    "sprint": {"new_per_day": 20, "reviews_per_day": 200, "label": "冲刺"},
}

BASE_SETTINGS = {
    "desired_retention": 0.85,       # 比默认 0.9 轻，复习量约降 15%
    "maximum_review_interval": 180,  # 不排到一年后，单词不会「消失」太久
    "leech_threshold": 4,            # 4 次忘记就标记，早暴露问题词
    "leech_action": "TAG_ONLY",      # 只打标签不自动暂停（暂停很像惩罚）
    "show_timer": True,              # 看得见秒数，防止一张卡磨 1 分钟
    "bury_new": False,               # 不自动藏卡，数量可预期
    "bury_reviews": False,
    "learn_steps": [1.0, 10.0],      # 1 分钟、10 分钟：答错的代价很低
    "relearn_steps": [10.0],
    "new_per_day_minimum": 0,
    "minimum_lapse_interval": 1,
    "cap_answer_time_to_secs": 60,
    "new_mix": "MIX_WITH_REVIEWS",   # 新词混在复习中间
}


# ---------------------------------------------------------------- anki protobuf
def find_anki_site_packages() -> str:
    """在 /nix/store 里找到 anki 自带的 python 包（含 protobuf 定义）。"""
    pats = [
        f"/nix/store/*-anki-*-lib/lib/python3.{sys.version_info.minor}/site-packages",
        "/nix/store/*-anki-*-lib/lib/python3.*/site-packages",
    ]
    for pat in pats:
        for cand in sorted(glob.glob(pat)):
            if os.path.exists(os.path.join(cand, "anki", "deck_config_pb2.py")):
                return cand
    sys.exit(
        "找不到 anki 的 python 包（需要 /nix/store/*-anki-*/lib/python3.*/site-packages）。\n"
        "请确认系统里有 anki：nix shell nixpkgs#anki"
    )


sys.path.insert(0, find_anki_site_packages())
import anki.decks_pb2 as decks_pb  # noqa: E402
from anki.deck_config_pb2 import DeckConfig  # noqa: E402


# ---------------------------------------------------------------- helpers
def anki_running() -> bool:
    try:
        out = subprocess.run(
            ["pgrep", "-f", r"/bin/anki($| )"], capture_output=True, text=True
        )
        return out.returncode == 0 and bool(out.stdout.strip())
    except FileNotFoundError:
        return False


def backup(files: list[str]) -> str:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = os.path.join(BACKUP_ROOT, f"anki-{stamp}")
    os.makedirs(dest, exist_ok=True)
    for f in files:
        if os.path.exists(f):
            shutil.copy2(f, os.path.join(dest, os.path.basename(f)))
    return dest


def now_ms() -> int:
    return int(time.time() * 1000)


def now_secs() -> int:
    return int(time.time())


def set_field(cfg, name: str, value) -> None:
    field = DeckConfig.Config.DESCRIPTOR.fields_by_name[name]
    if field.enum_type is not None:
        if isinstance(value, int):
            setattr(cfg, name, value)
            return
        names = {v.name: v.number for v in field.enum_type.values}
        for cand in (value, f"LEECH_ACTION_{value}", f"REVIEW_MIX_{value}"):
            if cand in names:
                setattr(cfg, name, names[cand])
                return
        raise KeyError(f"未知枚举值 {value}（可选：{sorted(names)}）")
    if field.is_repeated:
        container = getattr(cfg, name)
        container.clear()
        container.extend(value)
        return
    setattr(cfg, name, value)


def red_book_decks(cur) -> list[tuple[int, str]]:
    cur.execute("SELECT id, name FROM decks")
    return [(i, n.replace("\x1f", "::")) for i, n in cur.fetchall() if "红宝" in n]


def ensure_preset(cur, tier: dict) -> int:
    """返回预设 id：已存在就更新，否则从默认预设复制后覆盖关键项。"""
    cur.execute("SELECT id, name, config FROM deck_config")
    rows = cur.fetchall()
    preset_id = None
    for pid, name, blob in rows:
        if name == PRESET_NAME:
            cfg = DeckConfig.Config()
            cfg.ParseFromString(blob)
            preset_id = pid
            break
    else:
        cur.execute("SELECT config FROM deck_config WHERE id = 1")
        row = cur.fetchone()
        cfg = DeckConfig.Config()
        cfg.ParseFromString(row[0])
        preset_id = max(now_ms(), max((r[0] for r in rows), default=0) + 1)

    for k, v in BASE_SETTINGS.items():
        set_field(cfg, k, v)
    set_field(cfg, "new_per_day", tier["new_per_day"])
    set_field(cfg, "reviews_per_day", tier["reviews_per_day"])

    blob = cfg.SerializeToString()
    if any(r[0] == preset_id for r in rows):
        cur.execute(
            "UPDATE deck_config SET name=?, mtime_secs=?, usn=-1, config=? WHERE id=?",
            (PRESET_NAME, now_secs(), blob, preset_id),
        )
    else:
        cur.execute(
            "INSERT INTO deck_config (id, name, mtime_secs, usn, config) VALUES (?,?,?,?,?)",
            (preset_id, PRESET_NAME, now_secs(), -1, blob),
        )
    return preset_id


def assign_preset(cur, deck_ids: list[int], preset_id: int) -> int:
    """把指定牌组的选项预设换成 preset_id，返回实际改动数。"""
    changed = 0
    for did in deck_ids:
        cur.execute("SELECT kind FROM decks WHERE id=?", (did,))
        row = cur.fetchone()
        if row is None:
            continue
        k = decks_pb.Deck.KindContainer()
        k.ParseFromString(row[0] or b"")
        if not k.HasField("normal") or k.normal.config_id == preset_id:
            continue
        k.normal.config_id = preset_id
        cur.execute(
            "UPDATE decks SET kind=?, mtime_secs=?, usn=-1 WHERE id=?",
            (k.SerializeToString(), now_secs(), did),
        )
        changed += 1
    return changed


def summarize(cur) -> None:
    cur.execute("SELECT id, name, kind FROM decks")
    rows = cur.fetchall()
    cur.execute("SELECT id, name, config FROM deck_config")
    presets = {pid: (name, blob) for pid, name, blob in cur.fetchall()}
    used = {}
    for did, name, kind in rows:
        if "红宝" not in name:
            continue
        k = decks_pb.Deck.KindContainer()
        k.ParseFromString(kind or b"")
        cid = k.normal.config_id if k.HasField("normal") else None
        used.setdefault(cid, 0)
        used[cid] += 1
    print("\n— 红宝书牌组使用的选项预设 —")
    for cid, n in used.items():
        pname = presets.get(cid, ("<缺失>", b""))[0]
        print(f"  {n:3d} 个牌组 → 「{pname}」")
    for pid, (name, blob) in presets.items():
        if name != PRESET_NAME:
            continue
        cfg = DeckConfig.Config()
        cfg.ParseFromString(blob)
        print(
            f"\n  预设「{name}」: 新词/天 {cfg.new_per_day} · 复习/天 {cfg.reviews_per_day} · "
            f"目标记忆率 {cfg.desired_retention:.2f} · 最长间隔 {cfg.maximum_review_interval} 天 · "
            f"学习步长 {list(cfg.learn_steps)} / 重学 {list(cfg.relearn_steps)} 分钟 · "
            f"顽固词阈值 {cfg.leech_threshold} ({cfg.leech_action})"
        )


# ---------------------------------------------------------------- main
def main() -> None:
    ap = argparse.ArgumentParser(description="把红宝书牌组的背诵计划调成 ADHD 友好档")
    ap.add_argument("--tier", choices=list(TIERS), default="std", help="每日强度档位")
    ap.add_argument("--db", default=COLLECTION, help="collection.anki2 路径")
    ap.add_argument("--dry-run", action="store_true", help="在 /tmp 副本上演练，不动真实数据")
    ap.add_argument("--force", action="store_true", help="即使 Anki 正在运行也强行写入")
    args = ap.parse_args()

    if not os.path.exists(args.db):
        sys.exit(f"找不到 {args.db}")

    db = args.db
    if args.dry_run:
        db = "/tmp/adhd_plan_dryrun.anki2"
        shutil.copy2(args.db, db)
        print(f"[dry-run] 使用副本 {db}")
    else:
        if anki_running() and not args.force:
            sys.exit("Anki 正在运行，请先完全退出（否则会覆盖改动）。")
        dest = backup([args.db, PREFS])
        print(f"已备份到 {dest}")

    tier = TIERS[args.tier]
    conn = sqlite3.connect(db)
    # Anki 的 schema 用自定义的 unicase 排序规则（名字唯一索引）
    conn.create_collation(
        "unicase",
        lambda a, b: (a.casefold() > b.casefold()) - (a.casefold() < b.casefold()),
    )
    cur = conn.cursor()

    preset_id = ensure_preset(cur, tier)
    decks = red_book_decks(cur)
    changed = assign_preset(cur, [i for i, _ in decks], preset_id)
    cur.execute("UPDATE col SET mod=? WHERE id=1", (now_ms(),))
    conn.commit()

    print(
        f"\n预设「{PRESET_NAME}」({tier['label']}档) 已就绪，id={preset_id}；"
        f"红宝书牌组 {len(decks)} 个，本次改动 {changed} 个（其余本来就是这个预设）"
    )
    summarize(cur)

    cur.execute("PRAGMA integrity_check")
    print("\nintegrity_check:", cur.fetchone()[0])
    conn.close()

    if args.dry_run:
        print("\n[dry-run] 真实 collection 未改动。确认无误后去掉 --dry-run 再跑一次。")


if __name__ == "__main__":
    main()
