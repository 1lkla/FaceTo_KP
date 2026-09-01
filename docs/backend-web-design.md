# FaceTo KP · 后端 Web 开发设计（工程实施版）

> 上游文档：`backend-architecture.md`（六层架构 + 七服务拆分 + 扛压六决策）
> 本文档回答：**具体怎么建**——容量数字、工程结构、数据模型、API 契约、异步管线、突发流量预案、迭代触发器。
> 设计基准：**日活 10 万，上线即可能遭遇流量激增（投放/爆款传播），且必须平滑演进不停机重写。**

---

## 0. 第一性原理：从物理约束推导，而不是抄架构

去掉所有名词，系统只受四个物理量约束：

| 物理量 | 推算（10 万 DAU） | 推出的决策 |
|---|---|---|
| **请求速率** | 峰值小时 4 万活跃用户，人均 15 次页面/接口交互 → 峰值读 ~2,000 QPS，作答提交峰值 ~400 QPS | 读走 CDN+Redis 挡 90%；写走 Kafka 合并，DB 只见批量写 |
| **外部延迟** | LLM 单次 2–30s（JD 解析、点评、模拟面试），不可压缩 | LLM 永不占用请求线程：全异步 + SSE 流式单向吐字 |
| **状态规模** | 300 万作答/日 ≈ 1GB/日；年增 ~400GB 作答流水 + 面经 ES 索引增长 | 作答表按月分区；核心表全部预埋 `user_id` 分片键 |
| **故障概率** | LLM 服务商日故障概率 >> 自有服务；爬虫源随时封禁 | AI 域与爬虫域必须可整体摘除（熔断 + 降级矩阵），核心刷题链路零依赖它们 |

**核心不等式**：`用户可感知延迟 < 1s 的请求，绝不允许依赖任何 > 1s 的外部调用。`
这条不等式直接决定：刷题、判分、进度、题库浏览全部走本地 PG/Redis；AI 只出现在「异步任务结果」和「SSE 流」两种形态里。

---

## 1. 现状盘点与差距分析

### 1.1 现有资产（v0）

| 资产 | 现状 | 目标架构中的去留 |
|---|---|---|
| `app/` Flask 单体 | app.py 1772 行、约 30 个服务端渲染路由、SQLite | **逻辑保留，代码重写**：作为「章节刷题 v0」并入题库服务域；不直接改造（见 §11 迁移） |
| 题库 3400 题 + CSV 管线 | 结构化 CSV、章节映射、去重校验 | 直接通过迁移脚本进 PG `questions` 表，作为初始通用题库 |
| `gen/` LLM 生成管线 | 断点续跑、自审、校验、去重 | 演进为 `crawler.push` / `exp2question` Worker 的离线版本，代码复用度 ~70% |
| `ExamMasterAndroid/` | Android 客户端 | 延后：Web 优先，API 网关天然兼容 |

### 1.2 关键差距

1. **SQLite → PostgreSQL**：无并发写、无分区、无复制 → 必须先迁；
2. **服务端渲染 → API + 前端分离**：v0 是 Jinja 模板直出，无法支撑小程序/App 多端，也无法做 CDN 缓存；
3. **无异步层**：v0 没有 Kafka/Worker，AI 能力（五屏核心）无处安放；
4. **无鉴权体系**：v0 是 session + 明文密码 → JWT + bcrypt/argon2 + 刷新令牌轮转；
5. **单容器部署**：无 HPA、无熔断，流量激增 = 直接崩。

---

## 2. 容量规划（所有后续设计的锚点）

### 2.1 流量模型（10 万 DAU 基准）

