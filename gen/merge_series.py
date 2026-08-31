#!/usr/bin/env python3
"""专题题库应用复核结果并与 v1+v2 合并出全量题库。

1. series_validated.jsonl 按复核记录修正/淘汰（qid = 行号）
2. 与 v1_clean、v2_final 合并（专题题再对 v1+v2 全局去重）
输出 data/questions/validated.jsonl（to_csv.py 的输入）
"""
import json
import re
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "questions"
SERIES_SRC = DATA_DIR / "series_validated.jsonl"
REVIEW_OUT = DATA_DIR / "series_review_out.jsonl"
V1_PATH = DATA_DIR / "validated_v1_clean.jsonl"
V2_PATH = DATA_DIR / "validated_v2_final.jsonl"
OUT_PATH = DATA_DIR / "validated.jsonl"
SERIES_FINAL = DATA_DIR / "series_final.jsonl"

CHOICE = {"单选题", "多选题", "判断题"}


def valid_answer(qtype, ans):
    ans = str(ans).strip().upper()
    if qtype == "单选题":
        return bool(re.fullmatch(r"[A-E]", ans))
    if qtype == "多选题":
        return bool(re.fullmatch(r"[A-E]{2,5}", ans)) and len(set(ans)) == len(ans)
    if qtype == "判断题":
        return ans in ("对", "错")
    return False


def norm(q):
    return re.sub(r"\s+", "", q).lower()


def main():
    # 1) 应用复核
    rows = [json.loads(l) for l in SERIES_SRC.open(encoding="utf-8") if l.strip()]
    verdicts = {}
    if REVIEW_OUT.exists():
        for line in REVIEW_OUT.open(encoding="utf-8"):
            if line.strip():
                rec = json.loads(line)
                if rec["verdict"] != "error":
                    verdicts[rec["qid"]] = rec  # 取最新一次有效复核
    stats = Counter(r["verdict"] for r in verdicts.values())
    fixed_choice, fixed_qa, dropped = 0, 0, []
    series_out = []
    for i, r in enumerate(rows):
        rec = verdicts.get(i)
        if rec is None or rec["verdict"] != "wrong":
            series_out.append(r)
            continue
        ca = str(rec.get("corrected_answer", "")).strip()
        if r["type"] in CHOICE and valid_answer(r["type"], ca):
            old = r.get("answer", "")
            r = dict(r)
            r["answer"] = ca
            r["analysis"] = (r.get("analysis", "") + f"\n（AI复核：原答案「{old}」有误已修正。）").strip()
            fixed_choice += 1
            series_out.append(r)
        elif r["type"] == "问答题" and len(ca) >= 30:
            r = dict(r)
            r["answer"] = ca
            r["analysis"] = (r.get("analysis", "") + "\n（AI复核：原参考答案有误，已由复核给出修正版。）").strip()
            fixed_qa += 1
            series_out.append(r)
        else:
            dropped.append({"qid": i, "type": r["type"], "issue": rec.get("issue", "")[:100]})

    # 2) 合并 v1 + v2 + series（专题对前两者去重）
    seen = set()
    out = []
    for path in (V1_PATH, V2_PATH):
        for line in path.open(encoding="utf-8"):
            if line.strip():
                r = json.loads(line)
                seen.add(norm(r["question"]))
                out.append(r)
    v1v2_n = len(out)
    dup = 0
    for r in series_out:
        k = norm(r["question"])
        if k in seen:
            dup += 1
            continue
        seen.add(k)
        out.append(r)

    with SERIES_FINAL.open("w", encoding="utf-8") as f:
        for r in series_out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with OUT_PATH.open("w", encoding="utf-8") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    report = {
        "专题复核分布": dict(stats),
        "修正客观题": fixed_choice, "回收问答题": fixed_qa, "淘汰": len(dropped),
        "淘汰明细": dropped,
        "专题入库": len(series_out) - dup, "与v1/v2重复淘汰": dup,
        "v1+v2题数": v1v2_n, "全量题数": len(out),
        "题型": dict(Counter(r["type"] for r in out)),
    }
    (DATA_DIR / "merge_report_series.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "淘汰明细"},
                     ensure_ascii=False, indent=2))
    print(f"输出: {OUT_PATH}")


if __name__ == "__main__":
    main()
