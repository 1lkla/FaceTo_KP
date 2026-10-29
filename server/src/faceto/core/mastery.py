"""岗位匹配度计算（core 共享纯函数，供 job / profile 两域调用，避免同名字段两种口径）。

★ 为什么放在 core 而不是某个域：
  匹配度是「岗位考点 × 用户掌握度」的联合计算，job 域与 profile 域都要用。
  若各自实现，必然出现「都叫 match_score 但算法不同」的语义分裂（已踩过一次坑）。
  core 提供无状态的纯函数，不 import 任何域 —— 符合 §3.3 依赖铁律（core 不依赖 domains）。

口径约定：
- match_score 匹配度 = Σ(考点权重 × 掌握度) / Σ全部考点权重，未答考点按 0 计入分母。
  保守口径：未练过的考点不得分，随刷题推进单调上行。
- coverage 覆盖度 = Σ已练考点权重 / Σ全部考点权重。
  只回答「练过多少」，不回答「掌握多少」，与匹配度是两件事，必须分开返回。
"""
from __future__ import annotations


def compute_match(points: list[dict], mastery_map: dict) -> dict:
    """points: [{"point_name": str, "weight": int}, ...]；mastery_map: {考点名: {"score": int, ...}}。"""
    if not points:
        return {"match_score": None, "coverage": None, "known": [], "weak": []}

    total_weight = sum(p["weight"] for p in points)
    known, covered_weight, weighted = [], 0, 0
    for p in points:
        m = mastery_map.get(p["point_name"])
        if m and m.get("score") is not None:
            known.append({"point_name": p["point_name"], "weight": p["weight"],
                          "mastery": m["score"], "answered": m.get("answered", 0)})
            covered_weight += p["weight"]
            weighted += p["weight"] * m["score"]

    if not known:
        # 一个考点都没练过：匹配度「无数据」（前端显示「尚未开始练习」），
        # 不可返回 0 —— 0 会被读成「练过但全不会」，语义完全不同。
        return {"match_score": None, "coverage": 0, "known": [], "weak": []}

    match = round(weighted / total_weight) if total_weight else None
    coverage = round(covered_weight / total_weight * 100) if total_weight else None
    # 弱项：已练考点中掌握度最低的 3 个（未练考点不算弱项，只是「未覆盖」）
    weak = sorted(known, key=lambda x: x["mastery"])[:3]
    return {"match_score": match, "coverage": coverage, "known": known,
            "weak": [{"point_name": w["point_name"], "mastery": w["mastery"]} for w in weak]}