| 指标 | 估算 | 依据 |
|---|---|---|
| 峰值活跃（20:00–22:00） | 4 万用户在线 | 40% 日活集中晚高峰 |
| 峰值读 QPS | 2,000–3,000 | 人均 15 交互/活跃小时 × 缓存命中后回源折减 |
| 峰值作答写 QPS | 400–600 | 人均 30 题/日 × 时段集中系数 |
| SSE 长连接（模拟面试） | 峰值 5,000 | 5% DAU 同时面试 |
| LLM 调用 | 日 30 万次（峰值 ~40 QPS） | JD 解析 1 万 + 问答点评 20 万 + 模拟面试 10 万轮 |
| 作答流水 | 300 万行/日 ≈ 1GB/日 | 含题干快照与作答文本 |
| 面经文档量 | 日新增 5k–2 万篇（爬虫） | 受控频率 |

### 2.2 各层容量结论

| 层 | 容量设计 | 余量 |
|---|---|---|
| 网关（APISIX） | 3 节点 × 8C16G，限流矩阵见 §8 | 单节点 2 万 QPS 级，余量 >10× |
| FastAPI 业务 Pod | 峰值 3,000 QPS ÷ 单 Pod 300 QPS（4 worker）= 10 Pod，HPA 目标 60% CPU，常态 6–12 Pod | HPA 上限 40 |
| PG 主库 | 读写分离后回源写 ~100 batch/s（Kafka 合并后），单实例 32C128G 足够 | 预埋分片键，见 §5.7 |
| Redis | 3 主 3 从 Cluster；热点题库缓存 ~5GB，会话 ~2GB（500 万用户 × 400B） | Cluster 可横扩 |
| Kafka | 3 broker；作答 topic 6 分区、峰值 600 msg/s，吞吐余量 >100× | 关键在延迟与堆积监控 |
| LLM Worker | 令牌桶：主模型并发 60 + 备用模型并发 30；堆积时排队可见化（§6.4） | 成本护栏见 §6.6 |

---

## 3. 工程结构：模块化单体（Mandatory First Step）

### 3.1 为什么不是直接微服务

10 万 DAU 的读 QPS（3k）和写 QPS（600）**单模块化单体 + 读写分离 PG 就能扛住**。直接上 7 个微服务的代价：分布式事务、链路追踪、7 套 CI/CD、跨服务联调——在团队 <10 人时是自杀式复杂度。但**必须按微服务的边界拆包**，让未来拆分是「搬目录」而不是「重写」。

### 3.2 代码组织（单仓库，Python 3.12 + FastAPI）

```
server/
├── src/faceto/
│   ├── main.py                    # 组装：只做 include_router + 中间件挂载
│   ├── core/                      # 框架层（不含业务）
│   │   ├── config.py              # pydantic-settings，全部环境变量集中
│   │   ├── db.py                  # async engine / session factory（读写路由）
│   │   ├── cache.py               # redis 客户端 + singleflight 装饰器
│   │   ├── mq.py                  # kafka producer 封装（幂等 producer）
│   │   ├── security.py            # JWT 签发校验、argon2、权限依赖注入
│   │   ├── ratelimit.py           # 网关之外的应用级兜底限流
│   │   └── observability.py       # OTel tracer / metrics / 日志上下文
│   ├── domains/                   # ★ 业务域 = 未来微服务边界
│   │   ├── user/                  # router.py models.py service.py repo.py
│   │   ├── job/                   # S1/S2：JD 管理、考点权重、画像
│   │   ├── question/              # S3/S4：题库、考点标注、版本
│   │   ├── practice/              # S3/S4：计划、作答、进度、错题
│   │   ├── exp/                   # S3：面经检索与聚合
│   │   ├── interview/             # S5：模拟面试、SSE
│   │   └── profile/               # S2/S5 回流：掌握度、弱项
│   ├── ai/                        # LLM 接口抽象层（见 §6.5）
│   └── workers/                   # 独立进程入口（消费 Kafka）
│       ├── ai_worker.py           # jd.parse / answer.grade / exp2q
│       ├── flush_worker.py        # 作答合并落库
│       ├── crawler_worker.py      # 面经采集（可整体停用）
│       └── notify_worker.py
├── migrations/                    # alembic
├── tests/                         # 契约测试 + 关键路径集成测试
└── deploy/                        # docker-compose（MVP）/ helm（规模化）
```

### 3.3 依赖铁律（对抗性审查会盯的点）

