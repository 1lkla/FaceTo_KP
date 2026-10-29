"""配置（§14 技术栈 / §8.3 降级矩阵）。

设计要求 pydantic-settings 集中管理环境变量；M1-dev 用纯 dataclass 等价实现，
字段名与未来的 pydantic-settings 版本保持一致，切换零成本。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# server/data/store.json（core/config.py → parents[3] = server/）
_DEFAULT_STORE_PATH = Path(__file__).resolve().parents[3] / "data" / "store.json"


@dataclass
class Settings:
    # --- 应用 ---
    APP_NAME: str = "FaceTo KP"
    API_PREFIX: str = "/api/v1"

    # --- 存储（§5 数据模型的 M1-dev 落地：内存 dict + JSON 快照落盘）---
    # 生产替换为 PG 后本组配置整体失效，字段保留仅为显式标注替换点。
    STORE_PERSIST: bool = os.getenv("FT_STORE_PERSIST", "1") != "0"
    STORE_PATH: Path = Path(os.getenv("FT_STORE_PATH", str(_DEFAULT_STORE_PATH)))
    STORE_FLUSH_INTERVAL: float = float(os.getenv("FT_STORE_FLUSH_INTERVAL", "2.0"))  # 秒

    # --- 鉴权（§7）---
    JWT_SECRET: str = os.getenv("JWT_SECRET", "dev-secret-change-me")
    ACCESS_TOKEN_TTL: int = int(os.getenv("ACCESS_TOKEN_TTL", "7200"))          # dev 放宽，生产 15min
    REFRESH_TOKEN_TTL: int = 30 * 24 * 3600                                     # 30d
    JWT_ISSUER: str = "faceto-kp"

    # --- 限流（§8.1 应用层兜底，简化为内存计数）---
    ANSWER_RATE_PER_MIN: int = 30          # POST /answers 单用户 30/min
    ANON_RATE_PER_MIN: int = 60

    # --- 降级矩阵开关（§8.3：只砍 AI 与检索域，核心刷题链路永不降级）---
    degrade: dict = field(default_factory=lambda: {
        "exp": False,            # 面经检索
        "ai_review": False,      # AI 点评
        "interview": False,      # 模拟面试新会话
        "jd_parse": False,       # JD 解析
        "stats": False,
    })

    # --- 模拟 LLM 行为（生产换成真实 Provider 的并发/延迟）---
    LLM_JD_PARSE_DELAY: float = 2.5         # JD 解析耗时（秒）
    LLM_REVIEW_DELAY: float = 4.0           # 作答点评耗时（秒）
    LLM_REPORT_DELAY: float = 3.0           # 面试报告耗时（秒）
    LLM_TOKEN_INTERVAL: float = 0.04        # SSE 吐字间隔（秒）


settings = Settings()
