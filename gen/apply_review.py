#!/usr/bin/env python3
"""应用 LLM 复核结果：修正 wrong 题答案、淘汰无法修正的错题。

分片映射：shard s 的复核记录 qid=p 对应 validated_v2.jsonl 第 p*4+s 行。
输出 data/questions/validated_v2_reviewed.jsonl + 报告。
"""
import json
import re
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "questions"
SRC = DATA_DIR / "validated_v2.jsonl"
SHARDS = 4
OUT_PATH = DATA_DIR / "validated_v2_reviewed.jsonl"
REPORT_PATH = DATA_DIR / "apply_review_report.json"

CHOICE = {"单选题", "多选题", "判断题"}


def valid_answer(qtype, ans):
    ans = str(ans).strip().upper()
    if qtype == "单选题":
        return bool(re.fullmatch(r"[A-E]", ans))
    if qtype == "多选题":
        return bool(re.fullmatch(r"[A-E]{2,5}", ans)) and len(set(ans)) == len(ans)
    if qtype == "判断题":
        return ans in ("对", "错")
    return bool(str(ans).strip())


def main():
    rows = [json.loads(l) for l in SRC.open(encoding="utf-8")]
    verdicts = {}
    for s in range(SHARDS):
        path = DATA_DIR / f"review_out_{s}.jsonl"
        if not path.exists():
            continue
        for line in path.open(encoding="utf-8"):
            if not line.strip():
                continue
            rec = json.loads(line)
            orig_idx = rec["qid"] * SHARDS + s
            if 0 <= orig_idx < len(rows):
                verdicts[orig_idx] = rec

    stats = Counter(r["verdict"] for r in verdicts.values())
    fixed, dropped, kept_uncertain = [], [], 0
    out = []
    for i, r in enumerate(rows):
        rec = verdicts.get(i)
        if rec is None or rec["verdict"] in ("correct", "error"):
            out.append(r)
            continue
        if rec["verdict"] == "uncertain":
            kept_uncertain += 1
            out.append(r)
            continue
        # wrong
        ca = str(rec.get("corrected_answer", "")).strip()
        if r["type"] in CHOICE and valid_answer(r["type"], ca):
            old = r.get("answer", "")
            r["answer"] = ca if r["type"] != "判断题" else ("对" if ca in ("对", "A", "正确") else "错")
            r["analysis"] = (r.get("analysis", "") + f"\n（AI复核：原答案「{old}」有误已修正。）").strip()
            fixed.append({"qid": i, "old": old, "new": r["answer"], "issue": rec.get("issue", "")[:100]})
            out.append(r)
        else:
            dropped.append({"qid": i, "issue": rec.get("issue", "")[:120],
                            "question": rec.get("question", "")})

    with OUT_PATH.open("w", encoding="utf-8") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    report = {
        "复核覆盖": len(verdicts),
        "verdict分布": dict(stats),
        "修正答案": len(fixed),
        "淘汰错题": len(dropped),
        "保留待定(uncertain)": kept_uncertain,
        "最终题数": len(out),
        "修正明细": fixed[:30],
        "淘汰明细前10": dropped[:10],
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if not k.startswith(("修正明", "淘汰明"))},
                     ensure_ascii=False, indent=2))
    print(f"输出: {OUT_PATH}")


if __name__ == "__main__":
    main()
