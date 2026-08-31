#!/usr/bin/env python3
"""合并 v2 四组题库：剥叙事壳、删废题、组内及对 v1 全局去重。

输出 data/questions/validated_v2.jsonl + 合并报告。
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "questions"
V1_PATH = DATA_DIR / "validated_v1_clean.jsonl"
GROUPS = ["vvmdx", "just0rg", "bypass", "small"]
OUT_PATH = DATA_DIR / "validated_v2.jsonl"
REPORT_PATH = DATA_DIR / "merge_report_v2.json"

# 与 clean_v1.py 同源的清洗规则
NARRATIVE = re.compile(
    r"霸面|拿到\s*offer|挂在|被拒|拒绝了他|你们学校|工作人员|面试官(指出|建议|评价|满意|追问后|的表情)|"
    r"HR(面|问)|第[一二三]面(中|上)(发生|提到)|面试(结果|通过|未通过|挂了)|拿到(了)?(口头)?offer|"
    r"他(最终|最后)?(入职|被拒)|lc4t|小白菜|goddemon"
)
META = re.compile(
    r"Summary\.md|持续更新|本项目|该仓库|该(项目|材料|仓库)(仍在|的)|整理者|README(\.md)?(文件)?(的|中)(结构|作用|说明)|目录噢"
)
LEAD_IN = re.compile(r"^在[^。]{0,50}(面|电话|视频)[^。]{0,60}面试官(问及|问到|提问|问)[^。]{0,120}。\s*")
WRAPPERS = [
    re.compile(r"^面试官(提问|问|：|:)\s*[“\"]?(.+?)[”\"]?[，,]?\s*(根据材料内容)?[，,]?\s*(以下回答最准确的是|你会怎么回答|以下哪个回答最(准确|全面))[?？]?$"),
    re.compile(r"^面试官(提问|问)?[：:]\s*[“\"]?(.+?)[”\"]?$"),
]


def clean_stem(q):
    q = LEAD_IN.sub("", q.strip())
    for pat in WRAPPERS:
        m = pat.match(q.strip())
        if m:
            inner = m.group(2).strip().rstrip("？?")
            if len(inner) >= 10:
                return inner + "？"
    return q


def norm(q):
    return re.sub(r"\s+", "", q).lower()


def main():
    seen = set()
    if V1_PATH.exists():
        for line in V1_PATH.open(encoding="utf-8"):
            if line.strip():
                seen.add(norm(json.loads(line)["question"]))
    v1_n = len(seen)

    kept, drop_dup_v1, drop_dup_v2, drop_narr, drop_meta = [], 0, 0, 0, 0
    per_group = Counter()
    for g in GROUPS:
        path = DATA_DIR / f"validated_v2_{g}.jsonl"
        if not path.exists():
            print(f"!! 缺少 {path}", file=sys.stderr)
            continue
        for line in path.open(encoding="utf-8"):
            if not line.strip():
                continue
            r = json.loads(line)
            q = clean_stem(r["question"].strip())
            if q != r["question"]:
                r["question"] = q
            a = str(r.get("answer", ""))[:200]
            if NARRATIVE.search(q) or NARRATIVE.search(a):
                drop_narr += 1
                continue
            if META.search(q):
                drop_meta += 1
                continue
            key = norm(q)
            if key in seen:
                if per_group.get("_seen_v2"):
                    drop_dup_v2 += 1
                else:
                    drop_dup_v1 += 1
                continue
            if key in {norm(x["question"]) for x in kept}:
                drop_dup_v2 += 1
                continue
            seen.add(key)
            kept.append(r)
            per_group[g] += 1

    with OUT_PATH.open("w", encoding="utf-8") as f:
        for r in kept:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    types = Counter(r["type"] for r in kept)
    chapters = Counter(r.get("chapter", "") for r in kept)
    report = {
        "v1已有题数": v1_n,
        "v2保留": len(kept),
        "对v1去重淘汰": drop_dup_v1,
        "v2组内去重淘汰": drop_dup_v2,
        "叙事废题": drop_narr,
        "元信息废题": drop_meta,
        "按题型": dict(types),
        "章节数": len(chapters),
        "题数前10章节": chapters.most_common(10),
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"输出: {OUT_PATH}")


if __name__ == "__main__":
    main()
