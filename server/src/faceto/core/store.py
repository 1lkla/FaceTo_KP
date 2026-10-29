"""存储与领域事件（§5 数据模型的 M1-dev 实现）。

★ 生产替换点（设计 §5.2）：
- 本文件所有 dict 对应 PG 表：users/jobs/job_points/questions/question_points/
  plans/plan_items/answers/ai_tasks/interview_sessions/interview_turns/mastery_events；
- 所有用户维度记录带 user_id（分片键预留 §5.7）；
- answers 的唯一约束语义 = (user_id, idempotency_key)（分片内唯一）；
- 领域事件总线对应 Kafka topics（§6.1）；
- Redis Key 语义（§5.3）在 practice/interview 域内以内存计数器模拟。

持久化（M1.1）：
- 内存 dict 仍是唯一权威副本，但会周期性 + 退出时写 JSON 快照（原子替换）；
- 启动时优先从快照恢复，恢复失败则回退到种子数据；
- 这样 `--reload` 热重载、手动重启、异常退出都不会再清空作答记录与计划进度。
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

DEMO_EMAIL = "demo@faceto.cn"
SCHEMA_VERSION = 1


class _IdGen:
    """可恢复的自增 ID（生产 = PG sequence / 雪花；快照恢复时续上，避免 ID 撞车）。"""

    def __init__(self, start: int = 1000) -> None:
        self._last = start - 1

    def next(self) -> int:
        self._last += 1
        return self._last

    @property
    def last(self) -> int:
        return self._last

    def restore(self, last: int) -> None:
        try:
            self._last = max(self._last, int(last))
        except (TypeError, ValueError):
            pass


_gen = _IdGen()


def next_id() -> int:
    return _gen.next()


def now() -> float:
    return time.time()


class EventBus:
    """领域事件（§3.3 铁律 3）：跨域写操作只走事件，不走跨域直接写表。"""

    def __init__(self) -> None:
        self._subs: dict[str, list[Callable[[dict], Awaitable[None]]]] = {}

    def subscribe(self, event_type: str, handler: Callable[[dict], Awaitable[None]]) -> None:
        self._subs.setdefault(event_type, []).append(handler)

    async def publish(self, event_type: str, payload: dict) -> None:
        event = {"event_id": f"evt-{next_id()}", "occurred_at": now(), "type": event_type, **payload}
        for handler in self._subs.get(event_type, []):
            try:
                await handler(event)
            except Exception as exc:  # 事件处理失败不阻断主链路（生产进 DLQ）
                print(f"[eventbus] {event_type} handler error: {exc}")


class Store:
    def __init__(self) -> None:
        self.users: dict[int, dict] = {}
        self.sessions: dict[str, int] = {}            # refresh_token -> user_id（Redis session:{user_id}）
        self.jobs: dict[int, dict] = {}
        self.job_points: dict[int, list[dict]] = {}
        self.questions: dict[int, dict] = {}
        self.plans: dict[int, dict] = {}
        self.plan_items: dict[int, list[dict]] = {}
        self.answers: dict[int, dict] = {}
        self.answer_idem: dict[tuple[int, str], int] = {}   # (user_id, idempotency_key) -> answer_id
        self.ai_tasks: dict[int, dict] = {}
        self.exp_docs: list[dict] = []
        self.interviews: dict[int, dict] = {}
        self.interview_turns: dict[int, list[dict]] = {}
        self.mastery: dict[int, dict[str, dict]] = {}       # user_id -> point -> stats
        self.bus = EventBus()
        self.lock = asyncio.Lock()
        self.persisted: bool = False                        # 是否由快照恢复（main 里用于日志）
        self.dirty: bool = False

    def mark_dirty(self) -> None:
        self.dirty = True

    # ------------------------------------------------------------ 快照序列化
    def snapshot(self) -> dict:
        return {
            "schema": SCHEMA_VERSION,
            "saved_at": now(),
            "last_id": _gen.last,
            "users": self.users,
            "sessions": self.sessions,
            "jobs": self.jobs,
            "job_points": self.job_points,
            "questions": self.questions,
            "plans": self.plans,
            "plan_items": self.plan_items,
            "answers": self.answers,
            # tuple key 无法进 JSON，编码为 "user_id::idempotency_key"
            "answer_idem": {f"{u}::{k}": a for (u, k), a in self.answer_idem.items()},
            "ai_tasks": self.ai_tasks,
            "exp_docs": self.exp_docs,
            "interviews": self.interviews,
            "interview_turns": self.interview_turns,
            "mastery": self.mastery,
        }

    def restore(self, data: dict) -> None:
        intkey = lambda d: {int(k): v for k, v in (d or {}).items()}
        self.users = intkey(data.get("users"))
        self.sessions = dict(data.get("sessions") or {})
        self.jobs = intkey(data.get("jobs"))
        self.job_points = intkey(data.get("job_points"))
        self.questions = intkey(data.get("questions"))
        self.plans = intkey(data.get("plans"))
        self.plan_items = intkey(data.get("plan_items"))
        self.answers = intkey(data.get("answers"))
        self.answer_idem = {}
        for k, v in (data.get("answer_idem") or {}).items():
            uid, _, key = k.partition("::")
            self.answer_idem[(int(uid), key)] = int(v)
        self.ai_tasks = intkey(data.get("ai_tasks"))
        self.exp_docs = list(data.get("exp_docs") or [])
        self.interviews = intkey(data.get("interviews"))
        self.interview_turns = intkey(data.get("interview_turns"))
        self.mastery = {int(u): v for u, v in (data.get("mastery") or {}).items()}
        _gen.restore(data.get("last_id", 0))
        self.persisted = True

    def heal_after_restore(self) -> None:
        """恢复后收尾：进程中断导致的悬挂异步任务直接判失败，避免前端无限轮询。"""
        healed = 0
        for t in self.ai_tasks.values():
            if t.get("status") in ("queued", "running"):
                t["status"] = "failed"
                t["result"] = {"error": "进程重启，任务中断"}
                ans = self.answers.get((t.get("payload") or {}).get("answer_id"))
                if ans and ans.get("ai_review_status") in ("queued", "running"):
                    ans["ai_review_status"] = "failed"
                healed += 1
        # 卡在 pending 的 JD 解析 / OCR：异步任务已随进程消失，置为失败让用户可「重新解析」
        for j in self.jobs.values():
            for field in ("parse_status", "ocr_status"):
                if j.get(field) == "pending":
                    j[field] = "failed"
                    healed += 1
        for s in self.interviews.values():
            if s.get("status") in ("streaming", "ending"):
                s["status"] = "done"
        if healed:
            print(f"[store] 恢复后收敛 {healed} 个被进程重启中断的任务")


# ------------------------------------------------------------ 快照落盘 / 载入
def save_snapshot(store: Store, path: Path) -> None:
    """原子写：tmp + os.replace，避免写一半进程被杀导致快照损坏。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(store.snapshot(), f, ensure_ascii=False)
    os.replace(tmp, path)
    store.dirty = False


