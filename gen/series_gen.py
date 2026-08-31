#!/usr/bin/env python3
"""专题系列出题管线（知识驱动，不依赖本地材料）。

流程：gen/series/*.json 大纲 → 每个专题两轮（生成 → 自审修正）→ raw_series/ → 校验去重 → series_validated.jsonl

用法：
  python3 gen/series_gen.py                # 全量（断点续跑：已有 raw 文件的专题跳过）
  python3 gen/series_gen.py --series 02-llm-security
  python3 gen/series_gen.py --topic java-security/agent-tool-security  # 试产单个专题
"""
import argparse
import asyncio
import json
import re
from pathlib import Path

from glm_client import GLMClient, PROJECT_ROOT
from validate import extract_json, normalize_question, validate_question

DATA_DIR = PROJECT_ROOT / "data" / "questions"
SERIES_DIR = PROJECT_ROOT / "gen" / "series"
RAW_SERIES_DIR = DATA_DIR / "raw_series"
OUT_PATH = DATA_DIR / "series_validated.jsonl"
V1_CLEAN_PATH = DATA_DIR / "validated_v1_clean.jsonl"

SYSTEM_PROMPT = """你是一位资深网络安全面试官，为初中高级安全岗位（渗透、蓝队、安全研发方向）出题。本次基于给定的知识点范围，出一批高质量面试题。

出题要求：
1. 深度优先：覆盖概念辨析、底层原理、实战利用条件、检测与防御、常见误区。要能区分"背过名词"和"真懂"的候选人，避免一眼看穿答案的送分题。
2. 题干优先场景化：多给现实场景（某段配置/某条日志/某段代码/某个现象/某个攻击现象），问"问题出在哪/下一步怎么做/如何修复/为什么"，少出纯概念背诵题。
3. 选项设计：干扰项必须来自真实误区（常见错误认知、易混淆概念、似是而非的做法）。正确答案是唯一技术上站得住脚的选项，其他选项都能说出明确的错因。
4. 解析要求（150-400字）：先给结论，再讲清原理（为什么对），逐项说明错误选项错在哪，可以补充实战延伸（利用条件/版本边界/防御加固）。解析要自洽、可学习，不看题干也能当知识点读。
5. 禁止出现"根据材料""上述材料""材料中"等字样（本次无材料，纯知识出题）。
6. 答案必须符合业内共识，无争议；对版本相关、快速演变的内容（如具体 CVE 的最新绕过），宁可考稳定的原理层面，不考易过期的细节。
7. 题型比例大致：单选题 50%、多选题 20%、判断题 10%、问答题 20%。难度比例大致：简单 20%、中等 50%、困难 30%。每个字段取值：type ∈ {"单选题","多选题","判断题","问答题"}；difficulty ∈ {"简单","中等","困难"}。
8. 字段结构：
   - type: 题型
   - chapter: "{chapter}"
   - difficulty: 难度
   - question: 题干（不超过 400 字）
   - options: 选择题为 {{"A": "...", "B": "...", "C": "...", "D": "..."}}（最多 5 项）；判断题固定 {{"A": "对", "B": "错"}}；问答题为 {{}}
   - answer: 单选单个字母；多选多个字母如 "BCD"；判断题 "对"/"错"；问答题为 150-400 字参考答案（分点作答，面试可直接口述）
   - analysis: 解析
严格只输出一个 JSON 数组，不要任何多余文字、解释或 markdown 围栏。"""

REVIEW_PROMPT = """你是极其严格的审题专家。下面是一批刚生成的网络安全面试题（JSON 数组）。请逐题审查并输出修正后的最终题目：

1. 技术事实错误、答案有争议或存在更优答案 → 修正（必要时改写题干和选项），无法挽救则整题删除。
2. 解析空洞、没有解释错误选项错在哪 → 补全解析（150-400 字，先结论再原理再逐项排除）。
3. 选项无区分度、一眼看穿 → 重写干扰项（用真实常见误区做干扰）。
4. 题干含"根据材料/上述/材料中"等字样 → 改写为纯知识/场景题。
5. 纯背诵送分题且无场景 → 尽量改造为场景化题干。
6. 判断题过滥 → 可以把部分改造成单选题（相应调整 type/options/answer）。
7. 保持字段结构与原有完全一致；chapter 字段保持原值不变。
宁缺毋滥：删掉低于平均水平的题是允许且鼓励的。只输出修正后的完整 JSON 数组，不要任何多余文字。"""


def load_series():
    return [json.loads(p.read_text(encoding="utf-8"))
            for p in sorted(SERIES_DIR.glob("*.json"))]


def load_v1_norms():
    norms = set()
    if V1_CLEAN_PATH.exists():
        for line in V1_CLEAN_PATH.open(encoding="utf-8"):
            if line.strip():
                norms.add(normalize_question(json.loads(line)["question"]))
    return norms


def parse_items(text):
    """容错解析 LLM 返回的题目数组；对截断输出尝试按最后一个完整对象修复。"""
    text = re.sub(r"^```(?:json)?\s*", "", text.strip())
    text = re.sub(r"\s*```$", "", text)
    i = text.find("[")
    if i == -1:
        raise ValueError("找不到数组起点")
    try:
        return json.loads(text[i:text.rfind("]") + 1])
    except Exception:
        pass
    body = text[i + 1:]
    pos = body.rfind("}")
    while pos != -1:
        try:
            return json.loads("[" + body[:pos + 1] + "]")
        except Exception:
            pos = body.rfind("}", 0, pos)
    raise ValueError("JSON 无法解析（含截断修复）")


GEN_USER = ("知识点范围：{name}\n"
            "考察要点与方向：{brief}\n\n"
            "请出 {n} 道题，覆盖上述考点的不同侧面（不要集中在一个点上）。只输出 JSON 数组。")


