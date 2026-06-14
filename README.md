# AI Code Review Bot

> **基于 AST 分析、规则引擎和 LLM (GPT-4o) 的自动化 Pull Request 审查工具。**
>
> 目标：减少 40% 手动审查时间，安全检测率 >80%，审查速度 <10秒/文件。

[![CI](https://github.com/your-org/ai-code-review-bot/actions/workflows/ci.yml/badge.svg)](https://github.com/your-org/ai-code-review-bot/actions/workflows/ci.yml)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688.svg)](https://fastapi.tiangolo.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## 功能特性

- **多层分析**：AST (tree-sitter) + 规则引擎（24 条内置规则）+ LLM (GPT-4o)
- **实时 PR 审查**：通过 GitHub Webhook 触发，结果以评论 + 内联注释形式发布
- **安全优先**：SQL 注入、XSS、硬编码密钥、弱加密等 6+ 种安全检查
- **性能与风格**：N+1 查询、复杂度、嵌套深度、TODO/FIXME 追踪
- **多语言支持**：Python、JavaScript、TypeScript、Java、Go、Rust
- **智能评分**：多维度（安全/性能/可维护性）置信度加权聚合
- **预算控制**：每日 LLM 成本限制 + 单 PR Token 上限
- **仪表盘**：React 前端，包含审查历史、趋势和仓库管理
- **企业级就绪**：pgvector 语义搜索、Prometheus 监控、Sentry 错误追踪、CI/CD

---

## 系统架构

```
GitHub PR → Nginx (SSL) → FastAPI → Celery Workers → Pipeline → GitHub API
                                           │
                              ┌────────────┼────────────┐
                              ▼            ▼            ▼
                          AST         规则引擎       LLM
                       (tree-sitter)  (24 条规则)  (GPT-4o)
                              └────────────┬────────────┘
                                           ▼
                                   结果聚合器
                                   (去重 + 评分)
                                           │
                              ┌────────────┴────────────┐
                              ▼                         ▼
                        PostgreSQL                 Redis 缓存
                      (7 张表 +                   (4 个 DB：
                       pgvector)                   broker/cache/
                                                   idempotency/
                                                   budget)
```

**技术栈**：
| 层级 | 技术 |
|------|------|
| 后端 | FastAPI 0.115+, Celery 5.4+, SQLAlchemy 2.0 async |
| 数据库 | PostgreSQL 16 + pgvector 0.7+ |
| 缓存/队列 | Redis 7.2+ (4 个逻辑数据库) |
| AST | tree-sitter 0.23+ (Python, JS, TS, Java, Go, Rust) |
| LLM | OpenAI GPT-4o (结构化 JSON 输出, Redis 缓存) |
| 前端 | React 18, TypeScript 5, Vite, Tailwind, shadcn/ui |
| 监控 | Prometheus + Grafana + Sentry |
| 基础设施 | Docker Compose (10 个服务), Nginx SSL 反向代理 |

---

## 快速开始

### 前置条件

- Docker & Docker Compose v2+
- GitHub App（用于 webhook 集成）
- OpenAI API 密钥

### 1. 克隆与配置

```bash
git clone https://github.com/your-org/ai-code-review-bot.git
cd ai-code-review-bot
cp .env.example .env
```

编辑 `.env` 文件，填入你的凭证：

```env
APP_SECRET=your-32-char-secret-key-here
GITHUB_APP_ID=123456
GITHUB_PRIVATE_KEY_PATH=/path/to/private-key.pem
GITHUB_WEBHOOK_SECRET=your_webhook_secret
OPENAI_API_KEY=sk-your-openai-key
SENTRY_DSN=https://xxx@sentry.io/xxx  # 可选
```

### 2. 使用 Docker 启动

```bash
# 构建并启动所有服务
docker compose up -d --build

# 运行数据库迁移
docker compose exec backend alembic upgrade head

# 检查健康状态
curl http://localhost/health
```

**服务端口**：
| 服务 | 端口 | URL |
|------|------|-----|
| 前端 | 80 | http://localhost |
| API | 80 (通过 Nginx) | http://localhost/api/v1 |
| API 文档 | 80 (仅调试模式) | http://localhost/docs |
| Flower (Celery) | 5555 | http://localhost:5555 |
| Grafana | 3001 | http://localhost:3001 |
| Prometheus | 9090 | http://localhost:9090 |

### 3. GitHub App 配置

1. 进入 **GitHub Settings → Developer settings → GitHub Apps → New GitHub App**
2. 设置 **Webhook URL** 为 `https://your-domain.com/api/v1/webhook`
3. 设置 **Webhook secret**（与 `.env` 中的 `GITHUB_WEBHOOK_SECRET` 相同）
4. 订阅 **Pull request** 事件
5. 授权权限：`contents:read`, `pull_requests:write`, `statuses:write`, `checks:write`
6. 生成私钥，保存为 `.keys/github-app.pem`

---

## 开发指南

### 本地开发（不使用 Docker）

```bash
# 后端
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 启动 PostgreSQL + Redis（或使用 docker compose up postgres redis）

# 运行迁移
alembic upgrade head

# 启动 API（热重载）
uvicorn app.main:app --reload --port 8000

# 启动 Celery worker（单独终端）
celery -A app.tasks.celery_app worker -l info

# 启动 Celery beat（单独终端）
celery -A app.tasks.celery_app beat -l info
```

### 前端开发

```bash
cd frontend
npm install
npm run dev  # Vite 开发服务器，地址 localhost:5173
```

### 测试

```bash
# 运行所有测试
pytest

# 带覆盖率
pytest --cov=app --cov-report=html

# 仅集成测试
pytest tests/integration/

# 前端测试
cd frontend && npm test
```

### 代码质量

```bash
# 代码检查
ruff check app/
ruff format --check app/

# 类型检查
mypy app/

# 预提交钩子（运行所有检查）
pre-commit run --all-files
```

---

## API 概览

所有端点位于 `/api/v1` 下，响应使用 `{data, meta}` 包装格式。

| 方法 | 端点 | 描述 | 认证 |
|------|------|------|------|
| POST | `/webhook` | GitHub webhook 接收器 | HMAC |
| GET | `/health` | 存活探针 | 无 |
| GET | `/reviews` | 审查列表（分页） | JWT |
| GET | `/reviews/{id}` | 审查详情及评论 | JWT |
| POST | `/reviews/{id}/stream` | SSE 实时状态 | JWT |
| POST | `/reviews` | 手动触发审查 | JWT |
| GET | `/repositories` | 活跃仓库列表 | JWT |
| PUT | `/repositories/{id}/settings` | 更新仓库配置 | JWT |
| GET | `/rules` | 所有规则列表 | JWT |
| POST | `/rules` | 创建自定义规则 | JWT |
| GET | `/stats/overview` | 仪表盘概览统计 | JWT |
| GET | `/stats/trends` | 审查趋势数据 | JWT |
| POST | `/auth/github` | GitHub OAuth 登录 | 无 |
| GET | `/auth/me` | 当前用户信息 | JWT |

完整交互式文档位于 `/docs`（当 `DEBUG=True` 时可用）。

---

## 评分算法

```
总体评分 = 0.4 × 安全 + 0.3 × 性能 + 0.3 × 可维护性
```

**来源置信度权重**：规则=1.0, AST=0.95, LLM=0.75

**严重程度扣分**：严重=10分, 警告=5分, 信息=1分（每条问题，按置信度加权）

**LOC 容忍度**：基础评分在每 100 行代码容忍阈值后按扣分比例降低。

评分范围限制在 [0, 100]。

---

## 项目结构

```
ai-code-review-bot/
├── app/
│   ├── api/v1/           # REST 端点 (webhook, reviews, repos, rules, stats, auth, sse)
│   ├── core/             # 配置、日志、安全、数据库、Redis、审查引擎、指标
│   ├── analyzers/        # AST、规则引擎、LLM、结果聚合器
│   ├── models/           # SQLAlchemy 模型（7 张表）
│   ├── schemas/          # Pydantic v2 API schemas
│   ├── services/         # 业务逻辑 (GitHub, reviews, repos, rules, stats, auth, budget, embedding)
│   ├── tasks/            # Celery 任务
│   └── utils/
├── frontend/             # React 应用 (Vite + TypeScript + Tailwind + shadcn/ui)
│   └── src/
│       ├── components/   # UI 组件 + 布局
│       ├── pages/        # 仪表盘、审查、设置、规则、登录
│       ├── store/        # Zustand 状态管理 (auth, theme)
│       └── lib/          # API 客户端、工具函数
├── alembic/              # 数据库迁移
├── docker/               # Nginx、Prometheus、Grafana 配置
├── tests/                # 单元 + 集成测试
├── .github/workflows/    # CI/CD（测试、构建、安全、部署）
├── docker-compose.yml    # 10 服务堆栈
├── requirements.txt      # Python 依赖（固定版本）
└── DESIGN.md             # 完整技术规格
```

---

## 监控

- **Prometheus**：`/metrics` 端点的指标（webhook 延迟、审查耗时、LLM token/成本、队列深度）
- **Grafana**：预配置仪表盘，地址 `http://localhost:3001`
- **Sentry**：错误追踪 + 性能监控（通过 `SENTRY_DSN` 配置）
- **Flower**：Celery worker 监控，地址 `http://localhost:5555`
- **Structlog**：所有服务的 JSON 结构化日志

---

## 安全措施

- HMAC-SHA256 webhook 签名验证（恒定时间比较）
- Redis SETNX 幂等性防止重复 webhook
- JWT HttpOnly + Secure + SameSite=Strict cookies（15分钟访问 / 7天刷新）
- Fernet 加密存储 webhook 密钥（BYTEA）
- CORS 白名单，GitHub IP 白名单就绪
- HSTS，通过 Nginx 设置安全头
- 参数化 SQL（SQLAlchemy ORM，无原生查询）
- Sentry 事件中的 PII/密钥脱敏
- Pydantic v2 所有输入 schema 使用 `extra=forbid`
- Dependabot 自动依赖更新 + Trivy 容器扫描

---

## 许可证

MIT — 详情见 [LICENSE](LICENSE)。
