# FaceTo KP · 岗位定向刷题

粘贴一份 JD → 生成岗位画像 → 定向刷题 → 模拟面试。
把面经和真题对准你要投的那个岗位，而不是刷一份通用题库。

本仓库是 `docs/backend-web-design.md` 设计文档的 **M1 MVP 实现**（模块化单体），
架构决策、容量规划、限流与降级矩阵、迭代触发器均记录在那份文档里。

---

## 快速开始（任意主机，克隆即可跑）

```bash
git clone https://github.com/1lkla/FaceTo_KP.git
cd FaceTo_KP/server

python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn src.faceto.main:app --host 127.0.0.1 --port 8787
```

浏览器打开 <http://127.0.0.1:8787>

**演示账号**：`demo@faceto.cn` / `demo1234`
（已预置一个解析完成的「安全工程师（Web方向）」岗位画像，登录即可体验 S2 → S5 全链路）

> 依赖只有 `fastapi` + `uvicorn`，无数据库、无外部服务：
> M1 阶段存储为进程内存（重启即失）、LLM 为规则引擎模拟，所有生产替换点已在代码与 `server/README.md` 中标注。

---

## 五屏功能模块

| 屏 | 功能 | 主要接口 | 业务域 |
|---|---|---|---|
| S1 | 导入岗位 JD（文本 / 链接 / 截图三入口，异步解析） | `POST /jobs` → 202 | job |
| S2 | 岗位画像：考点雷达、权重微调、掌握度、弱项 | `GET/PUT /jobs/{id}/points`、`GET /profile/mastery` | job / profile |
| S3 | 备考计划（按权重分日）+ 面经情报检索 | `POST /jobs/{id}/plans`、`GET /plans/{id}`、`GET /exp` | practice / exp |
| S4 | 定向刷题：客观同步判分、主观 AI 异步点评、双溯源 | `GET /plans/{id}/next`、`POST /answers`、`GET /answers/{id}/review` | practice / question |
| S5 | 模拟面试：SSE 流式追问 + 实时考点评估 + 报告回流 | `POST /interviews`、`GET /interviews/{id}/stream`、`POST /turns` | interview |

掌握度通过领域事件回流（`answer.graded` → profile 域），S2 雷达与 S5 报告共享同一份数据。

---

## 工程结构

```
docs/                        # 设计文档（架构 / 后端 Web 开发设计）
server/
├── src/faceto/
│   ├── main.py              # 组装：include_router + 静态站点
│   ├── core/                # 框架层（config / security / store / tasks）
│   ├── domains/             # ★ 业务域 = 未来微服务边界
│   │   ├── user/  job/  question/  practice/  exp/  interview/  profile/
│   └── ai/                  # LLM 抽象层（Protocol + MockProvider）
├── web/                     # 五屏前端（index.html / app.js / styles.css）
└── requirements.txt
```

域目录 = 未来的微服务边界：域之间只调 service 接口，跨域写走领域事件（生产切 Kafka），
拆分服务是「搬目录」而不是「重写」。详见 `docs/backend-web-design.md` §3.3 依赖铁律。

---

## API 契约要点

- 前缀 `/api/v1/*`，从第一天起版本化；
- 鉴权 `Authorization: Bearer <access_token>`（JWT，15min access + 30d refresh）；
- 写接口支持 `Idempotency-Key`（作答提交必带，防双击与重试双写）；
- AI 类接口 202 异步语义 + 统一任务状态 `GET /tasks/{id}` 轮询兜底，排队时间可见；
- SSE：`event: token | point_eval | done | error`，心跳与关缓冲策略见文档 §4.3；
- 错误体统一 `{"code": "...", "message": "..."}`，错误码按域前缀（`AUTH_` / `JOB_` / `PRC_`…）。

---

## 当前阶段的简化（生产替换点）

| 项 | M1 实现 | 生产 |
|---|---|---|
| 存储 | 进程内存 | PostgreSQL 16（主从 + 分区表，已预留 `user_id` 分片键） |
| 异步 | asyncio 后台协程 | Kafka + ai_worker / flush_worker 进程 |
| LLM | 规则引擎（关键词抽取 / 模板点评 / 预设话术） | VolcanoGLM 主 + LocalQwen 备，令牌桶 + 熔断 |
| 检索 | 内存关键词过滤 | Elasticsearch 8（ik 分词） |
| 缓存 / 限流 | 内存计数器 | Redis 7 Cluster + 网关 APISIX |
| SSO 会话 | 内存 | Redis（`session:{user_id}` / `sse:state:{session_id}`） |

降级矩阵（`degrade.*` 开关）已在 `core/config.py` 落地：只砍 AI 与检索域，
核心刷题链路（登录 → 题目 → 判分 → 进度）永不降级。

---

## 参考

- `docs/backend-architecture.md` —— 六层架构、七服务拆分、扛压六决策
- `docs/backend-web-design.md` —— 容量规划、工程结构、API 契约、数据模型、异步管线、降级预案
- `server/README.md` —— 代码与设计的逐条映射表、运行说明
