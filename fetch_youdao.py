#!/usr/bin/env python3
"""从有道词典 API 补全缺失的单词释义"""
import json
import time
import urllib.request
import urllib.parse
import sys

JSON_PATH = "/home/cloudygirl/Anki红宝书/all_entries_v2.json"
PROGRESS_PATH = "/tmp/opencode/fetch_progress.log"


def fetch_word(word: str) -> dict | None:
    """查询有道词典，返回 {meaning, pos, usphone}"""
    dicts = urllib.parse.quote('{"count":99,"dicts":[["ec"]]}')
    url = f"https://dict.youdao.com/jsonapi?xmlVersion=5.1&dicts={dicts}&q={urllib.parse.quote(word)}"
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
    except Exception:
        return None

    ec = data.get("ec", {}).get("word")
    if not ec:
        return None

    w = ec[0] if isinstance(ec, list) else ec
    trs = w.get("trs", [])

    # 收集所有释义行
    lines = []
    for tr in trs:
        for item in tr.get("tr", []):
            for s in item.get("l", {}).get("i", []):
                s = s.strip()
                if s:
                    lines.append(s)
    if not lines:
        return None

    # 从首条释义提取词性（如 "adj. xxx"）
    pos = ""
    first = lines[0]
    if ". " in first or first.endswith("."):
        head = first.split(" ", 1)[0].rstrip(".")
        if 1 <= len(head) <= 12 and head.replace(" ", "").isalpha():
            pos = head + "."

    return {
        "meaning": "；".join(lines),
        "pos": pos,
        "usphone": w.get("usphone", ""),
    }


def main():
    with open(JSON_PATH) as f:
        entries = json.load(f)

    targets = [(i, e) for i, e in enumerate(entries) if not e.get("meaning", "").strip()]
    total = len(targets)
    print(f"待抓取: {total}", flush=True)

    ok = fail = 0
    for n, (i, entry) in enumerate(targets, 1):
        word = entry["word"]
        result = fetch_word(word)
        if result:
            entry["meaning"] = result["meaning"]
            if result["pos"] and not entry.get("pos", "").strip():
                entry["pos"] = result["pos"]
            if result["usphone"] and not entry.get("phonetic", "").strip():
                entry["phonetic"] = result["usphone"]
            ok += 1
            status = "OK"
        else:
            fail += 1
            status = "FAIL"

        if n % 20 == 0 or status == "FAIL":
            msg = f"[{n}/{total}] ok={ok} fail={fail} last={word}:{status}"
            print(msg, flush=True)
            with open(PROGRESS_PATH, "a") as pf:
                pf.write(msg + "\n")

        time.sleep(0.3)

    with open(JSON_PATH, "w") as f:
        json.dump(entries, f, ensure_ascii=False, indent=1)

    print(f"完成: ok={ok} fail={fail}", flush=True)


if __name__ == "__main__":
    main()
