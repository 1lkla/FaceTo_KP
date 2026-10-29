# FaceTo KP · server（M1 MVP）

> 依据 `docs/backend-web-design.md` §3.2 工程结构实施的模块化单体。
> 本仓库形态 = 设计文档的 **M1 MVP**：FastAPI 单体 + 按域拆包（未来微服务边界）。

## 与设计文档的映射

| 设计要求 | 本实现 | 说明 |
|---|---|---|
| §3.2 目录结构 | `src/faceto/{core,domains/*,ai}` | 域目录 = 未来微服务边界 |
| §3.3 依赖铁律 | core 不 import domains；跨域只调 service 接口 | 见各 router.py 头部注释 |
| §4.2 API 契约 | `/api/v1/*` 全部核心接口 | 含 202 异步语义、Idempotency-Key、游标分页 |
| §4.3 SSE | `GET /interviews/{id}/stream` | event: token / point_eval / done / error，15s 心跳 |
| §5 数据模型 | `core/store.py` 内存实现 + JSON 快照落盘 + 预留 `user_id` 分片键语义 | **M1-dev 用内存存储**（权威副本仍在内存，快照防重启/热重载丢失），生产换 SQLAlchemy+PG（见 store.py 注释） |
| §6 异步任务层 | `core/tasks.py`（进程内任务表） | 生产替换为 Kafka topic + ai_worker/flush_worker |
| §6.5 LLM 抽象 | `ai/llm.py` Protocol + MockProvider | 生产接 VolcanoGLM(主)/LocalQwen(备) |
| §8.3 降级矩阵 | `core/config.py` degrade.* 开关 | AI 域接口读开关返回降级响应 |

## 运行

```bash
cd server
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn src.faceto.main:app --port 8787 --reload
# 打开 http://localhost:8787
```

演示账号（种子数据）：`demo@faceto.cn` / `demo1234`
（已预置一个解析完成的岗位画像，登录即可体验 S2→S5 全链路）

## 持久化（M1.1）

M1 的权威副本仍是进程内存，但会写 JSON 快照，避免 `--reload` 热重载或重启把作答记录清空：

- 快照路径：`server/data/store.json`（环境变量 `FT_STORE_PATH` 可改；`FT_STORE_PERSIST=0` 可关闭）；
- 写时机：每 `FT_STORE_FLUSH_INTERVAL`（默认 2s）周期落盘 + 进程退出时落盘（原子 tmp + `os.replace`）；
- 读时机：启动时恢复，失败（文件不存在 / schema 不符 / 解析异常）则回退种子数据；
- 种子数据**幂等**：题库按题干去重补录、面经按标题去重、demo 账号与演示岗位只在首次创建，
  因此 ID 不会漂移，浏览器 localStorage 里的 `job_id` / `plan_id` 重启后依然有效；
- 恢复后 `heal_after_restore()` 收敛被重启打断的异步任务（AI 点评 / JD 解析 / 面试报告判失败，可重触发）。

> 清空数据 = 删掉 `server/data/store.json` 后重启。

## 已知 dev 简化（生产替换点）

- 存储为进程内存（+ JSON 快照落盘，`--reload`/重启不丢；仍是单进程权威副本）→ 换 PG；
- 异步任务为 asyncio 后台协程 → 换 Kafka + Worker 进程；
- LLM 为规则模拟（JD 关键词抽取 / 模板点评 / 预设面试问题流）→ 换真实 Provider；
- JWT 为 HMAC-SHA256（与 jose 等价），密码为 PBKDF2 → 生产换 argon2id；
- SSE 断线续播（Last-Event-ID）未实现 → 生产按 §4.3 落 Redis 位点。
