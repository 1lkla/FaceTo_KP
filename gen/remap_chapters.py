#!/usr/bin/env python3
"""章节名重映射：修复单文件库（goddemondemongod README）所有块共用一个章节名的问题。

原理：按 chunk 文本在原始 markdown 中的位置，向上找最近的二级（##）标题作为章节名，
前缀「面试真题-」。只处理 chapter 字段为 "<repo>-README" 的记录。
在 validate.py 之后、to_csv.py 之前运行。
"""
import json, re, os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VALIDATED = os.path.join(BASE, "data/questions/validated.jsonl")
CHUNKS = os.path.join(BASE, "data/questions/chunks.jsonl")
SRC = "/Users/1lk/workspace/40-knowledge/interview_prep"

REMAP_REPOS = {"goddemondemongod_Sec-Interview": "面试真题"}


def section_map(repo):
    """chunk_id -> 章节名：在原文中定位 chunk 文本起点，向上找最近 ## 标题。"""
    path = os.path.join(SRC, repo, "README.md")
    with open(path, encoding="utf-8") as f:
        full = f.read()
    # 预计算所有 ## 标题的位置
    heads = [(m.start(), m.group(1).strip()) for m in re.finditer(r"^#{1,3}\s+(.+)", full, re.M)]
    m = {}
    with open(CHUNKS, encoding="utf-8") as f:
        for line in f:
            c = json.loads(line)
            if c["source_repo"] != repo:
                continue
            # 用 chunk 文本前 80 个非空白字符定位
            probe = re.sub(r"\s+", "", c["text"])[:80]
            full_nospace = re.sub(r"\s+", "", full)
            idx = full_nospace.find(probe)
            if idx < 0:
                continue
            # 换算回原文大致位置：按比例估算即可（找标题只需相对顺序）
            approx = int(idx / max(len(full_nospace), 1) * len(full))
            sec = None
            for pos, title in heads:
                if pos <= approx:
                    sec = title
                else:
                    break
            m[c["chunk_id"]] = sec
    return m


def main():
    maps = {repo: section_map(repo) for repo in REMAP_REPOS}
    rows = [json.loads(l) for l in open(VALIDATED, encoding="utf-8")]
    changed = 0
    for r in rows:
        repo = r.get("source_repo")
        if repo in REMAP_REPOS and r.get("chapter", "").endswith("-README"):
            sec = maps[repo].get(r.get("chunk_id"))
            prefix = REMAP_REPOS[repo]
            r["chapter"] = f"{prefix}-{sec}" if sec else f"{prefix}-综合"
            changed += 1
    with open(VALIDATED, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"重映射 {changed} 题的章节名")


if __name__ == "__main__":
    main()
