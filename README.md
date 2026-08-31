# 网安面试刷题系统

本地可部署的面试刷题系统，仿 easthome CISP 章节刷题体验。基于开源项目 [EXAM-MASTER](https://github.com/CiE-XinYuChen/EXAM-MASTER)（MIT）二次改造，题库由 LLM 从本地面试知识库自动生成。

- 题库：**3400 题**（单选 1491 / 多选 717 / 判断 577 / 问答 615），**238 个章节**，全部带答案解析
- 来源：现有本地面试知识库（duckpigdog、h4m5t、goddemondemongod、evilAdan0s 等）+ 6 个知识驱动专题系列（共 **479 道新增题**：OWASP Top 10、LLM 安全攻防、组件与中间件、Java 安全、云与容器、应急响应与溯源）。专题题目按「原理 → 利用条件 → 检测 → 防御 → 面试场景」设计，并经生成后自动审校、字段校验和跨库去重。
- 题型分布：单选 1491、多选 717、判断 577、问答 615（v1 材料题 2921 + 专题 479）；专题原始生成 480 题，因 1 道题干超长淘汰，最终保留 479 题。

## 快速开始（Docker，推荐）

```bash
docker compose up -d
# 打开 http://localhost:32220 ，注册账号即可开始刷题
```

数据库持久化在 `./data/db/`，删容器不丢进度。

## 功能

- **章节练习**（首页）：章节卡片列表，显示每章总题数 / 已练 / 正确率 / 进度条，点进去从上次进度继续刷
- **问答题**：面试口述题，作答后展示参考答案 + 解析，点「我答对了/我答错了」自评，计入错题本
- 单选 / 多选 / 判断：即时判分 + 解析
- 错题本、收藏、答题历史、统计分析、模拟考试、定时模式、关键词搜索

## 本地运行（不用 Docker）

```bash
cd app
python3 -m venv venv && ./venv/bin/pip install -r requirements.txt
./venv/bin/python app.py        # http://localhost:32220
```

## 导入题库

```bash
# Docker
docker cp data/questions/output/questions.csv exam-master:/tmp/q.csv
docker exec exam-master python tools/import_csv.py /tmp/q.csv
# 本地
./app/venv/bin/python app/tools/import_csv.py data/questions/output/questions.csv
```

## 重新生成题库（LLM 管线）

模型配置在 `.env`（当前主用火山 glm-5.2，备用本地 Qwen3.8-27B，均 OpenAI 兼容协议）。

### 原有材料驱动题库

```bash
python3 gen/chunk.py            # 1. 切分 markdown → chunks.jsonl（424 块）
python3 gen/test_client.py      # 2. 测试模型连通性
python3 gen/generate.py         # 3. 并发出题（断点续跑；--only <repo> --limit N 可试产）
python3 gen/validate.py         # 4. 校验 + 去重
python3 gen/remap_chapters.py   # 5. 章节名重映射
python3 gen/to_csv.py           # 6. 导出 data/questions/output/questions.csv
GEN_CONCURRENCY=8               # 并发数，默认 8
```

题库源材料更新后，删掉 `data/questions/done.txt` 和 `data/questions/raw/` 即可全量重跑（约 200 万 token）。

### 知识驱动专题系列（推荐扩展方式）

专题大纲位于 `gen/series/`，目前包含 6 个系列、52 个细分专题：OWASP Top 10、LLM 安全攻防、组件与中间件漏洞、Java 安全、云与容器安全、应急响应与溯源。每个细分专题会经过「生成 → LLM 自审 → 结构校验 → 去重」流程。

```bash
# 试产单个专题
cd gen && .venv/bin/python series_gen.py --topic owasp-top10/a03-injection

# 生成指定系列（支持断点续跑）
cd gen && .venv/bin/python series_gen.py --series llm-security

# 校验全部专题 raw 结果
cd gen && .venv/bin/python series_gen.py --validate-only

# 与现有题库合并并导出 CSV
cd gen && .venv/bin/python export_series.py --start-id 2943
```

`data/questions/output/series_questions.csv` 是增量导入文件；`questions.csv` 是包含现有题库和专题题库的全量文件。新增系列题目会自动按专题章节归类，便于在首页分章节练习。

## 目录结构

```
app/                  # 刷题系统（Flask + SQLite，EXAM-MASTER 二次改造）
gen/                  # LLM 题库生成管线
data/questions/       # 切块、原始响应、校验结果、最终 CSV
data/db/              # Docker SQLite 数据卷
Dockerfile / docker-compose.yml
.env                  # 模型 API 配置（勿提交）
```

## 说明

- 问答题在模拟考试/定时模式中不参与自动判分（无法机判口述题）
- evilAdan0s 库（无答案）生成的题目，解析末尾标注「(答案由AI生成)」，请甄别
- 原 EXAM-MASTER 自带 881 道示例题已移除（备份在 `app/questions.csv.bak`）
