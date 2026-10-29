"""LLM 抽象层（§6.5）：Protocol + MockProvider。

生产实现：VolcanoGLM（主）/ LocalQwen（备），统一超时/重试/指标装饰；
本 MVP 用规则引擎模拟三类能力：JD 解析 / 作答点评 / 模拟面试话术流。
"""
from __future__ import annotations

import re
from typing import Protocol


class LLMProvider(Protocol):
    async def chat(self, prompt: str) -> str: ...


# ---------------------------------------------------------------- JD 解析（jd.parse）

# 关键词词典：命中词 -> 考点（名称, 维度）。生产由 LLM 抽取，这里规则模拟。
_KEYWORD_MAP: list[tuple[str, str, str]] = [
    ("sql注入", "SQL注入防御", "知识"), ("注入", "SQL注入防御", "知识"),
    ("xss", "XSS防御", "知识"), ("跨站脚本", "XSS防御", "知识"),
    ("csrf", "CSRF防御", "知识"), ("跨站请求伪造", "CSRF防御", "知识"),
    ("渗透", "渗透测试流程", "技能"), ("漏洞挖掘", "渗透测试流程", "技能"), ("漏洞扫描", "渗透测试流程", "技能"),
    ("https", "HTTPS原理", "知识"), ("tls", "HTTPS原理", "知识"), ("加密算法", "对称与非对称加密", "知识"),
    ("jwt", "JWT鉴权", "知识"), ("oauth", "JWT鉴权", "知识"), ("鉴权", "JWT鉴权", "知识"), ("认证", "JWT鉴权", "知识"),
    ("应急", "应急响应", "技能"), ("溯源", "应急响应", "技能"), ("安全事件", "应急响应", "技能"),
    ("等保", "等保与风险评估", "知识"), ("风险评估", "等保与风险评估", "知识"), ("合规", "等保与风险评估", "知识"),
    ("linux", "Linux权限与提权", "技能"), ("权限管理", "Linux权限与提权", "技能"),
    ("tcp", "TCP协议", "知识"), ("网络", "计算机网络基础", "知识"), ("协议栈", "计算机网络基础", "知识"),
    ("安全开发", "安全开发规范", "知识"), ("sdl", "安全开发规范", "知识"), ("安全规范", "安全开发规范", "知识"),
    ("限流", "接口限流", "知识"), ("waf", "接口限流", "知识"),
    ("python", "Python工程实践", "技能"), ("java", "Java工程实践", "技能"),
    ("redis", "Redis应用", "知识"), ("kafka", "消息队列", "知识"), ("消息队列", "消息队列", "知识"),
    ("docker", "容器与部署", "技能"), ("k8s", "容器与部署", "技能"), ("kubernetes", "容器与部署", "技能"),
    ("数据结构", "数据结构与算法", "知识"), ("算法", "数据结构与算法", "知识"),
    ("前端", "前端基础", "知识"), ("vue", "前端基础", "知识"), ("react", "前端基础", "知识"),
    ("数据库", "数据库基础", "知识"), ("mysql", "数据库基础", "知识"), ("postgresql", "数据库基础", "知识"),
    ("分布式", "分布式系统", "知识"), ("高并发", "分布式系统", "知识"), ("微服务", "微服务架构", "知识"),
]


def mock_jd_parse(jd_text: str) -> dict:
    """规则版「LLM」：关键词命中次数 -> 考点权重；命中句子 -> JD 原句证据（jd_evidence §5.2）。"""
    text = jd_text.lower()
    sentences = [s.strip() for s in re.split(r"[。；;\n.]+", jd_text) if len(s.strip()) >= 4]

    hits: dict[str, dict] = {}
    for kw, point, dim in _KEYWORD_MAP:
        count = text.count(kw)
        if count == 0:
            continue
        if point not in hits or count > hits[point]["count"]:
            evidence = [s for s in sentences if kw in s.lower()][:3]
            hits[point] = {"count": hits.get(point, {}).get("count", 0) + count, "evidence": evidence, "dimension": dim}
        else:
            hits[point]["count"] += count

    if not hits:  # 词典未命中时的兜底
        hits["计算机网络基础"] = {"count": 1, "evidence": sentences[:2], "dimension": "知识"}
        hits["数据结构与算法"] = {"count": 1, "evidence": sentences[:2], "dimension": "知识"}

    ranked = sorted(hits.items(), key=lambda kv: kv[1]["count"], reverse=True)[:10]
    total = sum(v["count"] for _, v in ranked) or 1
    points = []
    for name, v in ranked:
        weight = round(max(4, min(100, v["count"] / total * 140)))
        points.append({
            "point_name": name, "dimension": v["dimension"], "weight": weight,
            "source": "ai", "jd_evidence": v["evidence"] or sentences[:1], "mastery_override": None,
        })
    # 归一化到总权重 ~100
    s = sum(p["weight"] for p in points) or 1
    for p in points:
        p["weight"] = max(3, round(p["weight"] / s * 100))
    return {"points": points}


