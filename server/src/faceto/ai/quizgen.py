"""LLM 出题器（quiz.import）：把任意学习资料转成刷题中心的题库包。

Provider 约定：OpenAI 兼容 chat/completions（智谱 GLM / DeepSeek / vLLM / Ollama 均适用），
环境变量配置（config.py 同款 FT_ 前缀）：
  FT_LLM_API_KEY   必填才启用导入
  FT_LLM_BASE_URL  默认 https://open.bigmodel.cn/api/paas/v4
  FT_LLM_MODEL     默认 glm-4-flash

未配置 key 时 generate_quiz 返回 None，路由层返回 501 并提示两条替代路径。
"""
from __future__ import annotations

import json
import os
import re
import urllib.request

_BASE_URL = os.getenv("FT_LLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4").rstrip("/")
_MODEL = os.getenv("FT_LLM_MODEL", "glm-4-flash")
_INPUT_CAP = 16000          # 单次导入的资料字符上限（超出截断并提示）
_TIMEOUT = 120              # LLM 调用超时（秒）

_PROMPT = """你是资深考试命题专家。依据下面的学习资料出一套刷题，严格只输出一个 JSON 对象，不要任何解释或代码块围栏。

格式要求（字段名必须一致）：
{{
  "choice": [  // 单选题 15~25 道，覆盖资料的主要知识点
    {{"stem": "题干（含（　）占位）", "options": ["A选项","B选项","C选项","D选项"], "answer": "A|B|C|D", "analysis": "一句话解析：为什么选它、干扰项错在哪"}}
  ],
  "subjective": [  // 非选择题 4~8 道，kind 只能是 简答题 或 材料题
    {{"kind": "简答题", "stem": "题干", "material": null, "answer_ref": "参考答案/评分要点，按要点分条，标注分值", "score": 7}}
  ]
}}

规则：
1. 只依据资料内容命题，不要编造资料外的结论；材料题的 material 从资料原文中摘取。
2. 简答题 score=7，材料题 score=15；answer_ref 按「（N分）」标注每个要点分值。
3. 干扰项要有迷惑性；analysis 说清考点。
4. 输出必须是合法 JSON（UTF-8 中文）。

【学习资料】
{material}
"""


def llm_configured() -> bool:
    return bool(os.getenv("FT_LLM_API_KEY"))


def _chat(prompt: str) -> str:
    req = urllib.request.Request(
        f"{_BASE_URL}/chat/completions",
        data=json.dumps({
            "model": _MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
        }).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {os.environ['FT_LLM_API_KEY']}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"]


def _extract_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)          # 剥代码块围栏
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)                       # 兜底：取首个 {...} 块
        if not m:
            raise ValueError("LLM 输出中未找到 JSON")
        return json.loads(m.group(0))


def _normalize(raw: dict) -> tuple[list[dict], list[dict]]:
    """校验 + 归一化：丢弃不合格条目，转成刷题中心的条目结构。"""
    L = "ABCD"
    choice = []
    for i, q in enumerate(raw.get("choice") or []):
        opts = q.get("options") or []
        ans = str(q.get("answer", "")).strip().upper()
        if len(opts) != 4 or ans not in L or not str(q.get("stem", "")).strip():
            continue
        choice.append({
            "id": f"i{i+1}", "set": "练", "no": len(choice) + 1, "type": "single",
            "stem": str(q["stem"]).strip(), "options": [str(o).strip() for o in opts],
            "answer": [L.index(ans)], "score": 2,
            "analysis": str(q.get("analysis") or "").strip() or f"答案 {ans}。",
        })
    subjective = []
    for q in (raw.get("subjective") or []):
        stem, ref = str(q.get("stem") or "").strip(), str(q.get("answer_ref") or "").strip()
        if not stem or not ref:
            continue
        kind = q.get("kind") if q.get("kind") in ("简答题", "材料题", "论述题") else "简答题"
        subjective.append({
            "id": f"s{len(subjective)+1}", "set": "练", "no": 26 + len(subjective),
            "type": "subjective", "kind": kind,
            "stem": f"【材料】{q['material']}\n【题目】{stem}" if (kind != "简答题" and q.get("material")) else stem,
            "options": None, "answer": None,
            "score": 15 if kind != "简答题" else 7, "analysis": ref,
        })
    return choice, subjective


def generate_quiz(material: str) -> tuple[list[dict], list[dict]] | None:
    """资料 → (choice, subjective)。未配置 LLM 返回 None；生成/解析失败抛异常（带原因）。"""
    if not llm_configured():
        return None
    text = material.strip()[:_INPUT_CAP]
    truncated = len(material.strip()) > _INPUT_CAP
    prompt = _PROMPT.format(material=text + ("\n\n（资料过长已截断，仅依据以上内容命题）" if truncated else ""))
    last_err: Exception | None = None
    for _ in range(2):                                # 解析失败重试一次
        try:
            raw = _extract_json(_chat(prompt))
            choice, subjective = _normalize(raw)
            if choice and subjective:
                return choice, subjective
            last_err = ValueError(f"有效题目不足（choice={len(choice)}, subjective={len(subjective)}）")
        except Exception as exc:
            last_err = exc
    raise RuntimeError(f"LLM 出题失败：{last_err}")