1. **域之间只准 import 对方的 service 接口，不准 import repo/model**——跨域数据访问一律走接口或事件，未来拆分时依赖单向可追溯；
2. `core` 不准 import 任何 `domains/*`；
3. 跨域写操作用**领域事件**（发 Kafka），不用跨域直接写表：如作答完成 → `answer.graded` 事件 → profile 域消费更新掌握度。这是未来拆服务的接缝；
4. 每个域目录必须能在 30 分钟内剥离成独立服务（router 前缀 = 服务名 = K8s namespace 预留）。

---

## 4. API 设计规范

### 4.1 总规范

- REST + JSON，前缀 `/api/v1/*`；**从第一天就版本化**，客户端带 `X-Client-Version`；
- 鉴权：`Authorization: Bearer <access_token>`（15min）+ `refresh_token`（30d，HttpOnly Cookie，轮转 + 撤销列表存 Redis）；
- 幂等：所有写接口接受 `Idempotency-Key` 头（作答提交**必须**带，防重刷/重试双写）；
- 分页：游标分页（`?cursor=`），禁用 offset 深翻页（数据库与缓存都扛不住深跳）；
- 错误体统一：`{"code": "PLAN_NOT_FOUND", "message": "...", "request_id": "..."}`，`request_id` 全链路透传，错误码按域前缀（`AUTH_`/`JOB_`/`PRC_`…）；
- 时间一律 UTC ISO8601，客户端本地化。

### 4.2 核心接口清单（对应五屏）

```
S1 导入
POST   /api/v1/jobs                        # 创建岗位：{source: text|url|image, payload}
       → 202 {job_id}                      # 同步只建记录，解析异步
GET    /api/v1/jobs                        # 我的岗位列表（缓存）
GET    /api/v1/jobs/{id}                   # 画像（AI 解析完成后返回，未完成返回 status）
POST   /api/v1/jobs/{id}/reparse           # 重新解析（限频）

S2 画像（读为主，全部可缓存）
GET    /api/v1/jobs/{id}/points            # 考点+权重+掌握度
PUT    /api/v1/jobs/{id}/points            # 用户手工调权重（触发计划重排，异步）

S3 计划 / 面经
POST   /api/v1/jobs/{id}/plans             # 生成 N 天计划（同步骨架 + 异步选题）
GET    /api/v1/plans/{id}                  # 计划详情（含每日模块）
GET    /api/v1/plans/{id}/progress         # 进度（Redis 直读，不落库查询）
GET    /api/v1/exp?point_id=&cursor=       # 面经检索（ES，独立降级开关）

S4 刷题 / 详情
GET    /api/v1/plans/{id}/next             # 下一题（含考点溯源信息）
POST   /api/v1/answers                     # 提交作答 ★核心写路径
       → 202 {answer_id}                   # 客观题同步判分返回，问答题 AI 点评异步
GET    /api/v1/answers/{id}/review         # AI 点评结果（未就绪返回 202 + retry_after）
GET    /api/v1/questions/{id}              # 题目详情 + 双溯源（JD 原句 + 面经出处）

S5 模拟面试
POST   /api/v1/interviews                  # 创建会话（选定岗位考点范围）
GET    /api/v1/interviews/{id}/stream      # ★SSE：面试官提问流
POST   /api/v1/interviews/{id}/turns       # 提交一轮回答
       → SSE 流返回追问 + 实时考点评估事件
GET    /api/v1/interviews/{id}/report      # 会话报告（会话结束异步生成）

任务状态通用
GET    /api/v1/tasks/{task_id}             # 所有 AI 任务统一状态查询（轮询兜底）
```

### 4.3 SSE 设计细节（对抗审查高发区）

- 事件格式：`event: token | point_eval | done | error`，心跳 `:ping` 每 15s；
- 网关侧：APISIX 单独 upstream group，`proxy_read_timeout 300s`，关闭缓冲（`X-Accel-Buffering: no`）；
- 断线恢复：客户端带 `Last-Event-ID`（= 服务端每 N token 落 Redis 的位点），重连续播而非重来——**防止断线重连导致 LLM 费用翻倍**；
- Pod 漂移保护：SSE 会话状态（当前轮次、已生成文本）存 Redis，不存内存——Pod 被杀用户重连即可恢复。

