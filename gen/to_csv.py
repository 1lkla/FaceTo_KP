#!/usr/bin/env python3
"""把 validated.jsonl 转成刷题系统 CSV（UTF-8-BOM，Excel 兼容）。

列：题号,题干,A,B,C,D,E,答案,难度,题型,类别,解析
"""
import csv
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "questions"
IN_PATH = DATA_DIR / "validated.jsonl"
OUT_PATH = DATA_DIR / "output" / "questions.csv"

COLUMNS = ["题号", "题干", "A", "B", "C", "D", "E", "答案", "难度", "题型", "类别", "解析"]
OPTION_KEYS = ["A", "B", "C", "D", "E"]


def main():
    if not IN_PATH.exists():
        print(f"未找到 {IN_PATH}，先跑 validate.py")
        return
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    # utf-8-sig 写入 BOM，Excel 直接打开不乱码
    with OUT_PATH.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(COLUMNS)
        with IN_PATH.open(encoding="utf-8") as fin:
            for line in fin:
                if not line.strip():
                    continue
                item = json.loads(line)
                n += 1
                opts = item.get("options") or {}
                if item["type"] == "判断题":
                    opts = {"A": "对", "B": "错"}
                row = [
                    n,
                    item["question"],
                    *[opts.get(k, "") for k in OPTION_KEYS],
                    item["answer"],
                    item["difficulty"],
                    item["type"],
                    item.get("chapter", ""),
                    item.get("analysis", ""),
                ]
                writer.writerow(row)
    print(f"写出 {n} 题 -> {OUT_PATH}")


if __name__ == "__main__":
    main()
