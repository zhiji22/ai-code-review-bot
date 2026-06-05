# AI Code Review Bot — 详细设计文档

> **项目名称**: AI Code Review Bot
> **版本**: v1.1
> **日期**: 2025-06-04
> **状态**: 设计阶段
>
> **v1.1 变更摘要** (基于 v1.0 评审):
> - DB: SERIAL → BIGINT IDENTITY, VARCHAR → TEXT, webhook_secret 加密, 新增 updated_at 触发器, 新增复合索引
> - API: 统一 {data, meta} 信封 + 标准 error 格式 + 游标分页 + rate-limit 响应头
> - 后端: 新增 Celery 任务重试/超时, 流水线错误降级策略, asyncio.gather 并行编排, DB 连接池配置
> - 评分: 引入来源置信度加权 + 容忍度阈值，去除任意 ×3 倍数
> - LLM: response_format 强制 JSON, 少样本提示, Pydantic 验证
> - 部署: 所有容器添加 CPU/内存限制, Redis 分库隔离, PG 内存上调
> - 新增 §15 安全加固 (JWT/Cookie/CSRF/CORS/IP白名单/Pydantic)
> - 新增 §16 运维与扩展 (OpenAPI/SSE/大PR/多语言/安装流程/GDPR/灾备)

---

## 目录