---

## 5. 数据模型（核心表设计）

### 5.1 命名与通用约定

- 全表小写蛇形、复数；主键 `id BIGINT GENERATED ALWAYS AS IDENTITY`；
- **所有用户维度表带 `user_id`**（分片键预留，迁移到分库时按它 hash）；
- 软删除仅用于合规需要（面经 UGC），业务数据用状态字段；
- 审计字段：`created_at / updated_at timestamptz`。

### 5.2 核心表（DDL 级要点）

```sql
-- 岗位域
jobs(id, user_id, title, company, source_type,          -- text|url|image
     raw_text, ocr_status, parse_status,                -- pending|done|failed
     cos_key,                                          -- 截图对象存储键
     created_at)                                       -- 分区: 无需，量小
job_points(id, job_id, point_name, dimension,           -- 技能/知识/项目
     weight numeric, source,                            -- ai|user|jd_sentence
     jd_evidence jsonb,  mastery_override)              -- JD原句引用数组

-- 题库域（读热点）
questions(id, type, stem, options jsonb, answer, analysis,
     chapter_id, difficulty, version int,               -- 版本化: 修正题目不改历史
     status)                                            -- draft|active|retired
question_points(question_id, point_name)                -- 考点标注多对多
point_stats(point_name, ref_count, sample_freq)         -- 高频考点聚合（物化）

-- 刷题域（写热点 → 分区 + 合并落库）
plans(id, user_id, job_id, days, status, created_at)
plan_items(id, plan_id, day_no, module, point_name,
     question_count, done_count)
answers(                                              -- ★ 按月 RANGE 分区
  id, user_id, plan_id, question_id,
  question_snapshot jsonb,                             -- 题干快照（版本隔离）
  user_answer, is_correct, self_rating,
  ai_review jsonb, ai_review_status,
  idempotency_key,                                    -- 唯一索引 (user_id, idempotency_key)
  created_at) PARTITION BY RANGE (created_at);

-- 异步任务域（统一 AI 任务表 = 状态查询 + 幂等 + 审计）
ai_tasks(id, user_id, task_type,                       -- jd_parse|answer_review|interview_turn
     payload jsonb, result jsonb,
     status,                                           -- queued|running|done|failed|degraded
     model_used, tokens_in, tokens_out, cost_cents,    -- ★成本字段从第一天就有
     attempts, next_retry_at,
     created_at) PARTITION BY RANGE (created_at);

-- 模拟面试域
interview_sessions(id, user_id, job_id, status,
     point_checklist jsonb, started_at, ended_at)
interview_turns(id, session_id, turn_no, role,
     content, point_tags jsonb, score, created_at)

-- 掌握度（事件溯源，可全量重算）
mastery_events(id, user_id, point_name, delta, reason,  -- answer|review|interview
     created_at) PARTITION BY RANGE (created_at);
mastery(user_id, point_name, score numeric,             -- 物化视图/表，由事件重算
     answered, correct, updated_at)
```

### 5.3 Redis Key 规范

```
session:{user_id}                 → 刷新令牌，TTL 30d
plan:progress:{plan_id}           → Hash 进度计数，TTL 7d（冷数据回源重算）
q:cache:{question_id}             → 题目 JSON，TTL 24h + 逻辑过期（防雪崩）
job:profile:{job_id}              → 画像 JSON，TTL 1h，写后失效
rate:{scope}:{key}                → 限流计数器（网关为主，应用兜底）
llm:bucket:main                   → 令牌桶状态
idem:answer:{user_id}:{key}       → 幂等锁，TTL 24h
sse:state:{session_id}            → SSE 会话态，TTL 2h
```

### 5.4 击穿/穿透/雪崩三件套

