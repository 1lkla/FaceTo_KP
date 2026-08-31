#!/usr/bin/env python3
"""LLM 答案复核：逐题送模型判断参考答案是否正确，产出复核结果 jsonl。

env:
  GEN_REVIEW_IN   输入题库 jsonl（必填）
  GEN_REVIEW_OUT  复核结果 jsonl
  GEN_REVIEW_DONE 断点记录
  GEN_CONCURRENCY 并发（默认 4）

复核结果每行：{qid, verdict: "correct"|"wrong"|"uncertain", issue, corrected_answer}
"""
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from glm_client import GLMClient, PROJECT_ROOT  # noqa: E402

DATA_DIR = PROJECT_ROOT / "data" / "questions"
IN_PATH = Path(os.environ.get("GEN_REVIEW_IN", ""))
OUT_PATH = Path(os.environ.get("GEN_REVIEW_OUT", str(DATA_DIR / "review_out.jsonl")))
DONE_PATH = Path(os.environ.get("GEN_REVIEW_DONE", str(DATA_DIR / "review_done.txt")))

SYSTEM_PROMPT = """你是一位严格的网络安全题库审校专家。给你一道题（题干、选项、给出的答案、解析），请你独立判断「给出的答案」是否正确。

判定标准：
- correct：答案正确（解析有小瑕疵不算错）。
- wrong：答案明确错误，或题目本身有严重问题导致无法作答（如题干与选项/答案矛盾、多选题答案缺漏明显）。尽量给出你认为的正确答案。
- uncertain：题目过于依赖特定材料原文、开放性问题无法客观判对错、或信息不足无法判定。

严格只输出一个 JSON 对象，格式：
{"verdict": "correct|wrong|uncertain", "issue": "一句话说明原因（correct 时可为空）", "corrected_answer": "仅 wrong 时给出正确答案字母/对错/简述，否则为空字符串"}
不要输出任何多余文字或 markdown 围栏。"""

USER_TEMPLATE = """题型：{qtype}
章节：{chapter}
题干：{question}
选项：{options}
给出的答案：{answer}
解析：{analysis}

请审校。"""


async def main():
    if not IN_PATH or not IN_PATH.exists():
        print(f"输入不存在: {IN_PATH}", file=sys.stderr)
        sys.exit(1)
    rows = [json.loads(l) for l in IN_PATH.open(encoding="utf-8") if l.strip()]
    done = set()
    if DONE_PATH.exists():
        done = set(DONE_PATH.read_text(encoding="utf-8").split())
    todo = [(i, r) for i, r in enumerate(rows) if str(i) not in done]
    print(f"共 {len(rows)} 题，已完成 {len(done)}，本次待复核 {len(todo)}")

    client = GLMClient()
    out_f = OUT_PATH.open("a", encoding="utf-8")
    done_f = DONE_PATH.open("a", encoding="utf-8")
    lock = asyncio.Lock()
    stats = {"correct": 0, "wrong": 0, "uncertain": 0, "error": 0}

    async def review(idx, r):
        import re as _re
        user = USER_TEMPLATE.format(
            qtype=r["type"], chapter=r.get("chapter", ""), question=r["question"],
            options=json.dumps(r.get("options") or {}, ensure_ascii=False),
            answer=r.get("answer", ""), analysis=r.get("analysis", "")[:600],
        )
        try:
            text, _ = await client.chat(
                [{"role": "system", "content": SYSTEM_PROMPT},
                 {"role": "user", "content": user}], max_tokens=4096)
            text = _re.sub(r"^```(?:json)?\s*", "", text.strip())
            text = _re.sub(r"\s*```$", "", text)
            start = min((i for i in (text.find("{"),) if i >= 0), default=-1)
            end = text.rfind("}")
            verdict = json.loads(text[start:end + 1])
            v = verdict.get("verdict", "uncertain")
            if v not in stats:
                v = "uncertain"
        except Exception as e:
            verdict, v = {"verdict": "error", "issue": str(e)[:200], "corrected_answer": ""}, "error"
        rec = {"qid": idx, "verdict": v, "issue": verdict.get("issue", ""),
               "corrected_answer": verdict.get("corrected_answer", ""),
               "chapter": r.get("chapter", ""), "question": r["question"][:100],
               "type": r["type"], "answer": r.get("answer", "")}
        async with lock:
            stats[v] += 1
            out_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            done_f.write(str(idx) + "\n")

    BATCH = 50
    for s in range(0, len(todo), BATCH):
        await asyncio.gather(*(review(i, r) for i, r in todo[s:s + BATCH]))
        out_f.flush(), done_f.flush()
        print(f"  进度 {min(s + BATCH, len(todo))}/{len(todo)}")
    out_f.close(), done_f.close()
    print(f"复核完成: {stats}")
    print(f"token 用量: {client.total_usage}")


if __name__ == "__main__":
    asyncio.run(main())
