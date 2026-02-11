# OpenShare

OpenShare 是一个面向开源社区的贡献激励平台，提供积分发放与回收、标签化积分池、兑换商城、用户资料与搜索、站内消息以及可选的分析能力，帮助社区透明地奖励贡献者。

## 文档导航
- `development.md`：开发环境与开发流程说明。
- `Commands.md`：项目命令手册（`just`、自定义管理命令、`manage.py` 命令快照）。
- `contribute.md`：贡献指南与 PR 协作约定。
- `.env.example`：环境变量模板（本地配置请复制为 `.env`）。

## 技术架构概览
- **后端框架**：Django 5（入口 `manage.py`），配置位于 `config/`。
- **核心域模型**：`accounts`、`homepage`、`messages`、`points`、`shop`，可选分析模块 `chdb`，共享工具在 `common`。
- **数据层**：默认 SQLite，生产使用 PostgreSQL。
- **缓存与分析**：可选 Redis 缓存与 ClickHouse 分析（`chdb`）。
- **存储与邮件**：可选 S3/兼容对象存储；邮件默认控制台输出，可配置 Mailgun。
- **静态资源**：开发期直接使用 `static/`，生产期可用 Whitenoise 或 CDN。


## 快速开始
**依赖**：Python 3.12+、`uv`、`just`。可选 Redis、ClickHouse、PostgreSQL。

```bash
# 1) 安装工具
pip install uv
brew install just   # 主要是为了方便快速执行某些特定的命令

# 2) 安装依赖
uv sync

# 3) 环境变量
cp .env.example .env
# 4) 初始化数据库
uv run manage.py migrate
uv run manage.py createsuperuser

# 5) 启动开发环境
just run            # http://127.0.0.1:8000/
just worker         # 另开终端运行后台 DB worker
```

## 常用命令
- `just run`：启动开发服务器（`runserver_plus`）。
- `just worker`：启动后台 DB worker。
- `just sh`：进入 `shell_plus`。
- `just fmt`：Ruff lint + format + djlint（提交前必跑）。
- `just test`：并行运行测试并生成覆盖率报告。
- `just manage <command>`：执行任意 Django 管理命令。
- 完整命令手册：`Commands.md`（含 `just`、自定义管理命令与 `manage.py` 命令快照）。

## 配置说明（.env）
复制 `.env.example` 到 `.env` 后，至少配置：
- `SECRET_KEY`、`DEBUG`、`ALLOWED_HOSTS`、`CSRF_TRUSTED_ORIGINS`
- 邮件：`MAILGUN_API_KEY`、`MAILGUN_SENDER_DOMAIN`（为空时本地仅控制台输出）
- 对象存储：`AWS_*`（未配置则使用本地文件系统）
- 缓存：`REDIS_URL`（未配置则回落到本地缓存）
- 社交登录：`SOCIAL_AUTH_*`（逗号分隔 scope）
- 分析：`CLICKHOUSE_*`（可选）

## 目录结构
- `config/`：Django settings、URL、ASGI/WSGI 入口
- `accounts/`：用户、资料、地址、社交登录
- `homepage/`：首页与搜索
- `points/`：积分池、流水、服务与管理命令
- `shop/`：商品、兑换与物流信息
- `messages/`：站内消息与提示
- `chdb/`：ClickHouse 集成（可选）
- `templates/`、`static/`：模板与静态资源

## 测试与质量
- 全量测试：`just test`
- 目标测试：`uv run manage.py test points.tests.test_services`
- 代码风格：`just fmt`

## Docker（可选）
- 构建镜像：`just docker-build IMAGE=fullsite`
- 容器测试：`just docker-test IMAGE=fullsite`

## 贡献
欢迎提交 Issue 和 PR。详见 `contribute.md`，更多开发细节参考 `development.md`。