- **击穿**：热点 key 过期瞬间 → `core/cache.py` 内置 singleflight（进程内 `asyncio.Lock` per-key + 短 TTL 负缓存占位）；
- **穿透**：不存在的 ID → 负缓存 60s + 接口层参数校验（ID 一律数字/ULID 白名单）；
- **雪崩**：逻辑过期（值内嵌 `expire_at`，过期后返回旧值 + 异步刷新），TTL 加随机抖动 ±20%。

### 5.5 ES 索引

- `exp_docs-{yyyy.MM}` 按月 rollover，热 3 月 + 温 9 月 + 冷归档对象存储；
- 字段：`title, source(niuke|csdn|…), content(ik_max_word), points[], published_at, url_hash`（去重键）。

### 5.6 向量检索

- MVP 用 **pgvector**（JD embedding ↔ 考点 ↔ 面经语义匹配，量级 <百万），接口抽象在 `ai/embedding.py`，量过百万再迁 Milvus——不提前引入新组件。

### 5.7 分片预留的「不做假动作」原则

分片键只做三件事，**不提前做分库**：
1. 所有用户表带 `user_id` 且外键以它为前缀语义；
2. 唯一约束设计成「分片内唯一」（如 `answers` 唯一键是 `(user_id, idempotency_key)` 而非全局 `idempotency_key`）；
3. 禁止跨用户 JOIN 的查询模式进入代码评审清单。
满足这三条，未来 ShardingSphere/Vitess 类方案迁移是配置工作而非重写。

---

## 6. 异步任务层设计

### 6.1 Topic 与消息契约

| Topic | 生产者 | 消费者 | 语义 | 投递 |
|---|---|---|---|---|
| `jd.parse` | job 域 | ai_worker | 每岗位 1 条 | at-least-once + 任务表幂等 |
| `answer.grade` | practice 域 | ai_worker | 仅问答题 | 同上 |
| `answer.flush` | practice 域 | flush_worker | 批量合并 | 聚合写，见 6.3 |
| `interview.turn` | interview 域 | ai_worker | 每轮 1 条 | SSE 直推 + 任务表落档 |
| `crawler.push` | 定时器 | crawler_worker | 采集任务 | 可整体暂停（开关在配置中心） |
| `notify.send` | 各域 | notify_worker | 通知 | 批量削峰 |

消息信封统一：`{event_id (uuid), occurred_at, producer, payload, trace_id}`；**幂等键 = 业务表唯一约束**（如 `ai_tasks.idempotency_key`），消费端「先插任务表占位，再执行」，重复消息插入冲突即丢弃。

### 6.2 重试与死信

- 指数退避：30s → 2m → 10m → 30m，共 4 次；
- 4 次失败 → `*.dlq` topic + 告警；DLQ 有人工重放工具（管理后台一键）；
- LLM 特有：**内容审查拒绝 / 超长** 类失败不重试（重试也不会成功），直接标 `failed_bad_input`。

### 6.3 作答写合并（写路径核心）

```
POST /answers
  → ① Redis 幂等检查（防双击/重试）
  → ② 客观题：本地判分，直接返回结果
  → ③ 发 Kafka answer.flush（不等落库）
  → ④ 返回 202

flush_worker（每 200ms 或攒满 500 条触发）:
  → 按 user_id 分组 → COPY 批量插入 answers
  → 更新 plan:progress Redis 计数
  → 问题：进度有 <1s 的最终一致窗口 → 产品可接受（进度条非资金数据）
```

**降级**：Kafka 不可用时，practice 域自动切直写 PG（连接池限流），性能降但可用性不掉——核心刷题链路不绑死中间件。

### 6.4 AI Worker 与用户感知

- 任务表状态可查（`GET /tasks/{id}` 轮询兜底），前端主用 SSE/WS 推送完成事件；
- **排队可见化**：队列堆积时前端显示「预计 N 秒」，比无限转圈的用户体验好一个量级，且是天然背压；
- LLM 输出缓存：相同 `(prompt_hash, model)` 结果 Redis 缓存 7 天——重复 JD/相似作答直接命中，省真金白银。

