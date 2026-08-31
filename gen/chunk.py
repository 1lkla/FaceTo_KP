#!/usr/bin/env python3
"""遍历 4 个面试题库，把 markdown 切成适合喂给 LLM 的块，落盘 chunks.jsonl。"""
import hashlib
import json
import os
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MATERIAL_ROOT = Path("/Users/1lk/workspace/40-knowledge/interview_prep")
OUT_PATH = Path(os.environ.get("GEN_CHUNKS_OUT", str(PROJECT_ROOT / "data" / "questions" / "chunks.jsonl")))

REPOS = [
    "duckpigdog_Sec-Interview",
    "h4m5t_Sec-Interview",
    "goddemondemongod_Sec-Interview",
    "evilAdan0s_RedTeamInterview",
    # v2 新增来源
    "vvmdx_Sec-Interview-4-2023",
    "Leezj9671_Pentest_Interview",
    "just0rg_Security-Interview",
    "Bypass007_Emergency-Response-Notes",
    "tangxiaofeng7_Security_Q-A",
    "we1h0_web-sec-interview",
    "WindXaa_Android-Reverse-interview",
]

# 单文件大仓库：章节用文件内最近的二/三级标题，避免整库挤在一个章节里
SINGLE_FILE_REPOS = {
    "vvmdx_Sec-Interview-4-2023": "vvmdx面经",
    "just0rg_Security-Interview": "just0rg面试题",
    "we1h0_web-sec-interview": "we1h0-Web安全面试",
}

SPLIT_THRESHOLD = 6000   # 超过则按标题再切
CHUNK_MAX = 3000         # 每块上限（字符，近似中文字数）

HEADING_RE = re.compile(r"^(#{2,3})\s+(.*)$", re.M)


def load_duckpigdog_chapters(repo_dir: Path) -> dict:
    """从 SUMMARY.md 解析 ChapterN -> 章节标题，如 {1: '信息收集'}。"""
    summary = repo_dir / "SUMMARY.md"
    mapping = {}
    if summary.exists():
        # 只匹配顶层条目，如 "- [2. SQL 注入](Chapter4/README.md)"，避免误配子条目 [1.31 xxx](Chapter1/1-31.md)
        # 注意 SUMMARY 的显示序号与目录编号不一定一致，以链接里的 ChapterN 为准
        for m in re.finditer(r"^\s*-?\s*\[\d+\.\s+([^\]]+)\]\(Chapter(\d+)/README\.md\)",
                             summary.read_text(encoding="utf-8"), re.M):
            mapping[int(m.group(2))] = m.group(1).strip()
    return mapping


def infer_chapter(repo: str, repo_dir: Path, fpath: Path, chapter_titles: dict) -> str:
    if repo == "duckpigdog_Sec-Interview":
        m = re.match(r"Chapter(\d+)", fpath.parent.name)
        if m:
            num = int(m.group(1))
            title = chapter_titles.get(num, "")
            return f"Chapter{num:02d}-{title}" if title else f"Chapter{num:02d}"
        return "duckpigdog-前言"
    # Bypass007：按子目录归类，如 等未命中则用文件名
    if repo == "Bypass007_Emergency-Response-Notes":
        parent = fpath.parent.name
        if parent and parent != "Emergency-Response-Notes" and parent != repo:
            return f"应急响应-{parent}"
        return f"应急响应-{fpath.stem}"
    if repo == "tangxiaofeng7_Security_Q-A":
        return f"tangx面试QA-{fpath.stem}" if fpath.stem != "README" else "tangx面试QA"
    if repo == "WindXaa_Android-Reverse-interview":
        return f"安卓逆向-{fpath.stem}" if fpath.stem != "README" else "安卓逆向-面试考点"
    # 其余库：用文件内第一个一级标题，否则用文件名
    try:
        text = fpath.read_text(encoding="utf-8")
        m = re.search(r"^#\s+(.+)$", text, re.M)
        if m:
            return m.group(1).strip()[:40]
    except Exception:
        pass
    return f"{repo}-{fpath.stem}"


def hard_split(text: str, limit: int):
    return [text[i:i + limit] for i in range(0, len(text), limit)]


