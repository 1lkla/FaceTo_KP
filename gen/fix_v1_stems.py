#!/usr/bin/env python3
"""修复 clean_v1.py 误伤的题干。

背景：clean_v1.py 的 LEAD_IN 正则 `[^。]{0,120}。` 会越过引号内的完整问题，
把「在xx面试中，面试官问到：“<真正的题目>”请简述。」整句吃掉，导致部分题干
变成空串或残句（如 '”'、'”请口述你的回答。'）。原始题干在
validated_v1_raw.bak.jsonl 中完好，本脚本按 (题型, 答案, 解析) 精确配对找回：

1. 坏题判定：题干过短 / 引号不配对 / 原始引号内核心问题在清洗版中丢失；
2. 恢复策略：优先取原始题干引号内的核心问题，否则剥掉「在xx面试中，面试官问到：」
   叙事前缀；仅当恢复文本比现题干多出实质内容（>=8 字符）才替换，避免误伤
   本来就完整的选择题题干；
3. 顺带修复 WRAPPERS 剥壳补「？」造成的「。？/？？」结尾瑕疵。

输出：覆盖 data/questions/validated_v1_clean.jsonl，并打印修复报告。
之后需重跑 gen/export_series.py 重新导出 CSV。
"""
import json
import re
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CLEAN_PATH = PROJECT_ROOT / "data" / "questions" / "validated_v1_clean.jsonl"
RAW_PATH = PROJECT_ROOT / "data" / "questions" / "validated_v1_raw.bak.jsonl"

QUOTE = re.compile(r'[“"]([^“”"]{10,500})[”"]')
# 叙事前缀：「在xx面试中，面试官问到：」/「面试官：」
NARR_PREFIX = re.compile(
    r"^在[^，。：]{0,30}的?面试[^：]{0,15}[，：]面试官(问到|问你|问及|提问|问)?[：:]\s*"
    r"|^面试官(提问|问到|问你|问及|问)?[：:]\s*"
)


def key(q):
    return (q["type"], str(q.get("answer", "")), str(q.get("analysis", ""))[:120])


def norm(s):
    return re.sub(r"\s+", "", s)


def unbalanced_quote(stem):
    return stem.count("”") != stem.count("“")


def fix_ending(stem):
    stem = stem.rstrip()
    if stem.endswith("。？"):
        return stem[:-1]
    if stem.endswith("？？"):
        return stem[:-1]
    return stem


def main():
    clean = [json.loads(l) for l in CLEAN_PATH.open(encoding="utf-8") if l.strip()]
    raw = [json.loads(l) for l in RAW_PATH.open(encoding="utf-8") if l.strip()]
    raw_map = {}
    for q in raw:
        raw_map.setdefault(key(q), []).append(q)

    fixed_stems, fixed_endings, skipped = [], 0, []
    for q in clean:
        cands = raw_map.get(key(q))
        if not cands:
            continue
        rq = cands[0]
        if len(cands) > 1:
            rq = next((c for c in cands if c.get("chapter") == q.get("chapter")), cands[0])

        cs, rs = q["question"].strip(), rq["question"].strip()
        m = QUOTE.search(rs)
        core = m.group(1).strip() if m else None

        fragmentary = len(cs) < 25 or unbalanced_quote(cs) or cs[:1] in "：“”"
        broken = fragmentary or (core and norm(core) not in norm(cs))
        if broken:
            if core:
                recovered = core
            else:
                recovered = NARR_PREFIX.sub("", rs)
                # 剥前缀后若整体被引号包裹，再去掉外层引号
                if recovered.startswith("“") and recovered.endswith("”"):
                    recovered = recovered[1:-1].strip()
            recovered = fix_ending(recovered)
            # 残干（过短/引号不配对/标点开头）直接替换；完整题干仅当恢复文本更有信息量才替换
            if fragmentary or len(norm(recovered)) - len(norm(cs)) >= 8:
                fixed_stems.append((cs, recovered))
                q["question"] = recovered
                continue
            skipped.append((cs, core or rs))

        # 结尾「。？/？？」瑕疵修复
        if q["question"] != fix_ending(q["question"]):
            q["question"] = fix_ending(q["question"])
            fixed_endings += 1

    with CLEAN_PATH.open("w", encoding="utf-8") as f:
        for q in clean:
            f.write(json.dumps(q, ensure_ascii=False) + "\n")

    print(f"总题数 {len(clean)} | 恢复题干 {len(fixed_stems)} | 修结尾 {fixed_endings} | 跳过(现干已完整) {len(skipped)}")
    print("\n=== 恢复题干清单 ===")
    for old, new in fixed_stems:
        print(f"- 残干: {old[:40]!r}")
        print(f"  恢复: {new[:70]}")
    if skipped:
        print("\n=== 跳过（恢复文本不比现题干更有信息量）===")
        for old, cand in skipped:
            print(f"- 现干: {old[:60]}")


if __name__ == "__main__":
    main()
