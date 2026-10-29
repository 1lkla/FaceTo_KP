"""刷题中心 —— 题库包注册表（M1-dev：磁盘 JSON 文件，一个包一个文件）。

生产替换点：换 PG 表 quiz_packs（包元数据）+ quiz_items（题目行），
本模块对外暴露的 list/get/save/delete 语义保持不变。

包文件结构（server/data/quiz_packs/{pid}.json）：
  {id, name, desc, source, origin, created_at, choice:[...], subjective:[...]}
- origin: "seed"（内置，不可删）| "import-llm"（LLM 导入）| "manual"（助手/脚本写入）
- choice 条目：{id,set,no,type:"single",stem,options[4],answer[idx],score,analysis}
- subjective 条目：{id,set,no,type:"subjective",kind,stem,options:null,answer:null,score,analysis}
"""
from __future__ import annotations

import json
import time
from pathlib import Path

_PACKS_DIR = Path(__file__).resolve().parents[3] / "data" / "quiz_packs"

from .xi_bank import QUIZ_BANK  # 内置种子包内容


def packs_dir() -> Path:
    _PACKS_DIR.mkdir(parents=True, exist_ok=True)
    return _PACKS_DIR


def _valid(pack: dict) -> bool:
    return (isinstance(pack, dict) and isinstance(pack.get("name"), str)
            and isinstance(pack.get("choice"), list)
            and isinstance(pack.get("subjective"), list))


def list_packs() -> list[dict]:
    out = []
    for f in sorted(packs_dir().glob("*.json")):
        try:
            p = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not _valid(p):
            continue
        out.append({
            "id": p["id"], "name": p["name"], "desc": p.get("desc", ""),
            "source": p.get("source", ""), "origin": p.get("origin", "manual"),
            "created_at": p.get("created_at", 0),
            "n_choice": len(p["choice"]), "n_subjective": len(p["subjective"]),
        })
    return out


def get_pack(pid: str) -> dict | None:
    if not pid.replace("-", "").replace("_", "").isalnum():
        return None  # 防路径穿越
    f = packs_dir() / f"{pid}.json"
    if not f.exists():
        return None
    try:
        p = json.loads(f.read_text(encoding="utf-8"))
        return p if _valid(p) else None
    except Exception:
        return None


def save_pack(pack: dict) -> None:
    packs_dir().joinpath(f"{pack['id']}.json").write_text(
        json.dumps(pack, ensure_ascii=False, indent=1), encoding="utf-8")


def delete_pack(pid: str) -> bool:
    f = packs_dir() / f"{pid}.json"
    if not f.exists():
        return False
    p = get_pack(pid)
    if p and p.get("origin") == "seed":
        raise PermissionError("内置题库包不可删除")
    f.unlink()
    return True


def seed_packs() -> None:
    """幂等：内置习思想包缺失时写入（用户在界面上删不掉它，无需每次重写）。"""
    if get_pack("xi15040") is None:
        save_pack({
            "id": "xi15040", "name": "习思想模拟卷（15040）",
            "desc": "习近平新时代中国特色社会主义思想概论 · 自考三套模拟题",
            "source": "内置 · 三套模拟卷（75 选择 + 18 非选择）",
            "origin": "seed", "created_at": time.time(),
            **QUIZ_BANK,
        })