def split_file(text: str):
    """≤6000 字整块返回；否则按二/三级标题切分后打包，每块 ≤3000 字，超出硬切。"""
    if len(text) <= SPLIT_THRESHOLD:
        return [text]
    sections = []
    matches = list(HEADING_RE.finditer(text))
    if not matches:
        return hard_split(text, CHUNK_MAX)
    if matches[0].start() > 0:
        sections.append(text[:matches[0].start()])
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections.append(text[m.start():end])
    chunks, buf = [], ""
    for sec in sections:
        if len(sec) > CHUNK_MAX:
            if buf:
                chunks.append(buf)
                buf = ""
            chunks.extend(hard_split(sec, CHUNK_MAX))
        elif len(buf) + len(sec) > CHUNK_MAX:
            chunks.append(buf)
            buf = sec
        else:
            buf += sec
    if buf:
        chunks.append(buf)
    return [c for c in chunks if c.strip()]


def iter_md_files(repo: str, repo_dir: Path):
    files = sorted(repo_dir.rglob("*.md"))
    for f in files:
        # duckpigdog 的 SUMMARY.md 只是目录，跳过
        if repo == "duckpigdog_Sec-Interview" and f.name == "SUMMARY.md":
            continue
        yield f


def split_file_h(text: str):
    """同 split_file，但返回 [(最近二/三级标题, 块)]，用于单文件大仓库的章节归属。"""
    pieces = split_file(text)
    matches = list(HEADING_RE.finditer(text))
    out = []
    for piece in pieces:
        heading = ""
        try:
            pos = text.index(piece[:80])
            prev = [m for m in matches if m.start() <= pos]
            if prev:
                heading = prev[-1].group(2).strip()[:40]
        except ValueError:
            pass
        out.append((heading, piece))
    return out


def main():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    chapter_titles = load_duckpigdog_chapters(MATERIAL_ROOT / "duckpigdog_Sec-Interview")
    stats = {}
    n_chunks = 0
    with OUT_PATH.open("w", encoding="utf-8") as out:
        for repo in REPOS:
            repo_dir = MATERIAL_ROOT / repo
            files = list(iter_md_files(repo, repo_dir))
            repo_chunks = 0
            for f in files:
                try:
                    text = f.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    text = f.read_text(encoding="utf-8", errors="replace")
                if not text.strip():
                    continue
                base_chapter = infer_chapter(repo, repo_dir, f, chapter_titles)
                rel = f.relative_to(repo_dir).as_posix()
                if repo in SINGLE_FILE_REPOS and f.name in ("README.md", "README_CN.md") or repo in SINGLE_FILE_REPOS and len(files) <= 2:
                    pieces = [(h, c) for h, c in split_file_h(text)]
                    for idx, (h, piece) in enumerate(pieces):
                        chapter = f"{SINGLE_FILE_REPOS[repo]}-{h}" if h else SINGLE_FILE_REPOS[repo]
                        chunk_id = hashlib.sha1(f"{repo}/{rel}#{idx}".encode()).hexdigest()[:12]
                        out.write(json.dumps({
                            "chunk_id": chunk_id,
                            "source_repo": repo,
                            "source_file": rel,
                            "chapter": chapter,
                            "text": piece,
                        }, ensure_ascii=False) + "\n")
                        repo_chunks += 1
                    continue
                chapter = base_chapter
                for idx, piece in enumerate(split_file(text)):
                    chunk_id = hashlib.sha1(f"{repo}/{rel}#{idx}".encode()).hexdigest()[:12]
                    out.write(json.dumps({
                        "chunk_id": chunk_id,
                        "source_repo": repo,
                        "source_file": rel,
                        "chapter": chapter,
                        "text": piece,
                    }, ensure_ascii=False) + "\n")
                    repo_chunks += 1
            stats[repo] = (len(files), repo_chunks)
            n_chunks += repo_chunks
    print(f"输出: {OUT_PATH}")
    print(f"总块数: {n_chunks}")
    for repo, (nf, nc) in stats.items():
        print(f"  {repo}: {nf} 个 md -> {nc} 块")


if __name__ == "__main__":
    main()
