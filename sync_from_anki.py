#!/usr/bin/env python3
"""从本地 Anki 数据库提取修正，同步回 all_entries_v2.json 并重新生成 apkg"""
import json
import re
import os
import hashlib
import sqlite3
import shutil
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
ANKI_DB = os.path.expanduser("~/.local/share/Anki2/账户 1/collection.anki2")
SRC_JSON = os.path.join(BASE, "all_entries_v2.json")
SYNC_STATE = os.path.join(BASE, ".sync_state.json")


def extract_back(back):
    no_phonetic = re.sub(r'\[.*?\]\s*<br>', '', back, count=1)
    meaning = ''
    mnemonic = ''
    if '【助记】' in no_phonetic:
        parts = no_phonetic.split('【助记】', 1)
        meaning = re.sub(r'\s+', ' ', parts[0].replace('<br>', ' ').replace('<br/>', ' ')).strip()
        mnemonic = parts[1].strip()
    else:
        meaning = re.sub(r'\s+', ' ', no_phonetic.replace('<br>', ' ').replace('<br/>', ' ')).strip()
    return meaning, mnemonic


def load_anki_notes():
    tmp_db = "/tmp/collection_sync.anki2"
    shutil.copy2(ANKI_DB, tmp_db)
    conn = sqlite3.connect(tmp_db)
    cur = conn.cursor()

    cur.execute("SELECT id, name FROM decks")
    deck_ids = [str(d[0]) for d in cur.fetchall() if '红宝' in d[1]]

    if not deck_ids:
        conn.close()
        return {}

    placeholders = ','.join(['?'] * len(deck_ids))
    cur.execute(f"""
        SELECT DISTINCT n.id, n.flds
        FROM notes n
        JOIN cards c ON c.nid = n.id
        WHERE c.did IN ({placeholders})
    """, deck_ids)
    rows = cur.fetchall()
    conn.close()
    os.remove(tmp_db)

    notes = {}
    field_sep = '\x1f'
    for nid, flds in rows:
        parts = flds.split(field_sep)
        word = parts[0].strip().lower() if len(parts) > 0 else ''
        back = parts[1] if len(parts) > 1 else ''
        notes[word] = back
    return notes


def hash_content(s):
    return hashlib.md5(s.encode()).hexdigest()


def load_state():
    if os.path.exists(SYNC_STATE):
        with open(SYNC_STATE) as f:
            return json.load(f)
    return {}


def save_state(snapshot):
    with open(SYNC_STATE, 'w') as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)


def norm(s):
    return re.sub(r'\s+', '', str(s).replace('<br>', '').replace('<br/>', ''))


def compare():
    with open(SRC_JSON) as f:
        src = json.load(f)

    anki_notes = load_anki_notes()
    if not anki_notes:
        print("无法读取 Anki 数据，请确认 Anki 已导入牌组")
        return None, [], {}

    state = load_state()

    diffs = []
    anki_snapshot = {}

    for entry in src:
        word = entry['word'].strip().lower()
        src_meaning = entry.get('meaning', '')
        src_mnemonic = entry.get('mnemonic', '').replace('【助记】', '').strip()

        if word not in anki_notes:
            continue

        anki_back = anki_notes[word]
        anki_meaning, anki_mnemonic = extract_back(anki_back)
        anki_m = anki_mnemonic.replace('【助记】', '').strip()

        anki_snapshot[word] = {
            "meaning_hash": hash_content(anki_meaning),
            "mnemonic_hash": hash_content(anki_m),
        }

        meaning_changed = norm(src_meaning) != norm(anki_meaning)
        mnemonic_changed = norm(src_mnemonic) != norm(anki_m)

        if not meaning_changed and not mnemonic_changed:
            continue

        last = state.get(word, {})
        # 只有当 Anki 端的数据相比上次同步有变化时，才认为是新修改
        meaning_new = (hash_content(anki_meaning) != last.get("meaning_hash", ""))
        mnemonic_new = (hash_content(anki_mnemonic) != last.get("mnemonic_hash", ""))

        if (meaning_changed and meaning_new) or (mnemonic_changed and mnemonic_new):
            diffs.append({
                'word': entry['word'],
                'section': entry['section'],
                'unit': entry['unit'],
                'src_meaning': src_meaning,
                'anki_meaning': anki_meaning,
                'src_mnemonic': src_mnemonic,
                'anki_mnemonic': anki_m,
                'meaning_changed': meaning_changed and meaning_new,
                'mnemonic_changed': mnemonic_changed and mnemonic_new,
            })

    return src, diffs, anki_snapshot


def show_diff(diffs):
    if not diffs:
        return

    print(f"\n发现 {len(diffs)} 条新修改：\n")
    print(f"{'单词':<16} {'字段':<6} {'源文件':<45} {'Anki中':<45}")
    print("-" * 120)
    for d in diffs:
        if d['meaning_changed']:
            print(f"{d['word']:<16} {'释义':<6} {d['src_meaning'][:42]:<45} {d['anki_meaning'][:42]:<45}")
        if d['mnemonic_changed']:
            print(f"{d['word']:<16} {'助记':<6} {d['src_mnemonic'][:42]:<45} {d['anki_mnemonic'][:42]:<45}")


def apply(diffs, src):
    word_map = {e['word'].strip().lower(): e for e in src}
    for d in diffs:
        w = d['word'].strip().lower()
        if w in word_map:
            if d['meaning_changed']:
                word_map[w]['meaning'] = d['anki_meaning']
            if d['mnemonic_changed']:
                word_map[w]['mnemonic'] = d['anki_mnemonic']

    with open(SRC_JSON, 'w') as f:
        json.dump(src, f, ensure_ascii=False, indent=2)
    print(f"已更新 {SRC_JSON}")


def regenerate():
    import subprocess
    script = os.path.join(BASE, "generate_anki_decks.py")
    result = subprocess.run(["python3", script], capture_output=True, text=True)
    print(result.stdout)
    if result.returncode != 0:
        print(result.stderr)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--init":
        _, _, anki_snapshot = compare()
        if anki_snapshot:
            save_state(anki_snapshot)
            print(f"已建立基线 ({len(anki_snapshot)} 词)，下次运行只显示新修改")
        return

    auto_apply = len(sys.argv) > 1 and sys.argv[1] == "--yes"

    print("正在对比 Anki 数据库与源 JSON ...")
    src, diffs, anki_snapshot = compare()

    if src is None:
        return

    if not diffs:
        print("没有新修改")
        save_state(anki_snapshot)
        return

    show_diff(diffs)

    if auto_apply:
        choice = 'y'
    else:
        print(f"\n写入源 JSON？(y/n/r)")
        print("  y = 写入  n = 取消  r = 写入并重新生成 apkg")
        choice = input("> ").strip().lower()

    if choice.startswith('y') or choice.startswith('r'):
        apply(diffs, src)
        save_state(anki_snapshot)
        if choice.startswith('r'):
            print("正在重新生成 apkg ...")
            regenerate()
        print("同步完成")
    else:
        print("已取消")


if __name__ == "__main__":
    main()