### 6.5 LLM 抽象层（`src/faceto/ai/`）

```python
class LLMProvider(Protocol):
    async def chat(self, req: ChatRequest) -> ChatResponse  # 统一超时/重试/指标装饰
# 实现: VolcanoGLM(主) / LocalQwen(备用) / 未来任意 OpenAI 兼容
```

- 主备切换：连续 5 次失败或 P99 > 30s → 熔断切备用模型，半开探测恢复；
- 供应商配额错峰：JD 解析（白天低峰）优先，模拟面试（晚间高峰）保并发；
- **每个 Prompt 模板版本化**（`v` 字段入库），改 Prompt = 灰度实验，出问题可回滚。

### 6.6 成本护栏（上线激增时防「账单崩溃」）

- 每用户每日 LLM 调用上限（免费 20 次 / 会员 500 次，Redis 计数）；
- 全局日 token 预算熔断：达到 80% 告警、100% 自动降级（点评改模板生成、模拟面试排队延长）；
- `ai_tasks` 成本字段日报 → 单 DAU 成本可追踪，定价决策有据。

---

## 7. 鉴权与安全

1. **JWT**：access 15min 无状态校验（网关 Lua 层直接验签，不打到业务）；refresh 轮转 + Redis 撤销列表（登出/改密即时生效）；
2. **密码**：argon2id；登录失败按账号+IP 双维度限流（防撞库）；
3. **内容合规（面经 UGC + 用户作答）**：接入文本审核 API（异步，审核通过才入 ES）；模拟面试对话留存 90 天（合规审计需要），之后归档删除；
4. **防爬**：题库接口按用户级限流（如 60 req/min）+ 行为异常检测（QPS 突增 + 无作答交互的纯浏览账号）；
5. **越权**：所有资源接口强制 `owner == current_user` 检查（FastAPI 依赖注入统一做，禁止手工比对散落各处）；
6. **SSE**：连接需持有效 access token；单用户同时 SSE 连接数上限 3；
7. **敏感配置**：`.env` 不入库（已列入 .gitignore），生产用 K8s Secret。

---

## 8. 突发流量防护（「上线即爆」场景预案）

### 8.1 限流矩阵（四层，从粗到细）

| 层 | 机制 | 阈值基准 |
|---|---|---|
| CDN/WAF | 全局 QPS + 验证码升级 | 超历史峰值 5× 触发 JS 挑战 |
| 网关 | 按 IP / 用户 / 接口三维令牌桶 | 匿名 IP 60/min；注册用户 600/min；`POST /answers` 单用户 30/min |
| 应用 | 单接口兜底（Redis 计数） | 网关被绕过（内网直连）时生效 |
| 资源 | PG 连接池排队、LLM 令牌桶 | 保护自身不被上游拖死 |

### 8.2 上线激增剧本（按顺序自动执行）

```
L0 常态          HPA 6-12 Pod，一切照旧
L1 读放大        首页/题库静态化（SSG 片段 + CDN），题目缓存预热脚本提前跑
L2 注册洪峰      注册接口独立限流池 + 手机验证码队列削峰（发送限速）
L3 AI 洪峰       LLM 令牌桶收紧 → 排队可见化 → 免费额度熔断
L4 过载          降级矩阵（见 8.3），保「能登录、能刷题、能判分」
```

每级有明确 Prometheus 告警阈值触发，**预案写成代码（feature flag + 自动化），不写成 wiki**。

### 8.3 降级矩阵（哪些可以死，哪些必须活）

| 功能 | 降级行为 | 开关 |
|---|---|---|
| 面经检索（S3 侧栏） | 隐藏入口或展示静态精选 | `degrade.exp` |
| AI 点评（S4） | 返回模板化要点 + 「稍后重试」 | `degrade.ai_review` |
| 模拟面试（S5） | 新会话排队页 / 停止新建 | `degrade.interview` |
| 统计报表 | 展示昨日快照 | `degrade.stats` |
| JD 解析 | 提示「排队中」，先手动选考点模板 | `degrade.jd_parse` |
| **章节刷题/判分/进度** | **不降级——这就是核心链路** | — |