async def process_topic(client, series, topic):
    raw_path = RAW_SERIES_DIR / f"{series['series_id']}__{topic['id']}.json"
    if raw_path.exists():
        print(f"  [skip] {series['series_id']}/{topic['id']}")
        return
    chapter = f"{series['chapter_prefix']}-{topic['name']}"
    meta = {
        "chunk_id": f"{series['series_id']}__{topic['id']}",
        "source_repo": f"series:{series['series_id']}",
        "source_file": topic["id"],
        "chapter": chapter,
    }
    # 分批：单次调用 5-8 题，避免超过输出上限被截断
    counts = []
    remain = topic["count"]
    while remain > 0:
        n = min(8 if remain >= 8 else remain, 8)
        if remain - n in (1, 2) and remain - n >= 1:
            n = remain - 4 if remain - 4 >= 4 else n
        counts.append(min(n, remain))
        remain -= min(n, remain)
    seen_local = set()
    final_items, cand_total = [], 0
    try:
        for bi, n in enumerate(counts, 1):
            gen_messages = [
                {"role": "system", "content": SYSTEM_PROMPT.replace("{chapter}", chapter)},
                {"role": "user", "content": GEN_USER.format(name=topic["name"], brief=topic["brief"], n=n)},
            ]
            candidates = None
            for attempt in range(2):
                text1, usage1 = await client.chat(gen_messages, max_tokens=8192)
                try:
                    candidates = parse_items(text1)
                    break
                except Exception as e:
                    print(f"  [warn] {series['series_id']}/{topic['id']} 批{bi} 生成解析失败({e})，重试")
            if not candidates:
                print(f"  [warn] {series['series_id']}/{topic['id']} 批{bi} 放弃该批")
                continue
            cand_total += len(candidates)
            review_messages = [
                {"role": "system", "content": REVIEW_PROMPT},
                {"role": "user", "content": "待审题目：\n" + json.dumps(candidates, ensure_ascii=False)},
            ]
            final_batch = candidates
            for attempt in range(2):
                text2, usage2 = await client.chat(review_messages, max_tokens=8192)
                try:
                    reviewed = parse_items(text2)
                    if reviewed:
                        final_batch = reviewed
                    break
                except Exception as e:
                    print(f"  [warn] {series['series_id']}/{topic['id']} 批{bi} 审校解析失败({e})，重试")
            for item in final_batch:
                q = normalize_question(str(item.get("question", "")))
                if q and q not in seen_local:
                    seen_local.add(q)
                    final_items.append(item)
    except Exception as e:
        print(f"  [fail] {series['series_id']}/{topic['id']}: {e}")
        return

    if not final_items:
        print(f"  [fail] {series['series_id']}/{topic['id']}: 无有效题目")
        return
    raw_path.write_text(json.dumps({
        **meta,
        "series": series["series_id"],
        "topic": topic["id"],
        "topic_name": topic["name"],
        "response": json.dumps(final_items, ensure_ascii=False),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  [ok] {series['series_id']}/{topic['id']} 候选{cand_total} 入库{len(final_items)}")


BAD_TEXT = re.compile(r"根据材料|上述材料|材料中|面试官指出|材料指出")


def validate_all():
    """从 raw_series 重建 series_validated.jsonl：校验 + 与 v1 及系列内部去重。"""
    seen = load_v1_norms()
    total, kept = 0, 0
    drop = {}
    with OUT_PATH.open("w", encoding="utf-8") as out:
        for rf in sorted(RAW_SERIES_DIR.glob("*.json")):
            raw = json.loads(rf.read_text(encoding="utf-8"))
            meta = {k: raw[k] for k in ("chunk_id", "source_repo", "source_file", "chapter")}
            try:
                items = extract_json(raw["response"])
                if isinstance(items, dict):
                    items = [items]
            except Exception:
                drop[rf.name + " JSON解析失败"] = drop.get(rf.name + " JSON解析失败", 0) + 1
                continue
            for item in items:
                total += 1
                clean, err = validate_question(item, meta)
                if err:
                    drop[err.split(":")[0]] = drop.get(err.split(":")[0], 0) + 1
                    continue
                q = clean["question"]
                if BAD_TEXT.search(q):
                    drop["题干引用材料"] = drop.get("题干引用材料", 0) + 1
                    continue
                h = normalize_question(q)
                if h in seen:
                    drop["题干重复"] = drop.get("题干重复", 0) + 1
                    continue
                seen.add(h)
                out.write(json.dumps(clean, ensure_ascii=False) + "\n")
                kept += 1
    print(f"专题题库校验完成：raw {total} 题 → 保留 {kept}，丢弃 {total - kept}")
    if drop:
        print("丢弃明细:", json.dumps(drop, ensure_ascii=False))
    print(f"输出: {OUT_PATH}")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--series", help="只处理指定 series_id")
    parser.add_argument("--topic", help="只处理指定 series_id/topic_id（试产）")
    parser.add_argument("--validate-only", action="store_true", help="只做校验汇总，不生成")
    args = parser.parse_args()

    RAW_SERIES_DIR.mkdir(parents=True, exist_ok=True)
    if args.validate_only:
        validate_all()
        return

    all_series = load_series()
    tasks = []
    for s in all_series:
        if args.series and s["series_id"] != args.series:
            continue
        for t in s["topics"]:
            if args.topic and f"{s['series_id']}/{t['id']}" != args.topic:
                continue
            tasks.append((s, t))
    print(f"待处理专题 {len(tasks)} 个")
    client = GLMClient()
    await asyncio.gather(*(process_topic(client, s, t) for s, t in tasks))
    print(f"token 用量: {client.total_usage}")
    validate_all()


if __name__ == "__main__":
    asyncio.run(main())
