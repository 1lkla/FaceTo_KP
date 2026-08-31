#!/usr/bin/env python3
"""读 chunks.jsonl，并发调 LLM 出题。断点续跑：done.txt 记录已完成 chunk_id。

用法：
  python3 gen/generate.py                              # 全量
  python3 gen/generate.py --only duckpigdog_Sec-Interview --limit 2   # 试产
"""
import argparse
import asyncio
import json
import os
import threading
from pathlib import Path

from glm_client import GLMClient, PROJECT_ROOT

DATA_DIR = PROJECT_ROOT / "data" / "questions"
CHUNKS_PATH = Path(os.environ.get("GEN_CHUNKS", str(DATA_DIR / "chunks.jsonl")))
DONE_PATH = Path(os.environ.get("GEN_DONE", str(DATA_DIR / "done.txt")))
RAW_DIR = Path(os.environ.get("GEN_RAW", str(DATA_DIR / "raw")))

# 无答案材料库：题目出自材料，答案由模型自身知识生成并标注
NO_ANSWER_REPOS = {"evilAdan0s_RedTeamInterview"}

SYSTEM_PROMPT = """你是一位资深网络安全面试出题专家。请基于给定的面试题材料，出 5-15 道高质量面试题（题量按材料内容密度决定，内容少则少出，内容多则多出）。

要求：
1. 题型混合：以单选题/多选题/判断题为主，每块材料至少出 1 道问答题（模拟面试口述场景）。
2. 每道题包含字段：
   - type: "单选题" | "多选题" | "判断题" | "问答题"
   - chapter: 所属章节（沿用材料的章节名）
   - difficulty: "简单" | "中等" | "困难"
   - question: 题干（不超过 500 字，面试导向）
   - options: 对象，如 {"A": "...", "B": "...", "C": "...", "D": "..."}；判断题固定为 {"A": "对", "B": "错"}；问答题为空对象 {}
   - answer: 单选题为单个字母（A-E）；多选题为多个字母（如 "ABC"）；判断题为 "对" 或 "错"；问答题为参考答案
   - analysis: 解析，必须引用材料中的原文知识点说明为什么
3. 选择题选项要有迷惑性（常见误区、相似概念做干扰项），不要一眼就能看出答案。
4. 严格只输出一个 JSON 数组，不要输出任何多余文字、解释或 markdown 围栏。"""

NO_ANSWER_NOTE = """
注意：该材料只有题目没有答案。请用你自身的网络安全知识给出正确答案，并在每题的 analysis 末尾标注「(答案由AI生成)」。"""

USER_TEMPLATE = """材料来源：{repo} / {file}（章节：{chapter}）

材料内容：
{text}

请出题。"""

_done_lock = threading.Lock()


def load_chunks(only=None, limit=None):
    chunks = []
    with CHUNKS_PATH.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                c = json.loads(line)
                if only and c["source_repo"] != only:
                    continue
                chunks.append(c)
    if limit:
        chunks = chunks[:limit]
    return chunks


def load_done():
    if DONE_PATH.exists():
        return set(DONE_PATH.read_text(encoding="utf-8").split())
    return set()


def mark_done(chunk_id):
    with _done_lock:
        with DONE_PATH.open("a", encoding="utf-8") as f:
            f.write(chunk_id + "\n")


async def process_chunk(client, chunk):
    chunk_id = chunk["chunk_id"]
    raw_path = RAW_DIR / f"{chunk_id}.json"
    system = SYSTEM_PROMPT + (NO_ANSWER_NOTE if chunk["source_repo"] in NO_ANSWER_REPOS else "")
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": USER_TEMPLATE.format(
            repo=chunk["source_repo"], file=chunk["source_file"],
            chapter=chunk["chapter"], text=chunk["text"])},
    ]
    try:
        text, usage = await client.chat(messages, max_tokens=8192)
    except Exception as e:
        print(f"  [fail] {chunk_id} ({chunk['source_repo']}/{chunk['source_file']}): {e}")
        return False
    raw_path.write_text(json.dumps({
        "chunk_id": chunk_id,
        "source_repo": chunk["source_repo"],
        "source_file": chunk["source_file"],
        "chapter": chunk["chapter"],
        "response": text,
        "usage": usage,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    mark_done(chunk_id)
    print(f"  [ok] {chunk_id} {chunk['source_repo']}/{chunk['source_file']} "
          f"(tokens: {usage['total_tokens']})")
    return True


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", help="只处理指定 repo")
    parser.add_argument("--limit", type=int, help="最多处理 N 个块")
    args = parser.parse_args()

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    chunks = load_chunks(args.only, args.limit)
    done = load_done()
    todo = [c for c in chunks if c["chunk_id"] not in done]
    print(f"候选 {len(chunks)} 块，已完成 {len(done)} 块，本次待处理 {len(todo)} 块")
    if not todo:
        return

    client = GLMClient()
    results = await asyncio.gather(*(process_chunk(client, c) for c in todo))
    ok = sum(results)
    print(f"完成 {ok}/{len(todo)} 块；累计 token 用量: {client.total_usage}")


if __name__ == "__main__":
    asyncio.run(main())
