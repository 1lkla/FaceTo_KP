# 网安面试刷题系统

本地可部署的面试刷题系统，仿 easthome CISP 章节刷题体验。基于开源项目 [EXAM-MASTER](https://github.com/CiE-XinYuChen/EXAM-MASTER)（MIT）二次改造，题库由 LLM 从本地面试知识库自动生成。

- 题库：**4837 题**（单选 1891 / 多选 1036 / 判断 886 / 问答 1024），**549 个章节**，全部带答案解析
- 来源：`~/workspace/40-knowledge/interview_prep/` 下 11 个库（duckpigdog 32 章、h4m5t 面经题库、goddemondemongod 30+ 公司真题、evilAdan0s 红队 128 题，以及 v2 新增：vvmdx 2023 届面经、Leezj9671 渗透面经、just0rg 面试题、Bypass007 应急响应笔记、tangxiaofeng7 面试 QA、we1h0 Web 安全面试、WindXaa 安卓逆向面试）
- v2 新题经 LLM 逐题答案复核（correct 92% / 修正 35 / 淘汰确证错题 17），复核+审计脚本见 `gen/review.py`、`gen/apply_review.py`、`gen/finalize_v2.py`

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