def load_snapshot(store: Store, path: Path) -> bool:
    """从快照恢复；文件不存在或解析失败返回 False（调用方回退到种子数据）。"""
    path = Path(path)
    if not path.exists():
        return False
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if int(data.get("schema", 0)) != SCHEMA_VERSION:
            print(f"[store] 快照 schema={data.get('schema')} 与当前 {SCHEMA_VERSION} 不符，回退种子数据")
            return False
        store.restore(data)
        return True
    except Exception as exc:  # 快照损坏不应阻断启动
        print(f"[store] 快照恢复失败（{exc}），回退到种子数据")
        return False


# ================================================================ 种子题库（读热点域）
# points 覆盖演示 JD：安全工程师（Web安全 / 密码学 / 鉴权 / 网络 / 系统 / 渗透 / 应急 / 合规）

_Q = [
    # ---- Web 安全 ----
    ("single", "以下哪种手段能有效防御 SQL 注入？", ["对用户输入做参数化查询（预编译）", "在前端用 JS 过滤单引号", "数据库账号使用 root 并提权方便运维", "把报错信息原样返回方便排查"], [0],
     "参数化查询让输入只作为数据而不参与 SQL 语法解析，是根治 SQL 注入的手段；前端过滤可被绕过，root 提权与报错回显反而放大风险。",
     2, ["SQL注入防御"], "牛客·字节安全一面", "Web安全"),
    ("multi", "关于 XSS 的防御，下列哪些说法是正确的？", ["输出到 HTML 上下文时做 HTML 实体转义", "设置 Content-Security-Policy 响应头", "Cookie 设置 HttpOnly 可缓解会话窃取", "只要关闭 JavaScript 就绝对安全"], [0, 1, 2],
     "转义、CSP、HttpOnly 三件套是 XSS 纵深防御的标准组合；「关闭 JS」不具业务可行性。", 3, ["XSS防御"], "牛客·腾讯安全一面", "Web安全"),
    ("subjective", "简述 CSRF 的攻击原理，并给出至少三种防御方案。", None, None,
     "要点：伪造用户已登录身份发起跨站请求（利用 Cookie 自动携带）；防御：CSRF Token、SameSite Cookie、校验 Origin/Referer、关键操作二次验证。",
     3, ["CSRF防御"], "CSDN·美团安全面经", "Web安全"),
    ("single", "同源策略规定两个页面同源需要满足的条件是？", ["协议、域名、端口全部相同", "域名相同即可", "IP 相同即可", "协议相同即可"], [0],
     "同源 = 协议 + 域名 + 端口三者完全一致，是浏览器隔离不同源文档/脚本的安全基石。", 1, ["XSS防御"], None, "Web安全"),
    # ---- 密码学 / 传输安全 ----
    ("single", "HTTPS 握手过程中，浏览器验证服务器身份主要依据是？", ["服务器证书由受信任 CA 签发且域名匹配", "服务器返回的 IP 地址", "URL 里包含 https 字样", "服务器自称是官方站点"], [0],
     "证书链校验（受信 CA 签名 + 域名匹配 + 有效期）是 TLS 身份认证的核心，其余选项均不可靠。", 2, ["HTTPS原理"], "牛客·阿里安全一面", "密码学与传输安全"),
    ("subjective", "说明对称加密与非对称加密的区别，并解释 HTTPS 中两者如何配合使用。", None, None,
     "要点：对称快但密钥分发难，非对称解决密钥交换但慢；TLS 中非对称（RSA/ECDHE）完成密钥协商，之后用对称密钥（AES）加密应用数据。",
     3, ["对称与非对称加密"], "牛客·拼多多安全二面", "密码学与传输安全"),
    ("single", "在数据库中存储用户密码的正确方式是？", ["加盐后做慢哈希（如 bcrypt/argon2/PBKDF2）", "MD5 哈希", "明文存储并限制数据库权限", "Base64 编码"], [0],
     "加盐慢哈希抵抗彩虹表与暴力穷举；MD5 太快且已被攻破，Base64 是编码不是加密。", 1, ["密码哈希存储"], None, "密码学与传输安全"),
    # ---- 认证与鉴权 ----
    ("multi", "JWT 相比传统 session-cookie 的特点包括？", ["服务端无状态，天然适合水平扩展", "payload 默认 Base64 编码，不应放敏感信息", "签发后无法主动撤销，需配合黑名单/短有效期", "JWT 一定比 session 更安全"], [0, 1, 2],
     "JWT 的无状态与自包含是双刃剑：扩展性好，但撤销难、payload 可读，需短有效期 + 黑名单兜底。", 2, ["JWT鉴权"], "CSDN·快手安全面经", "认证与鉴权"),
    ("single", "水平越权（访问他人资源）最有效的防御位置是？", ["服务端接口统一校验资源 owner 与当前用户一致", "前端隐藏他人数据的入口", "使用 POST 而不是 GET", "接口路径加随机数"], [0],
     "越权必须在服务端强制 owner == current_user；前端隐藏、POST、路径混淆都可被绕过。", 2, ["越权访问控制"], "牛客·滴滴安全一面", "认证与鉴权"),
    # ---- 网络协议 ----
    ("single", "TCP 三次握手的第二次握手报文携带的标志位是？", ["SYN+ACK", "ACK", "FIN+ACK", "RST"], [0],
     "第二次握手是服务端同时确认（ACK 客户端 SYN）与同步（SYN 自己的序列号），故为 SYN+ACK。", 1, ["TCP协议"], None, "网络协议"),
    ("subjective", "描述一次 HTTP 请求从输入 URL 到页面展示的完整过程。", None, None,
     "要点：DNS 解析 → TCP 三次握手 → TLS 握手（HTTPS）→ 发送 HTTP 请求 → 服务端处理返回 → 浏览器解析 HTML 构建 DOM/CSSOM → 渲染合成。条理清晰与关键节点完整是得分关键。",
     2, ["计算机网络基础"], "CSDN·腾讯后端面经", "网络协议"),
    # ---- 系统安全 ----
    ("single", "Linux 下发现某进程 CPU 异常飙高，第一步应该？", ["用 top/ps 定位进程及其命令行与父进程", "立刻重启服务器", "直接 kill -9 该进程", "格式化磁盘"], [0],
     "应急响应第一步是取证与定位（进程画像、命令行、网络连接），而非破坏现场；kill/reboot 会丢失证据。", 2, ["应急响应"], "牛客·奇安信面试", "系统与运维安全"),
    ("multi", "常见的 Linux 提权风险点包括？", ["SUID 程序被利用", "内核漏洞（如 DirtyCow）", "sudo 配置过于宽松", "使用 zsh 替代 bash"], [0, 1, 2],
     "SUID、内核漏洞、宽松 sudo 是经典提权三路；shell 选择与提权无关。", 3, ["Linux权限与提权"], "先知社区面经整理", "系统与运维安全"),
    # ---- 渗透与安全测试 ----
    ("subjective", "简述一次完整渗透测试的流程阶段。", None, None,
     "要点：授权与范围界定 → 信息收集 → 漏洞扫描与验证 → 利用（保持最小影响）→ 后渗透评估 → 报告与修复建议复测。强调合法授权贯穿始终。",
     3, ["渗透测试流程"], "牛客·长亭科技面经", "渗透与安全测试"),
    ("single", "OWASP Top 10 中排在前列的注入类漏洞，其根本成因是？", ["不可信数据被当作代码/指令解析执行", "服务器防火墙未开启", "密码策略太弱", "没有使用 HTTPS"], [0],
     "注入（SQL/命令/模板）的本质是「数据与代码边界被打破」，防御思路是严格分离（参数化、白名单）。", 1, ["SQL注入防御"], None, "渗透与安全测试"),
    # ---- 安全工程与合规 ----
    ("single", "SDL（安全开发生命周期）中，需求阶段就应完成的安全活动是？", ["安全需求分析与威胁建模立项", "上线前渗透测试", "线上应急响应演练", "代码审计"], [0],
     "安全左移：需求期明确安全需求与合规基线，成本最低；渗透/审计/应急都在其后。", 2, ["安全开发规范"], "CSDN·蚂蚁安全面经", "安全工程与合规"),
    ("single", "等级保护 2.0 中，第三级系统要求的安全测评周期是？", ["每年至少一次", "每两年一次", "每三年一次", "上线时测评一次即可"], [0],
     "等保 2.0 规定三级系统每年至少开展一次测评，四级系统 twice/年（自查+测评组合），体现持续合规。", 2, ["等保与风险评估"], None, "安全工程与合规"),
    ("multi", "Web 应用部署时的安全基线应包含？", ["统一接入 WAF 并开启防护规则", "管理后台限制来源 IP / VPN 访问", "默认口令全部修改、关闭调试模式", "开放目录列表方便排障"], [0, 1, 2],
     "WAF、后台收敛、改默认口令关调试是上线检查单必项；目录列表开放是典型风险项。", 1, ["安全开发规范"], "牛客·深信服面经", "安全工程与合规"),
    # ---- 综合 ----
    ("subjective", "如果让你给公司的登录接口设计防撞库措施，你会怎么做？", None, None,
     "要点：账号+IP 双维度限流、失败锁定与渐进延迟、验证码升级、异地/设备风控、密码加盐慢哈希、泄露口令库比对。分层作答加分。",
     3, ["接口限流", "JWT鉴权"], "CSDN·京东安全面经", "安全工程与合规"),
]

