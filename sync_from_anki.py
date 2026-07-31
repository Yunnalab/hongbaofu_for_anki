#!/usr/bin/env python3
"""从本地 Anki 数据库提取修正，同步回 all_entries_v2.json 并重新生成 apkg"""
import json
import re
import os
import sqlite3
import shutil
import sys

ANKI_DB = os.path.expanduser("~/.local/share/Anki2/账户 1/collection.anki2")
SRC_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "all_entries_v2.json")
DIFF_FILE = "/tmp/anki_sync_diff.json"


def extract_back(back):
    """从 Anki back 字段中分离释义和助记"""
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
    """从 Anki 数据库加载红宝书牌组的笔记"""
    tmp_db = "/tmp/collection_sync.anki2"
    shutil.copy2(ANKI_DB, tmp_db)
    conn = sqlite3.connect(tmp_db)
    cur = conn.cursor()

    cur.execute("SELECT id, name FROM decks")
    deck_ids = [str(d[0]) for d in cur.fetchall() if '红宝' in d[1]]

    if not deck_ids:
        print("未找到红宝书牌组")
        conn.close()
        return []

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


def norm(s):
    return re.sub(r'\s+', '', str(s).replace('<br>', '').replace('<br/>', ''))


def compare():
    with open(SRC_JSON) as f:
        src = json.load(f)

    anki_notes = load_anki_notes()
    if not anki_notes:
        print("无法读取 Anki 数据，请确认 Anki 已导入牌组")
        return

    diffs = []
    for entry in src:
        word = entry['word'].strip().lower()
        src_meaning = entry.get('meaning', '')
        src_mnemonic = entry.get('mnemonic', '')

        if word not in anki_notes:
            continue

        anki_back = anki_notes[word]
        anki_meaning, anki_mnemonic = extract_back(anki_back)

        # 仅比较内容，去除【助记】前缀
        src_m = src_mnemonic.replace('【助记】', '').strip()
        anki_m = anki_mnemonic.replace('【助记】', '').strip()

        meaning_changed = norm(src_meaning) != norm(anki_meaning)
        mnemonic_changed = norm(src_m) != norm(anki_m)

        if meaning_changed or mnemonic_changed:
            diffs.append({
                'word': entry['word'],
                'section': entry['section'],
                'unit': entry['unit'],
                'src_meaning': src_meaning,
                'anki_meaning': anki_meaning,
                'src_mnemonic': src_mnemonic,
                'anki_mnemonic': anki_m,
                'meaning_changed': meaning_changed,
                'mnemonic_changed': mnemonic_changed,
            })

    return src, diffs


def show_diff(diffs):
    if not diffs:
        print("没有发现修改")
        return

    print(f"\n发现 {len(diffs)} 条变化：\n")
    print(f"{'单词':<16} {'字段':<6} {'原文':<45} {'修改后':<45}")
    print("-" * 120)
    for d in diffs:
        if d['meaning_changed']:
            src_t = d['src_meaning'][:42]
            anki_t = d['anki_meaning'][:42]
            print(f"{d['word']:<16} {'释义':<6} {src_t:<45} {anki_t:<45}")
        if d['mnemonic_changed']:
            src_t = d['src_mnemonic'][:42]
            anki_t = d['anki_mnemonic'][:42]
            print(f"{d['word']:<16} {'助记':<6} {src_t:<45} {anki_t:<45}")

    with open(DIFF_FILE, 'w') as f:
        json.dump(diffs, f, ensure_ascii=False, indent=2)


def apply(diffs, src):
    """将修改写入源 JSON"""
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
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "generate_anki_decks.py")
    result = subprocess.run(["python3", script], capture_output=True, text=True)
    print(result.stdout)
    if result.returncode != 0:
        print(result.stderr)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--yes":
        auto_apply = True
    else:
        auto_apply = False

    print("正在对比 Anki 数据库与源 JSON ...")
    src, diffs = compare()

    if not diffs:
        print("源 JSON 与 Anki 数据库一致，无需同步")
        return

    show_diff(diffs)

    if auto_apply:
        choice = 'y'
    else:
        print(f"\n是否将以上 {len(diffs)} 条修改写入源 JSON？(y/n/r)")
        print("  y = 写入源 JSON")
        print("  n = 取消")
        print("  r = 写入并重新生成 apkg")
        choice = input("> ").strip().lower()

    if choice.startswith('y') or choice.startswith('r'):
        apply(diffs, src)
        if choice.startswith('r'):
            print("正在重新生成 apkg 文件...")
            regenerate()
    else:
        print("已取消")
        print(f"差异文件已保存到 {DIFF_FILE}")


if __name__ == "__main__":
    main()