原则：**降级只砍 AI 和检索域，核心刷题链路 (登录→题目→判分→进度) 的每一跳都只依赖 PG/Redis/Kafka，且有 PG 单独存活的最低部署形态。**

### 8.4 数据库最后防线

- PG 主从延迟 > 5s：读流量自动切主（牺牲读扩展保一致）；
- Kafka 堆积 > 10 万：flush_worker 临时扩副本（K8s Job 式弹性消费）；
- Redis 整体故障：应用侧熔断直读 PG（缓存装饰器内置 fallthrough），接口变慢但全可用。

---

## 9. 可观测性与 SLO

### 9.1 SLO（对外承诺，倒逼架构）

| 指标 | 目标 |
|---|---|
| 核心刷题链路可用性 | 99.9%（月停机 < 43min） |
| 题目获取 P95 延迟 | < 200ms（不含 AI） |
| 作答提交 P95 | < 300ms（202 异步语义下） |
| AI 点评完成 P95 | < 60s（排队另计且可见） |
| SSE 首字节 | < 1.5s |

### 9.2 黄金四信号 + 业务指标

- 延迟/流量/错误/饱和度按接口维度打点（OTel → Prometheus）；
- **业务指标单独面板**：作答 QPS、判分正确率漂移（防题目数据事故）、AI 任务成功率/成本、SSE 并发数、队列堆积；
- 告警分级：P0（核心链路错误率 > 1%）电话、P1（队列堆积/主从延迟）IM、P2（成本异常）日报。

---

## 10. 测试与上线策略

1. **契约测试**：API 用 schemathesis 做属性测试（fuzz 输入不 500）；
2. **关键路径集成测试**：提交作答 → 判分 → 进度 → 掌握度回流，全链路跑通（testcontainers 起 PG/Redis/Kafka）；
3. **压测脚本**（上线前必跑，进 CI 夜间任务）：
   - 作答洪峰：5,000 用户虚拟用户 600 QPS 提交，验证合并落库与幂等；
   - SSE 并发：5,000 长连接 + 随机断线重连，验证续播与 Pod 漂移恢复；
   - 缓存击穿演练：热 key 强制过期 + 单副本压测；
4. **灰度发布**：API 版本路由按用户哈希分桶（5% → 50% → 100%），出问题秒回切。

---

## 11. 迁移方案（v0 → 新架构，不丢数据不停服）

1. **数据迁移**：SQLite → PG 用脚本直迁（用户/作答历史/收藏）；`questions.csv` → `questions` 表（`gen/` 管线的输出天然对齐字段）；迁移脚本幂等可重跑；
2. **双写过渡**（如需平滑）：v0 Flask 加一个「作答完成后发 Kafka」的旁路，新旧系统并行一周核对计数；
3. **域名切换**：网关把 `/api/*` 路由到新 FastAPI，`/`（旧页面）继续指向 Flask，直到前端新站上线；
4. **回滚保障**：切换期间 v0 完整保留可独立运行（本仓库现状即回滚形态）。

---

## 12. 迭代路线图与量化触发器（不拍脑袋拆服务）

| 阶段 | 形态 | 进入下一阶段的**量化触发器** |
|---|---|---|
| M1 MVP | FastAPI 模块化单体 + PG 主从 + Redis + Kafka，3–4 Pod | 产品验证：DAU > 1 万 |
| M2 增长 | + ES 上线面经、+ AI Worker 独立部署组、CDN 静态化 | **SSE 并发 > 1,500** 或 **AI Worker 单独占资源 > 40%** → 拆模拟面试服务 |
| M3 规模 | 拆 interview 服务；拆 exp 服务 | **PG 主库写 CPU 持续 > 60%** → 启动分库评估（先读写分离调优、再分区归档、最后分片） |
| M4 10万 DAU | 全七服务 + K8s 多可用区 + 全链路压测常态化 | — |