_EXP = [
    ("字节跳动·安全工程师一面", "牛客", "问了 SQL 注入的绕过手法和防御，手写了一个带过滤函数的注入场景让我绕过；然后问 CSRF 和 XSS 的区别、SameSite 的三个取值。整体偏实战，答的时候最好结合自己挖过的洞讲。", ["SQL注入防御", "CSRF防御", "XSS防御"], "2026-07-12"),
    ("腾讯·安全运营二面", "牛客", "场景题：官网被挂了暗链，怎么排查和应急？我按止血（下线/回滚）→ 取证（日志、webshell 排查）→ 加固（WAF、补丁）的顺序答的，面试官比较满意。", ["应急响应", "安全开发规范"], "2026-07-03"),
    ("阿里云·安全工程师", "牛客", "HTTPS 握手讲了十分钟，从证书链验证讲到 ECDHE 前向安全；然后问了 JWT 的优缺点和注销方案，我答了短有效期+Redis 黑名单。", ["HTTPS原理", "JWT鉴权", "对称与非对称加密"], "2026-06-28"),
    ("美团·安全测试一面", "CSDN", "渗透测试流程必考，还会追问「拿到 webshell 之后你会做什么」。建议把 PTES 流程背熟，并强调授权边界。", ["渗透测试流程", "Linux权限与提权"], "2026-07-20"),
    ("长亭·安全服务工程师", "牛客", "问了等保三级的测评项和差距评估怎么做，还有密评基础。偏合规的岗位对这块问得很细。", ["等保与风险评估"], "2026-08-01"),
    ("快手·客户端安全", "CSDN", "网络基础问得深：三次握手为什么不是两次、TIME_WAIT 的作用、SYN Flood 防御（syncookie）。", ["TCP协议", "计算机网络基础"], "2026-08-05"),
]