1. [项目概述](#1-项目概述)
2. [系统架构](#2-系统架构)
3. [技术栈与选型理由](#3-技术栈与选型理由)
4. [模块详细设计](#4-模块详细设计)
5. [数据库设计](#5-数据库设计)
6. [API 设计](#6-api-设计)
7. [核心业务流程](#7-核心业务流程)
8. [前端设计](#8-前端设计)
9. [部署方案](#9-部署方案)
10. [监控与运维](#10-监控与运维)
11. [测试策略](#11-测试策略)
12. [开发计划](#12-开发计划)
13. [风险评估与应对](#13-风险评估与应对)
14. [面试亮点](#14-面试亮点)
15. [安全加固](#15-安全加固)
16. [运维与扩展设计](#16-运维与扩展设计)

---

## 1. 项目概述

### 1.1 背景

代码审查（Code Review）是软件工程质量保障的核心环节，但人工审查耗时且标准不统一。AI Code Review Bot 作为 GitHub App 集成到开发流程中，在 PR 提交时自动触发审查，在几秒内给出质量评分、安全建议和性能优化提示。

### 1.2 目标

| 目标 | 衡量指标 |
|------|---------|
| 减少人工 Review 时间 | 目标减少 40% |
| 捕获常见代码问题 | 安全漏洞检测率 > 80% |
| 提供可操作的建议 | 建议采纳率 > 60% |
| 快速响应 | 单文件 Review < 10 秒 |

### 1.3 核心价值

- **对开发者**: 即时反馈，不等待人工 Review
- **对团队**: 统一代码质量标准，自动记录
- **对面试官**: 完整展示 AST 解析 + LLM + 异步队列 + 缓存 + 容器化部署的工程能力

---

## 2. 系统架构

### 2.1 整体架构图

```
                         ┌─────────────────────────────────────────────┐
                         │              GitHub Platform                 │
                         │  ┌───────────────────────────────────────┐   │
                         │  │         GitHub App (CodeReviewBot)     │   │
                         │  │         Webhook: pull_request          │   │
                         │  └──────────────────┬────────────────────┘   │
                         └─────────────────────┼───────────────────────┘
                                               │ HTTPS POST
                                               ▼
                    ┌──────────────────────────────────────────────┐
                    │              Nginx (反向代理/SSL)              │
                    │              Port: 443 → 8000                 │
                    └──────────────────────┬───────────────────────┘
                                           │
                    ┌──────────────────────▼───────────────────────┐
                    │           FastAPI 应用层 (Port 8000)          │
                    │  ┌─────────────┐  ┌──────────────────────┐   │
                    │  │  Webhook     │  │  Dashboard API        │   │
                    │  │  Handler     │  │  (REST endpoints)     │   │
                    │  └──────┬──────┘  └──────────────────────┘   │
                    │         │                                    │
                    │  ┌──────▼──────────────────────────────────┐ │
                    │  │         任务调度层 (Task Dispatcher)      │ │
                    │  │  1. 签名验证  2. 幂等检查  3. 入队         │ │
                    │  └──────┬──────────────────────────────────┘ │
                    └─────────┼────────────────────────────────────┘
                              │
                              ▼
                    ┌──────────────────────────────────────────────┐
                    │          Celery 异步任务队列 (Redis Broker)    │
                    │    ┌────────────────────────────────────┐     │
                    │    │      Review Worker (可水平扩展)       │     │
                    │    │                                      │     │
                    │    │  ┌─────────────────────────────┐    │     │
                    │    │  │    Pipeline A: AST 分析       │    │     │
                    │    │  │    (tree-sitter)              │    │     │
                    │    │  └──────────────┬──────────────┘    │     │
                    │    │                 │                    │     │
                    │    │  ┌──────────────▼──────────────┐    │     │
                    │    │  │    Pipeline B: 规则引擎       │    │     │
                    │    │  │    (安全/性能/风格检查)        │    │     │
                    │    │  └──────────────┬──────────────┘    │     │
                    │    │                 │                    │     │
                    │    │  ┌──────────────▼──────────────┐    │     │
                    │    │  │    Pipeline C: LLM 深度分析    │    │     │
                    │    │  │    (OpenAI API + 缓存检查)     │    │     │
                    │    │  └──────────────┬──────────────┘    │     │
                    │    │                 │                    │     │
                    │    │  ┌──────────────▼──────────────┐    │     │
                    │    │  │    结果聚合 + 评分计算         │    │     │
                    │    │  └──────────────┬──────────────┘    │     │
                    │    └─────────────────┼──────────────────┘     │
                    └──────────────────────┼───────────────────────┘
                                           │
                    ┌──────────────────────▼───────────────────────┐
                    │              数据存储层                        │
                    │  ┌────────────┐  ┌──────────┐  ┌──────────┐ │
                    │  │ PostgreSQL  │  │  Redis   │  │ pgvector │ │
                    │  │ (持久化)    │  │  (缓存)   │  │ (向量)   │ │
                    │  └────────────┘  └──────────┘  └──────────┘ │
                    └──────────────────────┬───────────────────────┘
                                           │
                    ┌──────────────────────▼───────────────────────┐
                    │          GitHub API (评论/状态)                │
                    │  ┌──────────────────────────────────────┐    │
                    │  │  Inline Comments + Summary + Status   │    │
                    │  └──────────────────────────────────────┘    │
                    └──────────────────────────────────────────────┘
```

### 2.2 数据流

```
PR 提交
  │
  ├─→ Webhook 到达 FastAPI
  │     ├─→ 验证 GitHub 签名 (HMAC-SHA256)
  │     ├─→ 检查 Redis 幂等 (PR + commit SHA)
  │     └─→ 推送到 Celery 队列
  │
  ├─→ Celery Worker 消费
  │     ├─→ 调用 GitHub API 获取 diff
  │     ├─→ Pipeline A: AST 分析变更文件
  │     ├─→ Pipeline B: 规则引擎匹配
  │     ├─→ Pipeline C: LLM 生成建议 (带缓存)
  │     └─→ 结果聚合 + 评分
  │
  ├─→ 结果存储
  │     ├─→ PostgreSQL: Review 记录 + 详细结果
  │     ├─→ pgvector: 代码片段向量 (用于相似问题搜索)
  │     ├─→ Redis: Review 结果缓存 (TTL 24h)
  │     └─→ GitHub API: PR 评论 + Check Status
  │
  └─→ Dashboard (异步更新)
        └─→ React 前端查询 API → 展示统计
```

---

## 3. 技术栈与选型理由

### 3.1 核心技术栈

| 层级 | 技术 | 版本 | 选型理由 |
|------|------|------|---------|
| **后端框架** | FastAPI | 0.115+ | 异步原生、类型安全、自动 OpenAPI 文档、社区活跃 |
| **数据库** | PostgreSQL | 16 | 企业级 RDBMS，JSONB 支持、pgvector 扩展 |
| **向量扩展** | pgvector | 0.7+ | 无需额外向量数据库，PostgreSQL 原生集成 |
| **缓存** | Redis | 7.2+ | 幂等检查、结果缓存、Celery Broker、速率限制 |
| **任务队列** | Celery | 5.4+ | Python 生态最成熟的异步任务框架 |
| **LLM** | OpenAI API | GPT-4o | 代码理解能力最强、API 稳定 |
| **AST 解析** | tree-sitter | 0.22+ | 多语言支持、增量解析、沙箱安全 |
| **前端** | React + TypeScript | React 18, TS 5 | 类型安全、生态最大、面试加分 |
| **UI 库** | Tailwind CSS + shadcn/ui | latest | 快速开发、设计一致、现代审美 |
| **容器** | Docker + Docker Compose | latest | 一键部署全栈 |
| **CI/CD** | GitHub Actions | — | 与 GitHub App 天然集成 |
| **监控** | Prometheus + Grafana | latest | 指标采集 + 可视化 |

### 3.2 Python 依赖清单

```
# requirements.txt

# --- Web 框架 ---
fastapi==0.115.6
uvicorn[standard]==0.32.1
python-multipart==0.0.12

# --- 数据库 ---
sqlalchemy[asyncio]==2.0.36
asyncpg==0.30.0
alembic==1.14.0
psycopg[binary]==3.2.3

# --- Redis ---
redis[hiredis]==5.2.0

# --- Celery ---
celery[redis]==5.4.0
flower==2.0.1

# --- LLM ---
openai==1.57.0
tiktoken==0.8.0
anthropic==0.40.0       # 可选: Claude 作为备选 LLM

# --- AST 分析 ---
tree-sitter==0.23.2
tree-sitter-python==0.23.6
tree-sitter-javascript==0.23.0
tree-sitter-typescript==0.23.2

# --- GitHub API ---
PyGithub==2.5.0
gidgethub==5.3.0
httpx==0.28.1

# --- 安全/认证 ---
pyjwt[crypto]==2.10.1
cryptography==44.0.0
python-jose[cryptography]==3.3.0
passlib[bcrypt]==1.7.4

# --- 工具库 ---
pydantic==2.10.3
pydantic-settings==2.6.0
python-dotenv==1.0.1
structlog==24.4.0
rich==13.9.4

# --- 测试 ---
pytest==8.3.4
pytest-asyncio==0.24.0
pytest-cov==6.0.0
httpx==0.28.1          # 测试中用 TestClient
respx==0.21.1          # mock httpx 请求
fakeredis==2.26.1       # mock Redis

# --- 代码质量 ---
ruff==0.8.4
mypy==1.13.0
pre-commit==4.0.1

# --- 监控 ---
prometheus-client==0.21.1
sentry-sdk[fastapi]==2.19.2
```

---

## 4. 模块详细设计

### 4.1 项目目录结构

```
ai-code-review-bot/
│
├── app/                           # FastAPI 主应用
│   ├── __init__.py
│   ├── main.py                    # FastAPI 入口
│   ├── config.py                  # 配置管理 (Pydantic Settings)
│   ├── dependencies.py            # FastAPI 依赖注入
│   │
│   ├── api/                       # API 路由层
│   │   ├── __init__.py
│   │   ├── webhook.py             # GitHub Webhook 接收
│   │   ├── reviews.py             # Review 查询 API
│   │   ├── repos.py               # 仓库管理 API
│   │   ├── auth.py                # 用户认证 API
│   │   ├── stats.py               # 统计数据 API
│   │   └── health.py              # 健康检查
│   │
│   ├── core/                      # 核心业务逻辑
│   │   ├── __init__.py
│   │   ├── github_client.py       # GitHub API 封装
│   │   ├── webhook_handler.py     # Webhook 处理逻辑
│   │   ├── review_engine.py       # Review 流水线编排
│   │   └── scoring.py             # 评分算法
│   │
│   ├── analyzers/                 # 代码分析器
│   │   ├── __init__.py
│   │   ├── base.py                # 分析器基类
│   │   ├── ast_analyzer.py        # AST 分析 (tree-sitter)
│   │   ├── rule_engine.py         # 规则引擎
│   │   ├── llm_analyzer.py        # LLM 分析
│   │   └── result_aggregator.py   # 多分析器结果聚合
│   │
│   ├── models/                    # 数据模型 (SQLAlchemy)
│   │   ├── __init__.py
│   │   ├── base.py                # Base, Session
│   │   ├── user.py                # 用户模型
│   │   ├── repository.py          # 仓库模型
│   │   ├── review.py              # Review 模型
│   │   ├── review_comment.py      # Review 评论模型
│   │   └── rule.py                # 自定义规则模型
│   │
│   ├── schemas/                   # Pydantic 请求/响应模型
│   │   ├── __init__.py
│   │   ├── webhook.py             # Webhook payload schema
│   │   ├── review.py              # Review 响应 schema
│   │   └── stats.py               # 统计 schema
│   │
│   ├── services/                  # 业务服务层
│   │   ├── __init__.py
│   │   ├── review_service.py      # Review 业务逻辑
│   │   ├── repo_service.py        # 仓库管理
│   │   ├── user_service.py        # 用户管理
│   │   ├── cache_service.py       # Redis 缓存
│   │   ├── vector_service.py      # pgvector 向量操作
│   │   └── notification.py        # 通知服务
│   │
│   ├── tasks/                     # Celery 异步任务
│   │   ├── __init__.py
│   │   ├── celery_app.py          # Celery 配置
│   │   ├── review_tasks.py        # PR Review 任务
│   │   └── report_tasks.py        # 定时报表任务
│   │
│   └── utils/                     # 工具函数
│       ├── __init__.py
│       ├── security.py            # JWT, 密码哈希
│       ├── github_crypto.py       # Webhook 签名验证
│       ├── rate_limiter.py        # 速率限制
│       └── logger.py              # 结构化日志
│
├── frontend/                      # React 前端
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts
│   ├── tailwind.config.js
│   ├── src/
│   │   ├── App.tsx
│   │   ├── main.tsx
│   │   ├── components/
│   │   │   ├── dashboard/
│   │   │   ├── reviews/
│   │   │   ├── settings/
│   │   │   └── common/
│   │   ├── pages/
│   │   │   ├── Dashboard.tsx
│   │   │   ├── ReviewHistory.tsx
│   │   │   ├── ReviewDetail.tsx
│   │   │   ├── RepositorySettings.tsx
│   │   │   └── Login.tsx
│   │   ├── hooks/
│   │   ├── services/              # API 调用
│   │   ├── stores/                # Zustand state
│   │   └── types/
│   └── public/
│
├── tests/                         # 测试
│   ├── __init__.py
│   ├── conftest.py                # pytest fixtures
│   ├── unit/
│   │   ├── test_webhook_handler.py
│   │   ├── test_ast_analyzer.py
│   │   ├── test_rule_engine.py
│   │   ├── test_llm_analyzer.py
│   │   ├── test_scoring.py
│   │   └── test_cache_service.py
│   ├── integration/
│   │   ├── test_review_flow.py
│   │   ├── test_github_client.py
│   │   └── test_celery_tasks.py
│   └── fixtures/
│       ├── webhook_payloads/      # GitHub Webhook 样例
│       └── sample_code/           # 测试用代码样本
│
├── docker/                        # Docker 配置
│   ├── Dockerfile.backend
│   ├── Dockerfile.frontend
│   ├── Dockerfile.worker
│   └── nginx.conf
│
├── docker-compose.yml             # 全栈编排
├── docker-compose.dev.yml         # 开发环境
├── .env.example                   # 环境变量模板
├── pyproject.toml                 # Python 项目配置
├── Makefile                       # 常用命令快捷方式
├── README.md
└── docs/
    ├── API.md                     # API 文档
    ├── DEPLOYMENT.md              # 部署指南
    └── ARCHITECTURE.md            # 架构详解
```

### 4.2 核心模块说明

#### 4.2.1 Webhook Handler (`app/api/webhook.py`)

**职责**: 接收并验证 GitHub Webhook

```
输入: HTTP POST /webhook (GitHub 格式)
处理:
  1. 验证 X-Hub-Signature-256 (HMAC-SHA256)
  2. 解析 event 类型 (pull_request)
  3. 检查 action (opened, synchronize, reopened)
  4. Redis 幂等检查 (key: pr:{repo}:{pr_number}:{commit_sha})
  5. 推送 Celery 任务
输出: 202 Accepted + task_id
```

关键接口:
```python
@router.post("/webhook")
async def handle_webhook(
    request: Request,
    x_hub_signature: str = Header(...),
    x_github_event: str = Header(...),
) -> JSONResponse:
    """接收 GitHub Webhook，验证签名后异步入队"""
```

#### 4.2.2 Review Engine (`app/core/review_engine.py`)

**职责**: 编排整个 Review 流水线

```
Pipeline:
  1. 获取 PR diff (GitHub API)
  2. 过滤变更文件 (.py, .js, .ts, .java 等)
  3. 对每个文件并行执行 (asyncio.gather):
     a. AST 分析 → 结构问题
     b. 规则引擎 → 安全/性能/风格
     c. LLM 分析 → 深度建议 (带缓存)
     ⚠️ 并行度通过 asyncio.Semaphore 控制，避免 OOM
  4. 结果聚合 → 评分计算
  5. 生成 PR 评论
  6. 发布到 GitHub
  7. 存储到数据库
```

**错误处理与容错策略**:

```python
# 各分析器独立失败不影响整体 Review
try:
    ast_report = await ast_analyzer.analyze(...)
except Exception as e:
    logger.warning("ast_analyzer_failed", error=str(e))
    ast_report = ASTReport.empty()  # 降级为空报告

# LLM 失败时使用 AST + 规则引擎的子集结果
try:
    llm_result = await llm_analyzer.analyze(...)
except (OpenAIRateLimitError, OpenAITimeoutError) as e:
    logger.warning("llm_analyzer_failed", error=str(e))
    llm_result = LLMReviewResult.empty(reason="LLM temporarily unavailable")
    # 仍以 AST + 规则结果继续完成 Review
```

**并行编排** (每文件三分析器并行，多文件通过 Semaphore 限流):

```python
async def review_files(self, files: list[FileDiff]) -> list[FileReport]:
    sem = asyncio.Semaphore(self.config.max_concurrent_files)  # 默认 4
    async def _one(f):
        async with sem:
            return await asyncio.gather(
                ast_analyzer.analyze(f),
                rule_engine.check(f),
                llm_analyzer.analyze(f),
                return_exceptions=True,
            )
    return await asyncio.gather(*[_one(f) for f in files])
```

关键接口:
```python
class ReviewEngine:
    async def review_pull_request(
        self, repo_full_name: str, pr_number: int, commit_sha: str
    ) -> ReviewResult:
        """执行完整的 PR Review 流水线"""
```

#### 4.2.3 Celery 任务配置 (`app/tasks/celery_app.py`)

```python
from celery import Celery

app = Celery("ai_review_bot", broker=settings.CELERY_BROKER_URL)

# --- 全局限流与容错 ---
app.conf.update(
    task_acks_late=True,                  # 任务完成后再 ack，防止 worker 崩溃丢任务
    task_reject_on_worker_lost=True,      # worker 挂掉时拒绝任务，让其他 worker 接手
    worker_prefetch_multiplier=1,         # 避免一个 worker 预取过多任务
    task_time_limit=600,                  # 硬超时 10 分钟 (整个 PR review)
    task_soft_time_limit=480,             # 软超时 8 分钟 (让任务优雅退出)
    task_default_retry_delay=30,          # 重试间隔 30s
    task_default_max_retries=3,           # 最多重试 3 次
    broker_connection_retry_on_startup=True,
)
```

```python
# app/tasks/review_tasks.py
@app.task(
    bind=True,
    autoretry_for=(OpenAIRateLimitError, httpx.TimeoutException),
    retry_backoff=True,                   # 指数退避: 30s, 60s, 120s
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=3,
)
def review_pull_request(self, repo_full_name: str, pr_number: int, commit_sha: str):
    """PR Review 任务，对 LLM 限流/网络异常自动重试"""
    ...
```

**数据库连接池**:

```python
# app/config.py
DB_POOL_SIZE = 10           # 常规 worker
DB_MAX_OVERFLOW = 20
DB_POOL_RECYCLE = 3600      # 1h 回收，防止 PG 断连
DB_POOL_PRE_PING = True      # 连接前 ping，防止使用过期连接
# Worker 独立 pool: POOL_SIZE=5 (worker 内不要共享 app 的 pool)
```

#### 4.2.4 AST Analyzer (`app/analyzers/ast_analyzer.py`)

**职责**: 使用 tree-sitter 解析代码结构

```
能力:
  - 检测复杂度过高的函数 (圈复杂度)
  - 发现未使用的导入
  - 识别深层嵌套
  - 发现重复代码块
  - 统计代码行数/注释比例
支持语言: Python, JavaScript, TypeScript (可扩展)
```

关键接口:
```python
class ASTAnalyzer:
    def analyze(self, file_path: str, code: str, language: str) -> ASTReport:
        """解析代码 AST，返回结构化报告"""
```

#### 4.2.5 Rule Engine (`app/analyzers/rule_engine.py`)

**职责**: 基于预定义规则检测代码问题

```
规则类别:
  - security: SQL注入、XSS、硬编码密钥、不安全反序列化
  - performance: N+1查询、不必要的循环、大数据量未分页
  - style: 命名规范、函数长度、参数数量
  - best_practices: 错误处理、日志记录、类型注解

每条规则:
  - id: 规则唯一标识 (e.g., "SEC001")
  - severity: critical / warning / info
  - pattern: 正则或 AST 模式
  - message: 问题描述 + 修复建议
  - languages: 适用的编程语言
```

关键接口:
```python
class RuleEngine:
    def check(self, code: str, language: str, rules: list[Rule]) -> list[RuleViolation]:
        """对代码执行规则检查，返回违规列表"""
```

#### 4.2.6 LLM Analyzer (`app/analyzers/llm_analyzer.py`)

**职责**: 使用 LLM 进行深度代码理解

```
策略:
  1. 先检查 Redis 缓存 (key: llm:{hash(code_diff)})
  2. 缓存未命中 → 构造 prompt → 调用 OpenAI
  3. 结构化输出 (JSON schema):
     - issues: [{line, severity, category, message, suggestion}]
     - summary: 整体评价
     - score: 0-100
  4. 结果写入缓存 (TTL 24h)
  5. Token 用量记录到数据库

Token 优化:
  - 只发送 diff 而非整个文件
  - system prompt 复用 (prompt caching)
  - batch 处理多个文件
  - gpt-4o-mini 处理简单文件，gpt-4o 处理复杂文件
```

关键接口:
```python
class LLMAnalyzer:
    async def analyze(
        self, code_diff: str, file_context: str, language: str
    ) -> LLMReviewResult:
        """使用 LLM 分析代码差异"""
```

#### 4.2.7 Result Aggregator (`app/analyzers/result_aggregator.py`)

**职责**: 聚合三个分析器的结果，生成最终 Review

```
输入:
  - ASTReport (结构问题)
  - list[RuleViolation] (规则违规)
  - LLMReviewResult (深度建议)

处理:
  1. 去重 (相同位置的问题合并)
  2. 按严重度排序
  3. 计算综合评分:
     score = base(100)
       - critical_issue * 10
       - warning * 5
       - info * 1
  4. 生成 PR 评论格式:
     - 概要表 (评分/问题数)
     - 按文件分组的行内评论
     - 总结与建议

输出: ReviewResult (存入数据库 + 发往 GitHub)
```

---

## 5. 数据库设计

### 5.0 通用约定

> **设计规范**（适用于所有表）:
> - **主键**: `BIGINT GENERATED ALWAYS AS IDENTITY`（非 `SERIAL`，避免 32 位溢出）
> - **外键**: `BIGINT`（与主键类型一致）
> - **字符串**: `TEXT`（PostgreSQL 中 `VARCHAR(N)` 无性能优势，仅在业务需要明确长度约束时使用）
> - **时间戳**: `TIMESTAMPTZ`（始终带时区）
> - **`updated_at`**: 通过触发器自动更新（非仅 `DEFAULT NOW()`）
> - **命名**: 表名复数、蛇形命名（snake_case）
> - **敏感字段**: 加密存储（`BYTEA` 或应用层加密）

```sql
-- 通用 updated_at 触发器（所有表共享）
CREATE OR REPLACE FUNCTION trigger_set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
```

### 5.1 ER 图

```
┌──────────────┐       ┌──────────────────┐       ┌──────────────────┐
│    users     │       │   repositories   │       │     reviews      │
├──────────────┤       ├──────────────────┤       ├──────────────────┤
│ id (PK)      │──┐    │ id (PK)          │──┐    │ id (PK)          │
│ github_id    │  │    │ github_id        │  │    │ repo_id (FK)     │
│ username     │  │    │ full_name        │  ├───→│ pr_number        │
│ email        │  ├───→│ owner_id (FK)    │  │    │ commit_sha       │
│ avatar_url   │  │    │ installation_id  │  │    │ status           │
│ created_at   │  │    │ webhook_secret   │  │    │ overall_score    │
└──────────────┘  │    │ settings (JSONB) │  │    │ created_at       │
                  │    │ created_at       │  │    │ completed_at     │
                  │    └──────────────────┘  │    └────────┬─────────┘
                  │                          │             │
                  │    ┌──────────────────┐  │             │ 1:N
                  │    │     rules        │  │             ▼
                  │    ├──────────────────┤  │    ┌──────────────────┐
                  └───→│ id (PK)          │  │    │ review_comments  │
                       │ repo_id (FK)     │──┘    ├──────────────────┤
                       │ rule_id          │       │ id (PK)          │
                       │ category         │       │ review_id (FK)   │
                       │ severity         │       │ file_path        │
                       │ pattern          │       │ line_number      │
                       │ message          │       │ source           │
                       │ enabled          │       │ severity         │
                       └──────────────────┘       │ category         │
                                                  │ message          │
                                                  │ suggestion       │
                       ┌──────────────────┐       │ created_at       │
                       │   llm_usage      │       └──────────────────┘
                       ├──────────────────┤
                       │ id (PK)          │       ┌──────────────────┐
                       │ review_id (FK)   │       │ code_embeddings  │
                       │ model            │       ├──────────────────┤
                       │ prompt_tokens    │       │ id (PK)          │
                       │ completion_tokens│       │ repo_id (FK)     │
                       │ cost_usd         │       │ file_path        │
                       │ created_at       │       │ line_start       │
                       └──────────────────┘       │ line_end         │
                                                  │ code_hash        │
                                                  │ embedding        │
                                                  │ (vector(1536))   │
                                                  │ metadata (JSONB) │
                                                  │ created_at       │
                                                  └──────────────────┘
```

### 5.2 表定义

#### 5.2.1 users

```sql
CREATE TABLE users (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    github_id     BIGINT UNIQUE NOT NULL,
    username      TEXT NOT NULL,
    email         TEXT,
    avatar_url    TEXT,
    role          TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'admin')),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TRIGGER set_updated_at_users
    BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();
```

#### 5.2.2 repositories

```sql
CREATE TABLE repositories (
    id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    github_id         BIGINT UNIQUE NOT NULL,
    full_name         TEXT NOT NULL,                  -- owner/repo
    owner_id          BIGINT REFERENCES users(id),
    installation_id   BIGINT NOT NULL,                -- GitHub App Installation ID
    -- ⚠️ 加密存储: 应用层使用 Fernet/AES-GCM 加密后写入
    webhook_secret    BYTEA,                          -- 加密后的 Webhook 密钥 (用于签名验证)
    settings          JSONB NOT NULL DEFAULT '{}',    -- enabled_rules, excluded_paths, token_budget 等
    is_active         BOOLEAN NOT NULL DEFAULT TRUE,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_repos_github_id ON repositories(github_id);
CREATE INDEX idx_repos_installation ON repositories(installation_id);
CREATE INDEX idx_repos_owner ON repositories(owner_id);
CREATE TRIGGER set_updated_at_repositories
    BEFORE UPDATE ON repositories
    FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();
```

> **安全说明**: `webhook_secret` 使用应用层加密 (推荐 `cryptography.fernet.Fernet`，密钥从 `SECRET_KEY` 派生)。
> 仅在校验签名时解密到内存，绝不日志输出、绝不返回 API 响应。

#### 5.2.3 reviews

```sql
CREATE TABLE reviews (
    id                   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    repo_id              BIGINT NOT NULL REFERENCES repositories(id),
    pr_number            INTEGER NOT NULL,
    pr_title             TEXT,
    commit_sha           VARCHAR(40) NOT NULL,
    status               TEXT NOT NULL DEFAULT 'pending'
                         CHECK (status IN ('pending', 'processing', 'completed', 'failed')),
    overall_score        INTEGER CHECK (overall_score >= 0 AND overall_score <= 100),
    security_score       INTEGER CHECK (security_score >= 0 AND security_score <= 100),
    performance_score    INTEGER CHECK (performance_score >= 0 AND performance_score <= 100),
    maintainability_score INTEGER CHECK (maintainability_score >= 0 AND maintainability_score <= 100),
    files_reviewed       INTEGER NOT NULL DEFAULT 0,
    total_issues         INTEGER NOT NULL DEFAULT 0,
    critical_count       INTEGER NOT NULL DEFAULT 0,
    warning_count        INTEGER NOT NULL DEFAULT 0,
    info_count           INTEGER NOT NULL DEFAULT 0,
    error_message        TEXT,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at         TIMESTAMPTZ,

    UNIQUE(repo_id, pr_number, commit_sha)
);

-- 查询仓库下 review 列表 (分页排序) 的核心索引
CREATE INDEX idx_reviews_repo_created ON reviews(repo_id, created_at DESC);
CREATE INDEX idx_reviews_repo_pr ON reviews(repo_id, pr_number);
CREATE INDEX idx_reviews_status ON reviews(status);
CREATE INDEX idx_reviews_created ON reviews(created_at DESC);
```

#### 5.2.4 review_comments

```sql
CREATE TABLE review_comments (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    review_id           BIGINT NOT NULL REFERENCES reviews(id) ON DELETE CASCADE,
    file_path           TEXT NOT NULL,
    line_number         INTEGER,
    line_end            INTEGER,
    source              TEXT NOT NULL CHECK (source IN ('ast', 'rule', 'llm')),
    severity            TEXT NOT NULL CHECK (severity IN ('critical', 'warning', 'info')),
    category            TEXT,                   -- security, performance, style, etc.
    rule_id             TEXT,                   -- 对应的规则ID (如 SEC001)
    message             TEXT NOT NULL,
    suggestion          TEXT,
    confidence          REAL CHECK (confidence >= 0 AND confidence <= 1)
                        DEFAULT 1.0,            -- 分析器置信度 (LLM/规则匹配强度)
    github_comment_id   BIGINT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_comments_review ON review_comments(review_id);
CREATE INDEX idx_comments_file ON review_comments(file_path);
CREATE INDEX idx_comments_severity ON review_comments(severity);
```

#### 5.2.5 rules

```sql
CREATE TABLE rules (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    repo_id         BIGINT REFERENCES repositories(id),   -- NULL = 全局规则
    rule_id         TEXT NOT NULL,                         -- e.g., SEC001
    category        TEXT NOT NULL CHECK (category IN ('security', 'performance', 'style', 'best_practices')),
    severity        TEXT NOT NULL DEFAULT 'warning'
                    CHECK (severity IN ('critical', 'warning', 'info')),
    name            TEXT NOT NULL,
    description     TEXT,
    pattern         TEXT,                                   -- 正则或 AST 模式
    languages       TEXT[],
    suggestion      TEXT,
    enabled         BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_rules_repo ON rules(repo_id);
CREATE INDEX idx_rules_category ON rules(category);
CREATE TRIGGER set_updated_at_rules
    BEFORE UPDATE ON rules
    FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();
```

#### 5.2.6 llm_usage

```sql
CREATE TABLE llm_usage (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    review_id           BIGINT NOT NULL REFERENCES reviews(id) ON DELETE CASCADE,
    model               TEXT NOT NULL,
    prompt_tokens       INTEGER NOT NULL CHECK (prompt_tokens >= 0),
    completion_tokens   INTEGER NOT NULL CHECK (completion_tokens >= 0),
    total_tokens        INTEGER NOT NULL CHECK (total_tokens >= 0),
    cost_usd            DECIMAL(10, 6) NOT NULL CHECK (cost_usd >= 0),
    duration_ms         INTEGER,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_llm_usage_review ON llm_usage(review_id);
CREATE INDEX idx_llm_usage_created ON llm_usage(created_at DESC);
```

#### 5.2.7 code_embeddings (pgvector)

```sql
-- 启用 pgvector 扩展
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE code_embeddings (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    repo_id         BIGINT REFERENCES repositories(id),
    file_path       TEXT NOT NULL,
    line_start      INTEGER,
    line_end        INTEGER,
    code_hash       VARCHAR(64) UNIQUE NOT NULL,   -- SHA-256
    embedding       vector(1536),                    -- OpenAI text-embedding-3-small
    issue_category  TEXT,
    issue_summary   TEXT,
    metadata        JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 向量相似度索引 (HNSW)
CREATE INDEX idx_embeddings_vector ON code_embeddings
    USING hnsw (embedding vector_cosine_ops);

CREATE INDEX idx_embeddings_repo ON code_embeddings(repo_id);
CREATE INDEX idx_embeddings_hash ON code_embeddings(code_hash);
```

> **迁移管理**: 所有表结构变更通过 **Alembic** 管理 (`alembic revision --autogenerate`)，版本文件提交到 Git，部署时 `alembic upgrade head` 自动执行。

---

## 6. API 设计

### 6.1 API 总览

| 方法 | 路径 | 描述 | 认证 |
|------|------|------|------|
| POST | `/api/v1/webhook` | GitHub Webhook 入口 | Webhook签名 |
| GET | `/api/v1/health` | 健康检查 | 无 |
| GET | `/api/v1/reviews` | Review 列表 (分页) | JWT |
| GET | `/api/v1/reviews/{id}` | Review 详情 | JWT |
| GET | `/api/v1/reviews/{id}/comments` | Review 评论列表 | JWT |
| GET | `/api/v1/repos` | 用户的仓库列表 | JWT |
| PUT | `/api/v1/repos/{id}/settings` | 更新仓库配置 | JWT |
| GET | `/api/v1/repos/{id}/rules` | 仓库自定义规则 | JWT |
| POST | `/api/v1/repos/{id}/rules` | 添加自定义规则 | JWT |
| PUT | `/api/v1/repos/{id}/rules/{rule_id}` | 更新规则 | JWT |
| DELETE | `/api/v1/repos/{id}/rules/{rule_id}` | 删除规则 | JWT |
| GET | `/api/v1/stats/overview` | 全局统计 | JWT |
| GET | `/api/v1/stats/trends` | 趋势数据 | JWT |
| GET | `/api/v1/stats/repos/{id}` | 仓库维度统计 | JWT |
| POST | `/api/v1/auth/github` | GitHub OAuth 登录 | 无 |
| GET | `/api/v1/auth/me` | 当前用户信息 | JWT |

### 6.2 通用响应规范

#### 6.2.1 成功响应信封

所有 GET / 资源接口采用统一信封:

```json
{
  "data": { ... } | [ ... ],
  "meta": { ... }
}
```

#### 6.2.2 错误响应格式 (统一)

所有错误响应遵循同一格式，不使用裸字符串或 `{error: "..."}`:

```json
{
  "error": {
    "code": "validation_error",
    "message": "Request validation failed",
    "details": [
      {
        "field": "page",
        "message": "Must be >= 1",
        "code": "out_of_range"
      }
    ],
    "request_id": "req_2k8j1h"
  }
}
```

**错误码枚举**:

| HTTP | code | 场景 |
|------|------|------|
| 400 | `bad_request` | 请求格式错误、JSON 解析失败 |
| 401 | `unauthorized` | 缺少/无效 JWT |
| 403 | `forbidden` | 权限不足、签名验证失败 |
| 404 | `not_found` | 资源不存在 |
| 409 | `conflict` | 重复资源 (如重复 webhook) |
| 422 | `validation_error` | Pydantic 校验失败 |
| 429 | `rate_limit_exceeded` | 超过速率限制 |
| 500 | `internal_error` | 服务端异常 (不暴露详情) |

#### 6.2.3 分页规范

支持 **游标分页 (cursor)** 和 **偏移分页 (offset)** 两种模式:

```
# Cursor (推荐，默认，O(1) 复杂度)
GET /api/v1/reviews?cursor=eyJpZCI6MTIzfQ&limit=20

# Offset (兼容管理后台场景)
GET /api/v1/reviews?page=2&page_size=20
```

游标分页响应:
```json
{
  "data": [ ... ],
  "meta": {
    "has_next": true,
    "next_cursor": "eyJpZCI6MTQzfQ==",
    "limit": 20
  }
}
```

偏移分页响应:
```json
{
  "data": [ ... ],
  "meta": {
    "total": 156,
    "page": 2,
    "page_size": 20,
    "total_pages": 8
  }
}
```

#### 6.2.4 速率限制头

所有 JWT 认证接口返回速率限制头:

```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 95
X-RateLimit-Reset: 1747000000

# 超限时返回
HTTP/1.1 429 Too Many Requests
Retry-After: 60
```

| 接口层级 | 限制 | 窗口 |
|----------|------|------|
| Webhook | 100/min | 按 repo |
| Dashboard API | 100/min | 按 user |
| Stats API | 30/min | 按 user (聚合查询较重) |
| 写接口 (规则 CRUD) | 30/min | 按 user |

### 6.3 核心 API 详细设计

#### POST /api/v1/webhook

```json
// 请求头
X-Hub-Signature-256: sha256=<HMAC>
X-GitHub-Event: pull_request

// 请求体 (GitHub Webhook payload)
{
  "action": "opened",
  "pull_request": {
    "number": 42,
    "title": "Add user authentication",
    "head": { "sha": "abc123..." }
  },
  "repository": {
    "id": 123456,
    "full_name": "owner/repo"
  },
  "installation": { "id": 789012 }
}

// 响应 202 Accepted
{
  "data": {
    "task_id": "celery-task-uuid",
    "status": "queued"
  }
}

// 403 (签名失败)
{
  "error": {
    "code": "forbidden",
    "message": "Invalid webhook signature"
  }
}

// 409 (重复)
{
  "error": {
    "code": "conflict",
    "message": "Duplicate webhook, already processing"
  }
}
```

#### GET /api/v1/reviews

```json
// 请求参数
?repo_id=1&cursor=eyJpZCI6MTAwfQ&limit=20&status=completed&sort=-created_at

// 响应 200
{
  "data": [
    {
      "id": 101,
      "pr_number": 42,
      "pr_title": "Add user authentication",
      "commit_sha": "abc123...",
      "status": "completed",
      "overall_score": 85,
      "security_score": 90,
      "performance_score": 80,
      "maintainability_score": 85,
      "total_issues": 5,
      "critical_count": 0,
      "warning_count": 3,
      "info_count": 2,
      "created_at": "2025-06-04T10:30:00Z",
      "completed_at": "2025-06-04T10:30:15Z"
    }
  ],
  "meta": {
    "has_next": true,
    "next_cursor": "eyJpZCI6MTAxfQ==",
    "limit": 20
  }
}
```

#### GET /api/v1/reviews/{id}

```json
// 响应 200
{
  "data": {
    "id": 101,
    "repo": {
      "id": 1,
      "full_name": "owner/repo"
    },
    "pr_number": 42,
    "pr_title": "Add user authentication",
    "commit_sha": "abc123...",
    "status": "completed",
    "scores": {
      "overall": 85,
      "security": 90,
      "performance": 80,
      "maintainability": 85
    },
    "summary": "Overall good code quality with minor performance concerns...",
    "files_reviewed": 8,
    "comments": [
      {
        "id": 1,
        "file_path": "src/auth.py",
        "line_number": 45,
        "source": "rule",
        "severity": "critical",
        "category": "security",
        "rule_id": "SEC001",
        "message": "SQL injection vulnerability: unsanitized input in query",
        "suggestion": "Use parameterized queries: cursor.execute(\"SELECT * FROM users WHERE id = %s\", (user_id,))",
        "confidence": 1.0
      },
      {
        "id": 2,
        "file_path": "src/api/users.py",
        "line_number": 120,
        "source": "llm",
        "severity": "warning",
        "category": "performance",
        "message": "N+1 query detected in user list endpoint",
        "suggestion": "Use select_related or prefetch_related to batch fetch related objects",
        "confidence": 0.85
      }
    ],
    "llm_usage": {
      "model": "gpt-4o",
      "total_tokens": 4500,
      "cost_usd": 0.0225
    },
    "created_at": "2025-06-04T10:30:00Z",
    "completed_at": "2025-06-04T10:30:15Z"
  }
}
```

#### GET /api/v1/stats/overview

```json
// 响应 200
{
  "data": {
    "total_reviews": 1247,
    "total_prs_reviewed": 892,
    "avg_score": 82.5,
    "avg_review_time_seconds": 12.3,
    "total_issues_found": 5832,
    "critical_issues_found": 234,
    "total_llm_cost_usd": 45.67,
    "reviews_last_7_days": 89,
    "score_distribution": {
      "90-100": 340,
      "80-89": 520,
      "70-79": 250,
      "60-69": 97,
      "0-59": 40
    }
  }
}
```

---

## 7. 核心业务流程

### 7.1 PR Review 流程 (时序图)

```
Developer       GitHub          FastAPI       Celery        OpenAI      PostgreSQL/Redis
   │               │               │            │              │              │
   │──创建 PR──────▶│               │            │              │              │
   │               │──Webhook──────▶│            │              │              │
   │               │               │──验证签名───│              │              │
   │               │               │──幂等检查──────────────────────────────▶│
   │               │               │──入队──────▶│              │              │
   │               │◀──202 Accept──│            │              │              │
   │               │               │            │──获取diff────│              │
   │               │◀──diff 数据──────────────────│              │              │
   │               │               │            │──AST分析──────│              │
   │               │               │            │──规则检查──────│              │
   │               │               │            │──缓存检查──────────────────▶│
   │               │               │            │──LLM分析─────▶│              │
   │               │               │            │◀──分析结果────│              │
   │               │               │            │──结果聚合──────────────────▶│
   │               │               │            │──存储结果──────────────────▶│
   │               │               │            │──发PR评论─────│              │
   │               │◀──评论数据───────────────────│              │              │
   │──看到评论─────│               │            │              │              │
   │◀──Review 结果─│               │            │              │              │
```

### 7.2 评分算法

```python
# 来源置信度权重 (用于对每个 issue 扣分时的加权)
SOURCE_CONFIDENCE = {
    "rule": 1.0,    # 规则匹配确定性高
    "ast":  0.95,   # AST 分析确定性高
    "llm":  0.75,   # LLM 结果存在一定不确定性
}

# 严重度基础扣分 (每发现一个问题扣的分数)
SEVERITY_PENALTY = {"critical": 10, "warning": 5, "info": 1}

# 归一化系数: 控制每 100 行代码的"问题容忍度"
# 例: 100 行允许 5 个 warning 才开始扣分
ISSUE_TOLERANCE_PER_100_LOC = {
    "critical": 0,
    "warning": 5,
    "info": 10,
}

def calculate_score(
    ast_issues: list[ASTIssue],
    rule_violations: list[RuleViolation],
    llm_issues: list[LLMIssue],
    lines_of_code: int,
) -> ReviewScores:
    """计算多维度评分

    设计原则:
    1. 按维度独立评分 (security / performance / maintainability)
    2. 用来源置信度加权 (LLM 结果扣分权重 < 规则引擎)
    3. 用代码量归一化 (大文件容许更多问题)
    4. 设容忍度阈值 (避免小文件因 1 个 info 就丢分)
    """

    base = 100
    loc_factor = max(lines_of_code / 100, 1)

    # 按来源标记每个 issue 的置信度
    all_issues: list[tuple[Issue, float]] = []
    for i in ast_issues:  all_issues.append((i, SOURCE_CONFIDENCE["ast"]))
    for i in rule_violations: all_issues.append((i, SOURCE_CONFIDENCE["rule"]))
    for i in llm_issues:  all_issues.append((i, i.confidence or SOURCE_CONFIDENCE["llm"]))

    # 按类别分组
    categories = {"security": [], "performance": [], "maintainability": []}
    for issue, conf in all_issues:
        if issue.category in categories:
            categories[issue.category].append((issue, conf))

    def category_score(issues_with_conf: list) -> int:
        # 按严重度聚合扣分 (考虑置信度)
        penalty_by_severity: dict[str, float] = {"critical": 0, "warning": 0, "info": 0}
        for i, conf in issues_with_conf:
            penalty_by_severity[i.severity] += SEVERITY_PENALTY[i.severity] * conf

        # 减去容忍度 (避免小文件过度惩罚)
        normalized_penalty = 0
        for sev, penalty in penalty_by_severity.items():
            tolerance = ISSUE_TOLERANCE_PER_100_LOC[sev] * loc_factor
            excess = max(0, penalty - tolerance)
            normalized_penalty += excess

        # 评分公式: 100 - 归一化惩罚分
        # 系数 1.0 (每超出 1 分惩罚扣 1 分)，封顶 0
        return max(0, int(base - normalized_penalty))

    sec = category_score(categories["security"])
    perf = category_score(categories["performance"])
    maint = category_score(categories["maintainability"])

    return ReviewScores(
        security=sec,
        performance=perf,
        maintainability=maint,
        overall=int(0.4 * sec + 0.3 * perf + 0.3 * maint),
    )
```

> **设计说明**:
> - **置信度加权**: LLM 的扣分权重低于规则匹配，避免因 LLM 幻觉导致误扣
> - **容忍度**: 100 行代码允许 5 个 warning 不扣分，避免小改动的 PR 因小问题被惩罚
> - **权重分配**: 安全 0.4 / 性能 0.3 / 可维护性 0.3 — 安全最重要

### 7.3 LLM Prompt 设计

```python
SYSTEM_PROMPT = """You are an expert code reviewer. Analyze the following code diff \
and provide structured feedback in JSON format.

Focus on:
1. Security vulnerabilities (injection, auth bypass, data exposure)
2. Performance issues (N+1 queries, unnecessary allocations, algorithmic complexity)
3. Maintainability (naming, complexity, missing error handling)
4. Best practices for {language}

Be concise and actionable. Only report real issues, not style preferences.
Each issue MUST include a concrete fix suggestion.

# Output Format

Return a JSON object matching this schema exactly:
{{
  "issues": [
    {{
      "line": <line_number_in_diff>,
      "severity": "critical" | "warning" | "info",
      "category": "security" | "performance" | "maintainability",
      "message": "<what's wrong>",
      "suggestion": "<how to fix it>",
      "confidence": <0.0-1.0>
    }}
  ],
  "summary": "<2-3 sentence overall assessment>",
  "score": <0-100 integer>
}}

# Few-Shot Examples

## Input
File: src/auth.py
Language: python
```diff
+ password = request.json["password"]
+ cursor.execute(f"SELECT * FROM users WHERE password = '{password}'")
```

## Output
{
  "issues": [
    {
      "line": 2,
      "severity": "critical",
      "category": "security",
      "message": "SQL injection: password concatenated into query",
      "suggestion": "Use parameterized query: cursor.execute(\"... WHERE password = %s\", (password,))",
      "confidence": 0.99
    }
  ],
  "summary": "Critical SQL injection vulnerability in authentication path.",
  "score": 25
}
"""

USER_PROMPT = """File: {file_path}
Language: {language}

```diff
{code_diff}
```

Context from surrounding code:
```{language}
{file_context}
```"""
```

**LLM 调用配置** (强制结构化输出):

```python
response = await client.chat.completions.create(
    model="gpt-4o",
    messages=[
        {"role": "system", "content": SYSTEM_PROMPT.format(language=lang)},
        {"role": "user", "content": USER_PROMPT.format(...)},
    ],
    response_format={"type": "json_object"},  # ⚠️ 强制 JSON 输出
    temperature=0.1,                          # 低温度保证一致性
    max_tokens=2000,
    seed=42,                                  # 可选: 提高可重现性
)

result = LLMReviewResult.model_validate_json(response.choices[0].message.content)
# 用 Pydantic 验证 JSON schema，不符合时 fallback 为空结果
```

### 7.4 幂等处理

```python
# Redis 幂等 Key 格式
key = f"webhook:pr:{repo_full_name}:{pr_number}:{commit_sha}"

# 处理流程
async def handle_webhook(payload: WebhookPayload) -> str:
    key = f"webhook:pr:{payload.repo_full_name}:{payload.pr_number}:{payload.commit_sha}"

    # SETNX = 仅当 key 不存在时设置 (原子操作)
    set = await redis.set(key, "processing", ex=3600, nx=True)
    if not set:
        raise HTTPException(409, "Duplicate webhook, already processing")

    # 推入 Celery 队列
    task = review_task.delay(payload.repo_full_name, payload.pr_number, payload.commit_sha)
    return task.id
```

### 7.5 速率限制

```python
# GitHub API 限制: 5000 req/hour (authenticated)
# OpenAI API 限制: 按 tier

# Redis 滑动窗口限流
async def check_rate_limit(key: str, limit: int, window: int) -> bool:
    """滑动窗口速率限制"""
    now = time.time()
    pipe = redis.pipeline()
    pipe.zremrangebyscore(key, 0, now - window)     # 移除窗口外的记录
    pipe.zadd(key, {str(now): now})                  # 添加当前请求
    pipe.zcount(key, 0, now)                         # 计数
    pipe.expire(key, window)                         # 设置过期
    _, _, count, _ = await pipe.execute()
    return count <= limit
```

---

## 8. 前端设计

### 8.1 页面结构

```
┌─────────────────────────────────────────────────────────┐
│  Logo  AI Code Review Bot     Dashboard | Settings | 👤  │
├──────────┬──────────────────────────────────────────────┤
│          │                                               │
│ Sidebar  │              Main Content                     │
│          │                                               │
│ Dashboard│  ┌──────────────┐ ┌──────────────┐           │
│ Reviews  │  │ Total Reviews│ │  Avg Score   │           │
│ Rules    │  │    1,247     │ │     82.5     │           │
│ Settings │  └──────────────┘ └──────────────┘           │
│          │  ┌──────────────┐ ┌──────────────┐           │
│          │  │ Issues Found │ │  LLM Cost    │           │
│          │  │    5,832     │ │   $45.67     │           │
│          │  └──────────────┘ └──────────────┘           │
│          │                                               │
│          │  ┌─────────────────────────────────────┐    │
│          │  │       Score Trend (Last 30 Days)      │    │
│          │  │  📈 Chart.js 折线图                   │    │
│          │  └─────────────────────────────────────┘    │
│          │                                               │
│          │  ┌─────────────────────────────────────┐    │
│          │  │       Recent Reviews                   │    │
│          │  │  PR #42  | Score: 85 | 3 warnings     │    │
│          │  │  PR #41  | Score: 92 | 1 info         │    │
│          │  │  PR #40  | Score: 67 | 2 critical     │    │
│          │  └─────────────────────────────────────┘    │
└──────────┴───────────────────────────────────────────────┘
```

### 8.2 核心页面

| 页面 | 功能 |
|------|------|
| Dashboard | 统计卡片、趋势图、最近 Reviews |
| Review History | PR Review 列表（分页、筛选、排序） |
| Review Detail | 单个 Review 的详细结果（文件树、行级评论） |
| Repository Settings | 启用/禁用 Bot、配置排除路径、Token 预算 |
| Rule Management | 自定义规则 CRUD |
| Login | GitHub OAuth 登录 |

### 8.3 技术选型

| 库 | 用途 |
|---|------|
| React 18 + TypeScript | 前端框架 |
| Vite | 构建工具 |
| Tailwind CSS | 样式 |
| shadcn/ui | 组件库 |
| TanStack Query | 数据获取/缓存 |
| Zustand | 全局状态管理 |
| Chart.js / Recharts | 图表 |
| React Router | 路由 |
| Lucide Icons | 图标 |

---

## 9. 部署方案

### 9.1 Docker Compose 全栈编排

```yaml
# docker-compose.yml
version: '3.9'

services:
  # --- 反向代理 ---
  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./docker/nginx.conf:/etc/nginx/nginx.conf
      - ./certbot/conf:/etc/letsencrypt
      - ./certbot/www:/var/www/certbot
    depends_on:
      - backend
      - frontend
    restart: always

  # --- FastAPI 后端 ---
  backend:
    build:
      context: .
      dockerfile: docker/Dockerfile.backend
    env_file: .env
    expose:
      - "8000"
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    restart: always
    deploy:
      resources:
        limits:
          cpus: '2.0'
          memory: 1G
        reservations:
          memory: 256M
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/api/v1/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  # --- Celery Worker ---
  worker:
    build:
      context: .
      dockerfile: docker/Dockerfile.backend
    command: celery -A app.tasks.celery_app worker --loglevel=info --concurrency=4
    env_file: .env
    depends_on:
      - redis
      - postgres
    restart: always
    deploy:
      resources:
        limits:
          cpus: '4.0'      # AST 分析 CPU 密集
          memory: 2G        # LLM 结果缓存 + AST 树
        reservations:
          memory: 512M

  # --- Celery Beat (定时任务) ---
  beat:
    build:
      context: .
      dockerfile: docker/Dockerfile.backend
    command: celery -A app.tasks.celery_app beat --loglevel=info
    env_file: .env
    depends_on:
      - redis
    restart: always
    deploy:
      resources:
        limits:
          memory: 256M

  # --- Flower (Celery 监控) ---
  flower:
    build:
      context: .
      dockerfile: docker/Dockerfile.backend
    command: celery -A app.tasks.celery_app flower --port=5555
    env_file: .env
    expose:
      - "5555"
    depends_on:
      - redis
    restart: always

  # --- React 前端 ---
  frontend:
    build:
      context: ./frontend
      dockerfile: ../docker/Dockerfile.frontend
    expose:
      - "3000"
    restart: always

  # --- PostgreSQL + pgvector ---
  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_DB: code_review_bot
      POSTGRES_USER: ${DB_USER}
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    # ⚠️ 生产环境通过 postgresql.conf 调优:
    #   shared_buffers = 256MB
    #   effective_cache_size = 1GB
    #   max_connections = 100
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${DB_USER}"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: always
    deploy:
      resources:
        limits:
          memory: 2G

  # --- Redis ---
  redis:
    image: redis:7.2-alpine
    # ⚠️ 分库隔离不同用途，避免互相驱逐
    # DB 0: 缓存 (review 结果, 24h TTL, LRU 驱逐)
    # DB 1: Celery broker (任务消息)
    # DB 2: Celery result backend (任务结果)
    # DB 3: 幂等/速率限制 (短 TTL)
    command: >
      redis-server
      --appendonly yes
      --maxmemory 1gb
      --maxmemory-policy allkeys-lru
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: always
    deploy:
      resources:
        limits:
          memory: 1.5G

  # --- Prometheus (指标采集) ---
  prometheus:
    image: prom/prometheus:latest
    volumes:
      - ./docker/prometheus.yml:/etc/prometheus/prometheus.yml
      - prometheus_data:/prometheus
    expose:
      - "9090"
    restart: always

  # --- Grafana (可视化) ---
  grafana:
    image: grafana/grafana:latest
    environment:
      GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_PASSWORD}
    volumes:
      - grafana_data:/var/lib/grafana
    expose:
      - "3001"
    depends_on:
      - prometheus
    restart: always

volumes:
  postgres_data:
  redis_data:
  prometheus_data:
  grafana_data:
```

### 9.2 环境变量

```bash
# .env.example

# --- 应用 ---
APP_ENV=production
APP_DEBUG=false
SECRET_KEY=<your-secret-key-min-32-chars>

# --- 数据库 ---
DATABASE_URL=postgresql+asyncpg://user:password@postgres:5432/code_review_bot
DB_USER=user
DB_PASSWORD=password

# --- Redis ---
REDIS_URL=redis://redis:6379/0

# --- Celery ---
CELERY_BROKER_URL=redis://redis:6379/1
CELERY_RESULT_BACKEND=redis://redis:6379/2

# --- GitHub App ---
GITHUB_APP_ID=<your-app-id>
GITHUB_PRIVATE_KEY_PATH=/run/secrets/github-private-key.pem
GITHUB_WEBHOOK_SECRET=<your-webhook-secret>
GITHUB_CLIENT_ID=<oauth-client-id>
GITHUB_CLIENT_SECRET=<oauth-client-secret>

# --- OpenAI ---
OPENAI_API_KEY=<your-api-key>
OPENAI_MODEL=gpt-4o
OPENAI_MODEL_LIGHT=gpt-4o-mini
OPENAI_MAX_TOKENS_PER_REVIEW=50000
OPENAI_DAILY_BUDGET_USD=10.00

# --- 监控 ---
SENTRY_DSN=<your-sentry-dsn>
PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus

# --- Grafana ---
GRAFANA_PASSWORD=<admin-password>
```

### 9.3 CI/CD (GitHub Actions)

```yaml
# .github/workflows/ci.yml
name: CI/CD Pipeline

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: pgvector/pgvector:pg16
        env:
          POSTGRES_PASSWORD: test
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
      redis:
        image: redis:7.2-alpine
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 10s

    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - uses: actions/setup-node@v4
        with:
          node-version: '20'

      - name: Install Python deps
        run: |
          pip install -r requirements.txt
          pip install pytest pytest-asyncio pytest-cov

      - name: Lint (ruff)
        run: ruff check app/

      - name: Type check (mypy)
        run: mypy app/

      - name: Run tests
        env:
          DATABASE_URL: postgresql://postgres:test@localhost:5432/test
          REDIS_URL: redis://localhost:6379/0
        run: pytest --cov=app --cov-report=xml

      - name: Frontend lint & test
        working-directory: frontend
        run: |
          npm ci
          npm run lint
          npm run test
          npm run build

  deploy:
    needs: test
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Deploy to server
        uses: appleboy/ssh-action@v1.0.0
        with:
          host: ${{ secrets.SERVER_HOST }}
          username: ${{ secrets.SERVER_USER }}
          key: ${{ secrets.SSH_PRIVATE_KEY }}
          script: |
            cd /opt/ai-code-review-bot
            git pull origin main
            docker-compose build
            docker-compose up -d
            docker-compose exec backend alembic upgrade head
```

---

## 10. 监控与运维

### 10.1 监控指标

| 指标 | 来源 | 告警阈值 |
|------|------|---------|
| Webhook 响应时间 | FastAPI middleware | p99 > 500ms |
| Review 处理时间 | Celery task | p95 > 30s |
| Review 队列长度 | Celery events | > 50 |
| LLM API 错误率 | httpx interceptor | > 5% |
| LLM 日花费 | llm_usage table | > $10 |
| GitHub API 限流 | X-RateLimit headers | < 100 remaining |
| PostgreSQL 连接数 | pg_stat_activity | > 80 |
| Redis 内存使用 | INFO memory | > 80% |
| Worker 存活 | Celery heartbeat | 离线 > 1min |

### 10.2 日志策略

```python
# 结构化 JSON 日志 (structlog)
import structlog

logger = structlog.get_logger()

logger.info("review_started",
    repo="owner/repo",
    pr_number=42,
    commit_sha="abc123",
    files_changed=8,
)

logger.info("review_completed",
    repo="owner/repo",
    pr_number=42,
    score=85,
    issues_found=5,
    duration_ms=12340,
    llm_tokens=4500,
    llm_cost_usd=0.0225,
)
```

### 10.3 告警通知

- **Sentry**: 异常和错误自动捕获
- **Email**: 关键告警 (LLM 预算超限、服务宕机)
- **Slack/DingTalk**: 日常运维通知 (可选)

---

## 11. 测试策略

### 11.1 测试分层

```
                    ┌─────────────────┐
                    │   E2E Tests     │  10%  ← 关键流程全链路
                    │   (Playwright)  │
                    ├─────────────────┤
                    │ Integration Tests│  25%  ← API + DB + Redis
                    │   (pytest)       │
                    ├─────────────────┤
                    │   Unit Tests     │  65%  ← 业务逻辑
                    │   (pytest)       │
                    └─────────────────┘
```

### 11.2 测试覆盖

| 模块 | 测试重点 | 工具 |
|------|---------|------|
| Webhook Handler | 签名验证、幂等、payload 解析 | pytest + httpx TestClient |
| AST Analyzer | 多语言解析、复杂度检测 | pytest + fixture |
| Rule Engine | 规则匹配、误报率 | pytest + parametrize |
| LLM Analyzer | Mock OpenAI 响应、缓存命中 | pytest + respx |
| Scoring | 评分边界、权重正确 | pytest + parametrize |
| GitHub Client | API 调用、错误处理 | pytest + respx |
| Cache Service | 读写、过期、并发 | pytest + fakeredis |
| Celery Tasks | 任务执行、重试、超时 | pytest + celery_worker |

### 11.3 测试样例

```python
# tests/unit/test_webhook_handler.py
class TestWebhookHandler:
    async def test_valid_webhook_accepted(self, client, valid_webhook_payload, valid_signature):
        response = await client.post(
            "/api/v1/webhook",
            json=valid_webhook_payload,
            headers={"X-Hub-Signature-256": valid_signature, "X-GitHub-Event": "pull_request"},
        )
        assert response.status_code == 202

    async def test_invalid_signature_rejected(self, client, valid_webhook_payload):
        response = await client.post(
            "/api/v1/webhook",
            json=valid_webhook_payload,
            headers={"X-Hub-Signature-256": "sha256=invalid", "X-GitHub-Event": "pull_request"},
        )
        assert response.status_code == 403

    async def test_duplicate_webhook_rejected(self, client, valid_webhook_payload, valid_signature, redis):
        # 第一次: 202
        # 第二次 (相同 commit_sha): 409
        ...

# tests/unit/test_rule_engine.py
@pytest.mark.parametrize("code,expected_violations", [
    ("password = 'hardcoded'", 1),  # SEC001: hardcoded secret
    ("eval(user_input)", 1),         # SEC002: unsafe eval
    ("SELECT * FROM users", 0),      # 无违规
])
def test_security_rules(code, expected_violations, rule_engine):
    violations = rule_engine.check(code, "python", SECURITY_RULES)
    assert len(violations) == expected_violations
```

---

## 12. 开发计划

### Week 1: 基础架构 + 核心流水线

| 天 | 任务 | 产出 |
|----|------|------|
| Day 1 | 项目搭建: 目录结构、Docker Compose、FastAPI 骨架 | `docker-compose up` 可运行空壳 |
| Day 2 | GitHub App 注册 + Webhook 签名验证 + 幂等处理 | Webhook 能接收并验证 |
| Day 3 | GitHub API 客户端封装 (PR diff 获取、评论发布) | 可读取 PR diff |
| Day 4 | AST 分析器 (tree-sitter 集成、复杂度检测) | 对 Python 代码生成 AST 报告 |
| Day 5 | 规则引擎 (安全/性能/风格规则定义、匹配逻辑) | 规则检查可用 |
| Day 6 | LLM 分析器 (OpenAI 集成、prompt 设计、缓存) | LLM 可生成结构化建议 |
| Day 7 | 结果聚合 + 评分算法 + PR 评论格式化 | 完整 Review 流水线 |

### Week 2: 数据持久化 + Dashboard

| 天 | 任务 | 产出 |
|----|------|------|
| Day 8 | 数据库设计 + SQLAlchemy 模型 + Alembic 迁移 | 数据库 schema 就绪 |
| Day 9 | Review Service + Cache Service + 完整 CRUD | 数据正确持久化 |
| Day 10 | Dashboard REST API (统计、列表、详情) | API 端就绪 |
| Day 11 | React 项目搭建 + 路由 + 认证 | 前端骨架 |
| Day 12 | Dashboard 页面 (统计卡片、图表) | 数据可视化 |
| Day 13 | Review 列表 + 详情页 (代码差分、行级评论) | 前端核心页面 |
| Day 14 | 仓库设置 + 规则管理页面 | 前端管理功能 |

### Week 3: 企业级特性 + 上线

| 天 | 任务 | 产出 |
|----|------|------|
| Day 15 | pgvector 集成 (相似代码问题搜索) | 向量检索可用 |
| Day 16 | Token 预算控制 + 速率限制 + 错误恢复 | 生产级健壮性 |
| Day 17 | Prometheus 指标 + Grafana Dashboard + Sentry | 监控就绪 |
| Day 18 | GitHub Actions CI/CD + 自动部署 | push to main = deploy |
| Day 19 | 测试补全 (单元/集成/E2E) + 文档 | 覆盖率 > 80% |
| Day 20 | README + 架构文档 + 演示 GIF | 项目可展示 |

---

## 13. 风险评估与应对

| 风险 | 影响 | 概率 | 应对方案 |
|------|------|------|---------|
| OpenAI API 费用超预期 | 高 | 中 | 每日预算上限 + Redis 缓存 + gpt-4o-mini 分级使用 |
| GitHub API 限流 | 中 | 中 | 请求合并 + 缓存 diff + 指数退避重试 |
| Webhook 重复投递 | 低 | 高 | Redis 幂等 (SETNX) + commit_sha 去重 |
| LLM 幻觉/误报 | 中 | 高 | 规则引擎兜底 + 用户反馈机制 + 置信度过滤 |
| 大 PR 慢 (100+ 文件) | 中 | 中 | 并行处理 + 超时控制 + 增量 Review |
| 数据库性能 | 中 | 低 | 索引优化 + 分页 + 连接池 + 读写分离(未来) |

---

## 14. 面试亮点

### 14.1 技术深度故事线

> **面试官**: "介绍一下这个项目的技术架构。"

**回答框架:**

1. **入口层**: "用 FastAPI 做网关，异步处理 Webhook。第一件事是验证 GitHub 的 HMAC-SHA256 签名——这保证了请求确实来自 GitHub，不是伪造的。"

2. **异步处理**: "Review 是 CPU+IO 密集型操作，Webhook 需要快速返回 202。所以我用 Celery + Redis 做异步队列，Worker 水平扩展。"

3. **分析流水线**: "三个并行分析器——AST 分析用 tree-sitter 做结构检查，规则引擎做已知模式匹配，LLM 做深度理解。三者互补: AST 快但浅，LLM 深但贵，规则准但覆盖窄。"

4. **成本控制**: "LLM 调用有三个优化: (1) 只发 diff 不发整个文件 (2) Redis 缓存避免重复分析 (3) 简单文件用 gpt-4o-mini，复杂文件才用 gpt-4o。整体成本降了 60%。"

5. **可靠性**: "幂等处理用了 Redis SETNX，Webhook 重复投递不会导致重复 Review。GitHub API 有限流和重试。LLM 有每日预算熔断。"

6. **可观测性**: "Prometheus + Grafana 监控 Review 耗时、LLM 花费、队列长度。Sentry 捕获异常。结构化日志方便排查。"

### 14.2 可量化的简历描述

```
AI Code Review Bot (GitHub App)                      2025.06
• 构建 AI 驱动的 GitHub App，自动审查 Pull Request，覆盖安全/性能/可维护性
• 技术栈: FastAPI + Celery + PostgreSQL/pgvector + Redis + React + Docker
• 设计三阶段分析流水线 (AST + 规则引擎 + LLM)，平均 Review 时间 < 15 秒
• 通过 Redis 缓存 + 分级 LLM 策略，将 API 成本降低 60%
• 实现幂等 Webhook 处理 (HMAC 验证 + Redis SETNX)，保障 99.9% 可靠性
• 集成 Prometheus + Grafana 监控，实现 LLM 预算熔断和自动告警
• GitHub: github.com/yourname/ai-code-review-bot
```

---

## 15. 安全加固

### 15.1 认证与会话管理

- **JWT 存储**: 使用 `HttpOnly + Secure + SameSite=Strict` Cookie，**不使用** localStorage (避免 XSS 窃取)
- **JWT 过期**: 短期 access token (15 分钟) + 长期 refresh token (7 天，一次性轮换)
- **密码**: 不存储明文，使用 `passlib[bcrypt]` (cost factor 12)
- **登出**: 服务端吊销 refresh token，清除 cookie

```python
# 设置 JWT Cookie
response.set_cookie(
    key="access_token",
    value=token,
    httponly=True,      # 防止 JS 读取
    secure=True,        # 仅 HTTPS
    samesite="strict",  # 防 CSRF
    max_age=900,        # 15 分钟
)
```

### 15.2 CSRF 防护

虽然使用 SameSite=Strict cookie 可显著降低 CSRF 风险，仍增加防御层:

- **Webhook 接口**: 不依赖 Cookie，使用 HMAC 签名验证 (无 CSRF 风险)
- **Dashboard API**: 对所有写接口 (POST/PUT/PATCH/DELETE) 要求 `X-CSRF-Token` 请求头
- **双提交 Cookie**: 服务端在登录时下发 `csrf_token` cookie，前端读取后放在请求头

### 15.3 CORS 配置

```python
# 仅允许 Dashboard 前端域
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://dashboard.yourdomain.com",
        "http://localhost:3000",  # dev
    ],
    allow_credentials=True,       # cookie 需要此选项
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-CSRF-Token"],
    expose_headers=["X-RateLimit-Remaining", "X-RateLimit-Reset"],
)
```

### 15.4 GitHub Webhook IP 白名单

```python
# 在 Nginx 或 FastAPI middleware 层限制 /webhook 仅接受 GitHub IP
# 参考: https://api.github.com/meta (hooks 字段)
GITHUB_HOOK_IPS = [
    "140.82.112.0/20",
    "185.199.108.0/22",
    "192.30.252.0/22",
    "143.55.64.0/20",
    # ...完整列表从 GitHub API 动态拉取并定期更新
]
```

### 15.5 输入验证 (Pydantic)

所有 API 入参通过 **Pydantic v2** 模型校验，不信任任何外部输入:

```python
from pydantic import BaseModel, Field, HttpUrl

class CreateRuleRequest(BaseModel):
    rule_id: str = Field(..., pattern=r"^[A-Z]{3}\d{3}$")  # e.g., SEC001
    category: Literal["security", "performance", "style", "best_practices"]
    severity: Literal["critical", "warning", "info"] = "warning"
    name: str = Field(..., min_length=1, max_length=200)
    pattern: str = Field(..., min_length=1)
    languages: list[str] = Field(..., min_length=1)

    model_config = {"extra": "forbid"}  # 拒绝未声明的字段
```

### 15.6 其他安全措施

| 措施 | 说明 |
|------|------|
| HTTPS 强制 | Nginx 配置 HSTS + 仅 443 端口 |
| 安全头 | `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin` |
| 依赖扫描 | GitHub Dependabot 自动创建 PR |
| 密钥管理 | `.env` 不入 Git，生产环境使用 Docker Secrets 或 Vault |
| 日志脱敏 | 不记录 JWT、webhook_secret、密码、PR diff 内容 |
| SQL 参数化 | 全部使用 SQLAlchemy ORM 或参数化查询，禁止字符串拼接 |

---

## 16. 运维与扩展设计

### 16.1 OpenAPI / Swagger

FastAPI 自动生成 OpenAPI 3.1 规范 (`/api/v1/docs` Swagger UI, `/api/v1/openapi.json` raw spec):
- 部署后可直接访问交互式文档
- CI 中导出 `openapi.json` 并检查是否有 breaking changes (`openapi-diff`)

### 16.2 实时状态推送 (SSE)

Review 状态变更通过 **Server-Sent Events** 推送到 Dashboard，无需轮询:

```
GET /api/v1/reviews/{id}/events
Accept: text/event-stream

# 服务端推送
event: status_changed
data: {"status": "processing", "progress": 0.3}

event: status_changed
data: {"status": "completed", "overall_score": 85}
```

### 16.3 大 PR 处理策略

100+ 文件的 PR 采用分级策略:

| 文件数 | 策略 |
|--------|------|
| 1-20 | 全量 Review (AST + 规则 + LLM) |
| 21-100 | 全量 AST + 规则；LLM 仅分析 Top-10 最可能有问题文件 (基于规则结果 + 历史热点) |
| 100+ | 仅 AST + 规则；LLM 仅分析 Top-5；PR 评论提示 "文件过多，仅审查关键变更" |

```python
async def select_files_for_llm(files: list[FileDiff], rule_results: dict) -> list[FileDiff]:
    """根据规则命中数排序，选择高风险文件送给 LLM"""
    scored = sorted(files, key=lambda f: -rule_results.get(f.path, 0))
    return scored[:10]
```

### 16.4 多语言扩展策略

tree-sitter 支持增量添加语言:

```python
LANGUAGE_PARSERS = {
    "python": tree_sitter_python.language(),
    "javascript": tree_sitter_javascript.language(),
    "typescript": tree_sitter_typescript.language_typescript(),
    # 后续添加:
    # "go": tree_sitter_go.language(),
    # "rust": tree_sitter_rust.language(),
    # "java": tree_sitter_java.language(),
}
```

规则引擎的 `languages` 字段控制每条规则适用的语言。新语言 = 注册 parser + 翻译/新建规则集。

### 16.5 GitHub App 安装流程

```
用户在 GitHub Marketplace/App 页面点击 Install
  │
  ├─→ GitHub 发送 installation webhook 到 /api/v1/webhook
  │     action: "created" | "added"
  │
  ├─→ 后端创建/更新 repositories 记录 (installation_id)
  │
  ├─→ 前端 Dashboard 通过 OAuth 拿到用户身份，关联仓库
  │
  └─→ 后续 PR 自动触发 Review
```

卸载 (action: "deleted") 时**软删除** (`is_active=false`)，保留历史 Review 数据。

### 16.6 数据保留与隐私 (GDPR)

| 数据 | 保留期 | 清理方式 |
|------|--------|---------|
| Review 记录 + 评论 | 90 天 | Celery beat 每日清理任务 |
| LLM Usage 日志 | 180 天 | 同上 |
| 代码片段 (code_embeddings) | 30 天 | 同上 |
| Webhook 原始 payload | 不存储 | — |
| 用户数据 | 账户删除时擦除 | `DELETE` + 审计日志 |

用户可通过 Dashboard 主动删除仓库的 Review 历史。PR diff 不持久化，仅用于内存分析后丢弃。

### 16.7 备份与灾难恢复

| 组件 | 策略 | RPO / RTO |
|------|------|-----------|
| PostgreSQL | 每日 `pg_dump` → S3 + WAL 流式归档 (pgBackRest) | RPO 5min / RTO 30min |
| Redis | AOF 持久化 + 每 6h RDB 快照 | RPO 1h / RTO 10min (可接受少量缓存丢失) |
| 配置 | `.env` 存储在 Vault，不入 Git | N/A |
| 镜像 | Docker 镜像推到 GHCR | N/A |

**灾难恢复演练**: 每月从备份恢复到 staging 环境，验证数据完整性。

---

## 附录

### A. 参考项目

- [Danger.js](https://danger.systems/js/) — Ruby/JS 的规则引擎 Review
- [Reviewdog](https://github.com/reviewdog/reviewdog) — Go 的 Linter 集成
- [CodeRabbit](https://coderabbit.ai) — 商业 AI Code Review (参考产品形态)

### B. GitHub App 注册步骤

1. 访问 https://github.com/settings/apps/new
2.填写 App 名称: "AI Code Review Bot"
3. Webhook URL: `https://yourdomain.com/api/v1/webhook`
4. 权限:
   - Pull requests: Read & Write
   - Contents: Read
   - Checks: Write
   - Metadata: Read
5. 订阅事件: `pull_request`
6. 生成 Private Key (.pem 文件)
7. 记录 App ID, Client ID, Client Secret

### C. 本地开发快速启动

```bash
# 1. 克隆项目
git clone https://github.com/yourname/ai-code-review-bot.git
cd ai-code-review-bot

# 2. Python 虚拟环境
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

# 3. 前端安装
cd frontend && npm install && cd ..

# 4. 环境变量
cp .env.example .env
# 编辑 .env 填入 API keys

# 5. Docker 启动全栈
docker-compose up -d

# 6. 数据库迁移
docker-compose exec backend alembic upgrade head

# 7. 访问
# Dashboard: http://localhost
# API Docs:  http://localhost/api/v1/docs
# Flower:    http://localhost:5555
# Grafana:   http://localhost:3001
```

---

> **文档版本**: v1.1
> **最后更新**: 2025-06-04
> **下一步**: 确认文档 → 搭建项目骨架 → 开始 Day 1 开发