**反向约束（防过度设计）**：触发器未到不拆服务、不上 ES、不引 Milvus。每引入一个新组件必须在本文档追加「为什么现有组件不够」一节。

---

## 13. 对抗性审查预判（自攻击清单）

> 按用户要求，后续将做对抗性审查。先自列已知薄弱点与防御，供审查对靶：

| # | 攻击面 | 现状防御 | 残余风险 |
|---|---|---|---|
| 1 | **Kafka 对小团队是重运维**（3 broker + 监控 + DLQ 工具链） | M1 可用 Redis Stream 起步？——**决策：M1 直接上 Kafka**，因消息契约/幂等/DLQ 设计与实现无关，切成本低于晚切 | 团队 Kafka 经验不足 → 用托管服务（如云厂商 Kafka）规避自运维 |
| 2 | SSE 经网关/负载均衡的兼容坑（缓冲、超时、HTTP/2） | §4.3 已列三项（独立分组、关缓冲、心跳）；上线前 SSE 专项压测 | 云 LB 行为差异 → M1 用 nginx ingress 实测并记录基线 |
| 3 | 作答 202 异步语义下，用户秒回列表看不到刚提交的记录 | 进度读 Redis 计数（写入即 +1）；作答列表从 Kafka 消费到落库 < 1s | 极端堆积时秒开列表缺最后一条 → 前端乐观插入（本地已有作答数据） |
| 4 | LLM 缓存导致不同用户看到串题/串点评 | prompt_hash 含 user_id 维度（个性化字段参与哈希） | 缓存命中率下降 → 可配置取舍 |
| 5 | 面经爬虫的法律/封禁风险 | 频率受控 + robots 尊重 + 可整体摘除 + 来源标注 | 仍需法务过一次采集范围 |
| 6 | 刷题进度 1s 最终一致窗口被用户当 bug 投诉 | 产品文案「实时」改「准实时」；Redis 计数先行 | 低 |
| 7 | 单仓库模块化单体最终腐化成大泥球 | §3.3 依赖铁律 + 依赖方向 CI 检查（import-linter） | 需要坚持评审纪律 |
| 8 | 10 万 DAU 估算过于乐观/悲观导致过度或不足建设 | 触发器机制（§12）让扩容跟随真实指标 | 需要在监控里从第一天收集真实行为基线 |
| 9 | 成本失控（LLM + 基础设施双烧钱） | §6.6 三重护栏 | 免费额度定价需上线后校准 |
| 10 | 热门岗位（如字节安全岗）JD 相同导致缓存击穿反向：同一 JD 千人解析 | JD 文本 hash → 命中直接复用解析结果（LLM 缓存子集） | 需保证 JD hash 归一化（去空白/大小写） |

---

## 14. 技术栈定版

| 组件 | 选型 | 备注 |
|---|---|---|
| 语言/框架 | Python 3.12 + FastAPI + SQLAlchemy 2 (async) + Pydantic v2 | 复用 gen/ 管线生态 |
| DB | PostgreSQL 16 | 主从起步，分区表见 §5.2 |
| 缓存 | Redis 7 Cluster | |
| 队列 | Kafka 3.x（托管优先） | |
| 检索 | Elasticsearch 8（M2 起） | ik 分词 |
| 网关 | APISIX | Lua 验 JWT、限流、SSE 分组 |
| 部署 | Docker → K8s（HPA） | M1 可 docker-compose 多机 |
| 可观测 | OpenTelemetry + Prometheus/Grafana + Loki | trace_id 贯穿 HTTP→Kafka→Worker |
| CI/CD | GitHub Actions + 镜像仓库 + 灰度路由 | |

---

## 结语

本设计与上游架构文档的关系：架构文档定义「为什么这样分」，本文档定义「第一行代码怎么写、第一个表怎么建、第一次流量洪峰怎么活」。所有决策均可回溯到 §0 的四个物理量；所有扩容动作由 §12 的量化触发器驱动；所有已知弱点摊在 §13 等对抗性审查逐条打击。