# ---------------------------------------------------------------- 作答点评（answer.grade）

_REVIEW_RUBRIC = {
    "SQL注入防御": ["参数化查询是否作为根治手段提及", "是否说明预编译的原理（SQL 结构与数据分离）", "是否补充纵深防御（最小权限、WAF、ORM）"],
    "XSS防御": ["是否区分存储型/反射型/DOM 型", "输出编码是否按上下文选择（HTML/JS/URL）", "是否提到 CSP 与 HttpOnly 的纵深价值"],
    "CSRF防御": ["是否讲清 Cookie 自动携带的利用原理", "Token/SameSite/Origin 校验三件套是否齐全", "关键操作二次验证是否补充"],
    "HTTPS原理": ["证书链验证是否完整", "非对称协商 + 对称加密的分工是否讲清", "是否提及前向安全（ECDHE）"],
    "对称与非对称加密": ["性能与密钥分发的权衡是否讲清", "TLS 中的混合使用是否准确", "是否提及典型算法（AES/RSA/ECC）"],
    "JWT鉴权": ["无状态的收益与代价是否都提到", "撤销难点的解法（短有效期+黑名单）是否给出", "payload 可读不放敏感信息是否强调"],
    "越权访问控制": ["是否强调服务端强制校验 owner", "水平/垂直越权是否区分", "是否提到统一依赖注入做检查"],
    "应急响应": ["是否先取证再处置（不破坏现场）", "止血-取证-加固三段式是否清晰", "是否强调复盘与预案沉淀"],
    "渗透测试流程": ["授权与范围界定是否放在第一步", "信息收集→验证→利用→报告的链路是否完整", "是否强调最小影响与合法边界"],
    "计算机网络基础": ["DNS/TCP/TLS/HTTP 节点是否齐全", "渲染流程（DOM/CSSOM）是否补充", "关键机制（握手、缓存）是否展开"],
    "接口限流": ["多维度限流（账号/IP/接口）是否覆盖", "令牌桶/漏桶的差异是否讲清", "是否给出 429 与退避的协议约定"],
}


def mock_answer_review(question: dict, user_answer: str) -> dict:
    """规则版点评：按考点要点清单逐条比对关键词命中，生成得分与建议。"""
    answer = (user_answer or "").strip()
    length = len(answer)
    point = question["points"][0] if question["points"] else "通用"
    rubric = _REVIEW_RUBRIC.get(point, ["答题结构是否清晰", "关键概念是否准确", "是否有实例支撑"])

    hit_flags = []
    for item in rubric:
        keys = re.findall(r"[\u4e00-\u9fa5A-Za-z]{2,}", item)[:4]
        hit_flags.append(any(k in answer for k in keys))

    hit_ratio = sum(hit_flags) / len(hit_flags)
    coverage = min(length / 150, 1.0)
    score = round(40 + hit_ratio * 40 + coverage * 20)

    covered = [item for item, ok in zip(rubric, hit_flags) if ok]
    missing = [item for item, ok in zip(rubric, hit_flags) if not ok]

    lines = [f"【AI 点评 · 得分 {score}/100】", f"考点：{point}　难度：{'★' * question['difficulty']}"]
    lines.append(f"作答长度 {length} 字，要点覆盖 {sum(hit_flags)}/{len(rubric)}。")
    if covered:
        lines.append("已覆盖要点：" + "；".join(covered[:3]) + "。")
    if missing:
        lines.append("建议补充：" + "；".join(missing[:3]) + "。")
    if length < 60:
        lines.append("作答偏短，建议按「结论先行 → 原理展开 → 实例/方案收尾」的结构作答。")
    lines.append(f"参考解析：{question['analysis']}")
    return {"score": score, "review": "\n".join(lines), "covered": covered, "missing": missing}


# ---------------------------------------------------------------- 模拟面试（interview.turn）