_DEMO_JD = """岗位：安全工程师（Web方向）
职责：
1. 负责公司 Web 应用的渗透测试与漏洞挖掘，输出测试报告并推动修复；
2. 参与安全开发生命周期（SDL）建设，在需求与开发阶段落地安全规范；
3. 处置线上安全事件，开展应急响应与溯源分析；
4. 对接等保测评与风险评估，完成合规整改。
要求：
1. 熟悉常见 Web 漏洞原理与防御（SQL注入、XSS、CSRF 等），有渗透测试经验；
2. 熟悉 HTTPS/TLS、加密算法与认证鉴权机制（JWT、OAuth）；
3. 熟悉 TCP/IP 协议栈与计算机网络基础；
4. 熟悉 Linux 系统安全与权限管理，具备应急响应经验；
5. 了解等保2.0与风险评估方法者优先。
"""


def seed_store(store: Store, hash_fn) -> None:
    """幂等种子：题库/面经按内容去重补录，demo 账号与演示岗位只在首次创建。

    幂等是持久化的前提——每次启动都重跑本函数，不能重复灌数据、也不能打乱已有 ID
    （前端 localStorage 里存着 job_id/plan_id，ID 漂移会让老链接失效）。
    """
    demo = next((u for u in store.users.values() if u["email"] == DEMO_EMAIL), None)
    fresh = demo is None
    if fresh:
        uid = next_id()
        demo = {"id": uid, "email": DEMO_EMAIL, "name": "演示用户",
                "password": hash_fn("demo1234"), "created_at": now()}
        store.users[uid] = demo

    # 题库：题干去重（快照恢复后题库已存在，这里只补录新增题、更新已有题字段）
    by_stem = {q["stem"]: q for q in store.questions.values()}
    for (qtype, stem, options, answer, analysis, difficulty, points, exp_ref, chapter) in _Q:
        payload = {"type": qtype, "stem": stem, "options": options, "answer": answer,
                   "analysis": analysis, "difficulty": difficulty, "points": points,
                   "exp_ref": exp_ref, "chapter": chapter, "version": 1, "status": "active"}
        exist = by_stem.get(stem)
        if exist:
            exist.update(payload)          # 保留原 id，避免已作答记录断链
        else:
            qid = next_id()
            store.questions[qid] = {"id": qid, **payload}

    # 面经库（生产在 ES，M1-dev 内存过滤）：按标题去重
    titles = {d["title"] for d in store.exp_docs}
    for (title, source, content, points, published) in _EXP:
        if title in titles:
            continue
        store.exp_docs.append({"id": next_id(), "title": title, "source": source,
                               "content": content, "points": points, "published_at": published})

    # 演示岗位：仅首次创建（快照恢复后直接用库里的那份，含用户自己导入的岗位）
    if fresh:
        jid = next_id()
        store.jobs[jid] = {
            "id": jid, "user_id": demo["id"], "title": "安全工程师（Web方向）", "company": "演示科技",
            "source_type": "text", "raw_text": _DEMO_JD, "parse_status": "done",
            "ocr_status": "done", "cos_key": None, "created_at": now(),
        }
        from ..ai.llm import mock_jd_parse  # 延迟导入避免环
        store.job_points[jid] = mock_jd_parse(_DEMO_JD)["points"]
