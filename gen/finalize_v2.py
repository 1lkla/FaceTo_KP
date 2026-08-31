#!/usr/bin/env python3
"""按审计结论重建 v2 终版题库：
- 问答题 wrong 且复核给出修正答案（>=30字）的：回收，替换参考答案
- 客观题 wrong 且修正答案合法的：替换答案（同 apply_review）
- 其余 wrong：淘汰
- qid 59（判断题「错→对」被审计判存疑）：回退为原答案
输出 data/questions/validated_v2_final.jsonl
"""
import json
import re
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "questions"
SRC = DATA_DIR / "validated_v2.jsonl"
SHARDS = 4
OUT_PATH = DATA_DIR / "validated_v2_final.jsonl"
CHOICE = {"单选题", "多选题", "判断题"}
REVERT_QID = {59}  # 审计存疑，保留原答案


def valid_answer(qtype, ans):
    ans = str(ans).strip().upper()
    if qtype == "单选题":
        return bool(re.fullmatch(r"[A-E]", ans))
    if qtype == "多选题":
        return bool(re.fullmatch(r"[A-E]{2,5}", ans)) and len(set(ans)) == len(ans)
    if qtype == "判断题":
        return ans in ("对", "错")
    return False


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
                verdicts[orig_idx] = rec  # 后写覆盖前写，取最新一次复核

    stats = Counter(r["verdict"] for r in verdicts.values())
    fixed_choice, fixed_qa, dropped = 0, 0, []
    out = []
    for i, r in enumerate(rows):
        rec = verdicts.get(i)
        if rec is None or rec["verdict"] != "wrong" or i in REVERT_QID:
            out.append(r)
            continue
        ca = str(rec.get("corrected_answer", "")).strip()
        if r["type"] in CHOICE and valid_answer(r["type"], ca):
            old = r.get("answer", "")
            r = dict(r)
            r["answer"] = ca
            r["analysis"] = (r.get("analysis", "") + f"\n（AI复核：原答案「{old}」有误已修正。）").strip()
            fixed_choice += 1
            out.append(r)
        elif r["type"] == "问答题" and len(ca) >= 30:
            r = dict(r)
            r["answer"] = ca
            r["analysis"] = (r.get("analysis", "") + "\n（AI复核：原参考答案有误，已由复核给出修正版。）").strip()
            fixed_qa += 1
            out.append(r)
        else:
            dropped.append({"qid": i, "type": r["type"], "issue": rec.get("issue", "")[:100]})

    with OUT_PATH.open("w", encoding="utf-8") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(json.dumps({
        "复核分布": dict(stats), "修正客观题": fixed_choice,
        "回收购问答题": fixed_qa, "淘汰": len(dropped), "最终题数": len(out),
    }, ensure_ascii=False, indent=2))
    print("淘汰明细:", json.dumps(dropped, ensure_ascii=False)[:1500])


if __name__ == "__main__":
    main()