_INTERVIEW_QA: dict[str, list[str]] = {
    "SQL注入防御": ["讲讲 SQL 注入的成因，以及参数化查询为什么能根治它？", "预处理和 ORM 就绝对安全了吗？说说你知道的绕过场景。", "如果线上日志里发现大量数据库报错，你会怎么排查是否遭遇注入？"],
    "XSS防御": ["XSS 有哪几种类型？分别给出最有效的防御手段。", "CSP 的 nonce 模式是怎么工作的？它防不了什么？"],
    "CSRF防御": ["CSRF 利用了浏览器什么机制？SameSite 的三个取值分别是什么效果？", "为什么 CSRF Token 要绑定会话？放 localStorage 里行不行？"],
    "HTTPS原理": ["完整描述一次 TLS 1.2 握手，证书链是怎么验证的？", "ECDHE 提供的前向安全是什么意思？RSA 密钥交换为什么没有？"],
    "对称与非对称加密": ["为什么 HTTPS 要混合使用对称与非对称加密？", "说说你了解的哈希与加密的区别，以及 HMAC 的用途。"],
    "JWT鉴权": ["JWT 的结构是什么？签名防篡改的原理？", "JWT 注销为什么难？你在项目里怎么解决的？"],
    "越权访问控制": ["水平越权和垂直越权的区别？各自举一个真实例子。", "如果让你设计一套统一的对象级授权检查，你会放在哪一层？"],
    "应急响应": ["发现服务器被植入 webshell，你的处置顺序是什么？", "如何在不重启服务器的情况下排查隐藏的持久化后门？"],
    "渗透测试流程": ["简述一次完整渗透测试的流程，哪一步最容易被甲方低估？", "拿到 RCE 之后你会做哪些后渗透动作，边界在哪里？"],
    "计算机网络基础": ["从输入 URL 到页面展示，说说完整过程。", "TIME_WAIT 过多怎么办？SYN Flood 的防御思路？"],
    "TCP协议": ["三次握手每一步的作用？为什么两次不行？", "TCP 和 UDP 的适用场景分别是什么？"],
    "Linux权限与提权": ["常见的 Linux 提权思路有哪些？", "SUID 程序的风险点在哪，怎么排查？"],
    "渗透测试流程 ": ["简述一次完整渗透测试的流程。"],
    "等保与风险评估": ["等保 2.0 三级和二级的核心差异？", "风险评估的资产-威胁-脆弱性三元组怎么落地成报告？"],
    "应急响应 ": ["讲一次你处理过的安全事件。"],
    "安全开发规范": ["SDL 各阶段的关键安全活动有哪些？", "怎么推动开发团队接受安全规范而不被抵制？"],
    "接口限流": ["你的登录接口防撞库方案是什么？", "令牌桶和漏桶的区别与选型？"],
    "计算机网络基础 ": ["讲讲 TCP 三次握手。"],
    "Linux权限与提权 ": ["说说 SUID 的风险。"],
    "HTTPS原理 ": ["讲讲 TLS 握手过程。"],
    "JWT鉴权 ": ["JWT 的优缺点？"],
    "SQL注入防御 ": ["SQL 注入怎么防？"],
}

_GENERIC_FOLLOWUPS = [
    "可以再展开讲讲背后的原理吗？",
    "结合一个你遇到过的真实场景说说。",
    "如果流量放大十倍，这个方案还成立吗？",
    "有没有你知道的坑或者失败的教训？",
    "这个点和纵深防御的整体思路怎么衔接？",
]


def mock_interview_first(points: list[str]) -> str:
    pt = "、".join(points[:3])
    return (f"你好，我是今天的面试官。本次模拟面试将围绕以下考点展开：{pt}。"
            f"共 5 轮问答，回答后我会给出实时评估。准备好了我们开始——")


def mock_interview_question(points: list[str], turn_no: int) -> str:
    pool: list[str] = []
    for p in points:
        pool.extend(_INTERVIEW_QA.get(p, []))
    if not pool:
        pool = _GENERIC_FOLLOWUPS
    return pool[(turn_no - 1) % len(pool)]


def mock_followup(turn_no: int) -> str:
    return _GENERIC_FOLLOWUPS[(turn_no - 1) % len(_GENERIC_FOLLOWUPS)]


def mock_eval(answer: str, point: str) -> dict:
    length = len((answer or "").strip())
    score = min(95, 45 + length // 6)
    level = "优秀" if score >= 85 else ("良好" if score >= 70 else ("合格" if score >= 55 else "待加强"))
    return {"point": point, "score": score, "level": level,
            "comment": "要点基本覆盖，表达清晰，可以补充实例增强说服力。" if score >= 70
                       else "回答偏简略，建议按「结论-原理-实例」结构展开。"}
