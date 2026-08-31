#!/usr/bin/env python3
"""清洗 v1 题库：删除面经叙事/元信息废题，剥掉"面试官："外衣。

输出 data/questions/validated_v1_clean.jsonl + 清洗报告。
"""
import json, re, os, collections

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(BASE, "data/questions/validated.jsonl")
DST = os.path.join(BASE, "data/questions/validated_v1_clean.jsonl")

# 叙事废题：问的是"某次面试发生了什么"，不是知识点
NARRATIVE = re.compile(
    r"霸面|拿到\s*offer|挂在|被拒|拒绝了他|你们学校|工作人员|面试官(指出|建议|评价|满意|追问后|的表情)|"
    r"HR(面|问)|第[一二三]面(中|上)(发生|提到)|面试(结果|通过|未通过|挂了)|拿到(了)?(口头)?offer|"
    r"他(最终|最后)?(入职|被拒)|lc4t|小白菜|goddemon"
)
# 元信息废题：问的是材料/仓库本身
META = re.compile(
    r"Summary\.md|持续更新|本项目|该仓库|该(项目|材料|仓库)(仍在|的)|整理者|README(\.md)?(文件)?(的|中)(结构|作用|说明)|目录噢"
)
# "面试官："外衣（内容是知识题，只是套了对话壳）——剥壳保留
WRAPPERS = [
    re.compile(r"^面试官(提问|问|：|:)\s*[“\"]?(.+?)[”\"]?[，,]?\s*(根据材料内容)?[，,]?\s*(以下回答最准确的是|你会怎么回答|以下哪个回答最(准确|全面))[?？]?$"),
    re.compile(r"^面试官(提问|问)?[：:]\s*[“\"]?(.+?)[”\"]?$"),
]
# "在XX公司X面中，面试官问及"…"。<真正的题目>" —— 删前半句叙事，保留知识题干
LEAD_IN = re.compile(r"^在[^。]{0,50}(面|电话|视频)[^。]{0,60}面试官(问及|问到|提问|问)[^。]{0,120}。\s*")


def clean_stem(q):
    q = LEAD_IN.sub("", q.strip())
    for pat in WRAPPERS:
        m = pat.match(q.strip())
        if m:
            inner = m.group(2).strip().rstrip("？?")
            if len(inner) >= 10:  # 剥壳后仍有实质内容
                return inner + "？"
    return q


def main():
    rows = [json.loads(l) for l in open(SRC, encoding="utf-8")]
    kept, drop_narr, drop_meta, stripped = [], 0, 0, 0
    for r in rows:
        q = r["question"]
        a = str(r.get("answer", ""))[:200]
        if NARRATIVE.search(q) or NARRATIVE.search(a):
            drop_narr += 1
            continue
        if META.search(q):
            drop_meta += 1
            continue
        q2 = clean_stem(q)
        if q2 != q:
            stripped += 1
            r["question"] = q2
        kept.append(r)
    with open(DST, "w", encoding="utf-8") as f:
        for r in kept:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"v1 原 {len(rows)} → 保留 {len(kept)}（删叙事 {drop_narr}、删元信息 {drop_meta}、剥外衣 {stripped}）")
    print("题型:", dict(collections.Counter(r["type"] for r in kept)))


if __name__ == "__main__":
    main()
