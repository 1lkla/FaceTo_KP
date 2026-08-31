#!/usr/bin/env python3
"""解析 raw/*.json，容错提取 JSON，校验题目，全局去重，产出 validated.jsonl 和报告。"""
import hashlib
import json
import os
import re
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "questions"
RAW_DIR = Path(os.environ.get("GEN_RAW", str(DATA_DIR / "raw")))
OUT_PATH = Path(os.environ.get("GEN_OUT", str(DATA_DIR / "validated.jsonl")))
REPORT_PATH = Path(os.environ.get("GEN_REPORT", str(DATA_DIR / "validate_report.json")))

TYPES = {"单选题", "多选题", "判断题", "问答题"}
DIFFICULTIES = {"简单", "中等", "困难"}


def extract_json(text: str):
    """容错提取：去 ```json 围栏，截取首个 [/{ 到最后一个 ]/}。"""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    start = len(text)
    for ch in "[{":
        i = text.find(ch)
        if i != -1:
            start = min(start, i)
    end = max(text.rfind("]"), text.rfind("}"))
    if start >= len(text) or end <= start:
        raise ValueError("找不到 JSON 边界")
    return json.loads(text[start:end + 1])


def normalize_question(q: str) -> str:
    return re.sub(r"\s+", "", q).lower()


def validate_question(item: dict, chunk_meta: dict):
    """返回 (clean_item, error)。error 为 None 表示通过。"""
    qtype = item.get("type")
    if qtype not in TYPES:
        return None, f"非法题型: {qtype!r}"
    question = str(item.get("question", "")).strip()
    if not question:
        return None, "题干为空"
    if len(question) > 500:
        return None, f"题干超长({len(question)}字)"
    options = item.get("options") or {}
    if not isinstance(options, dict):
        return None, "options 不是对象"
    options = {str(k).strip().upper(): str(v).strip() for k, v in options.items()}
    answer = str(item.get("answer", "")).strip()
    analysis = str(item.get("analysis", "")).strip()
    difficulty = item.get("difficulty", "中等")
    if difficulty not in DIFFICULTIES:
        difficulty = "中等"

    if qtype == "单选题":
        a = answer.upper()
        if not re.fullmatch(r"[A-E]", a):
            return None, f"单选答案非法: {answer!r}"
        if a not in options:
            return None, f"单选答案 {a} 对应选项不存在"
        answer = a
    elif qtype == "多选题":
        a = answer.upper().replace(",", "").replace("，", "").replace(" ", "")
        if not re.fullmatch(r"[A-E]{2,5}", a):
            return None, f"多选答案非法: {answer!r}"
        missing = [ch for ch in a if ch not in options]
        if missing:
            return None, f"多选答案 {a} 中选项 {missing} 不存在"
        answer = a
    elif qtype == "判断题":
        if answer not in ("对", "错"):
            # 容忍字母答案（选项即 对/错）、T/F、正确/错误 之类
            a = answer.upper()
            if a in options and options[a] in ("对", "错"):
                answer = options[a]
            else:
                m = {"正确": "对", "错误": "错", "true": "对", "false": "错",
                     "t": "对", "f": "错", "a": "对", "b": "错"}.get(answer.lower())
                if not m:
                    return None, f"判断题答案非法: {answer!r}"
                answer = m
        options = {"A": "对", "B": "错"}
    else:  # 问答题
        if not answer:
            return None, "问答题答案为空"
        options = {}

    clean = {
        "type": qtype,
        "chapter": item.get("chapter") or chunk_meta.get("chapter", ""),
        "difficulty": difficulty,
        "question": question,
        "options": options,
        "answer": answer,
        "analysis": analysis,
        "source_repo": chunk_meta.get("source_repo", ""),
        "source_file": chunk_meta.get("source_file", ""),
        "chunk_id": chunk_meta.get("chunk_id", ""),
    }
    return clean, None


def main():
    raw_files = sorted(RAW_DIR.glob("*.json"))
    if not raw_files:
        print(f"{RAW_DIR} 下没有 raw 文件")
        return
    total, kept = 0, 0
    drop_reasons = Counter()
    type_counts = Counter()
    seen = set()
    bad_files = []

    with OUT_PATH.open("w", encoding="utf-8") as out:
        for rf in raw_files:
            raw = json.loads(rf.read_text(encoding="utf-8"))
            chunk_meta = {k: raw.get(k, "") for k in ("chunk_id", "source_repo", "source_file", "chapter")}
            try:
                items = extract_json(raw["response"])
                if isinstance(items, dict):
                    items = [items]
            except Exception as e:
                bad_files.append((rf.name, str(e)))
                drop_reasons["整块JSON解析失败"] += 1
                continue
            for item in items:
                total += 1
                clean, err = validate_question(item, chunk_meta)
                if err:
                    drop_reasons[err.split(":")[0]] += 1
                    continue
                h = hashlib.sha1(normalize_question(clean["question"]).encode()).hexdigest()
                if h in seen:
                    drop_reasons["题干重复去重"] += 1
                    continue
                seen.add(h)
                type_counts[clean["type"]] += 1
                kept += 1
                out.write(json.dumps(clean, ensure_ascii=False) + "\n")

    report = {
        "raw_files": len(raw_files),
        "total_questions": total,
        "kept": kept,
        "dropped": total - kept + len(bad_files),
        "type_counts": dict(type_counts),
        "drop_reasons": dict(drop_reasons),
        "unparseable_files": bad_files,
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"raw 文件: {len(raw_files)}，题目总数: {total}，保留: {kept}，丢弃: {report['dropped']}")
    print(f"题型分布: {dict(type_counts)}")
    if drop_reasons:
        print(f"丢弃原因: {dict(drop_reasons)}")
    if bad_files:
        print(f"解析失败的块: {[n for n, _ in bad_files]}")
    print(f"输出: {OUT_PATH}\n报告: {REPORT_PATH}")


if __name__ == "__main__":
    main()
