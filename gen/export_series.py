#!/usr/bin/env python3
"""合并 v1 题库与专题系列题库，导出 CSV。

输出：
  data/questions/validated_full.jsonl      合并后的完整题库（JSONL）
  data/questions/output/questions.csv      全量题库 CSV（题号 1..N，全新库导入用）
  data/questions/output/series_questions.csv  仅专题系列 CSV（增量导入线上库用，
                                           题号从 --start-id 开始，默认 2943）
"""
import argparse
import csv
import hashlib
import json
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "questions"
OUT_DIR = DATA_DIR / "output"
V1_CLEAN_PATH = DATA_DIR / "validated_v1_clean.jsonl"
SERIES_PATH = DATA_DIR / "series_validated.jsonl"
FULL_PATH = DATA_DIR / "validated_full.jsonl"

COLUMNS = ["题号", "题干", "A", "B", "C", "D", "E", "答案", "难度", "题型", "类别", "解析"]
OPTION_KEYS = ["A", "B", "C", "D", "E"]


def norm(q):
    return re.sub(r"\s+", "", q).lower()


def write_csv(rows, out_path, start_id=1):
    n = start_id - 1
    with out_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(COLUMNS)
        for item in rows:
            n += 1
            opts = item.get("options") or {}
            if item["type"] == "判断题":
                opts = {"A": "对", "B": "错"}
            w.writerow([
                n,
                item["question"],
                *[opts.get(k, "") for k in OPTION_KEYS],
                item["answer"],
                item["difficulty"],
                item["type"],
                item.get("chapter", ""),
                item.get("analysis", ""),
            ])
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start-id", type=int, default=2943,
                    help="series_questions.csv 的起始题号（需大于线上库当前最大题号）")
    args = ap.parse_args()

    rows_v1 = [json.loads(l) for l in V1_CLEAN_PATH.open(encoding="utf-8") if l.strip()]
    rows_series = [json.loads(l) for l in SERIES_PATH.open(encoding="utf-8") if l.strip()]

    seen = {norm(r["question"]) for r in rows_v1}
    merged = list(rows_v1)
    for r in rows_series:
        if norm(r["question"]) in seen:
            continue
        seen.add(norm(r["question"]))
        merged.append(r)

    FULL_PATH.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in merged),
                         encoding="utf-8")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    last = write_csv(merged, OUT_DIR / "questions.csv")
    series_last = write_csv(rows_series, OUT_DIR / "series_questions.csv", start_id=args.start_id)
    print(f"v1: {len(rows_v1)} 题，系列: {len(rows_series)} 题，合并后: {len(merged)} 题"
          f"（跨库去重 {len(rows_v1) + len(rows_series) - len(merged)}）")
    print(f"全量 CSV: questions.csv（题号 1..{last}）")
    print(f"增量 CSV: series_questions.csv（题号 {args.start_id}..{series_last}）")


if __name__ == "__main__":
    main()
