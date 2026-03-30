# OpenShare 测试策略

本文档说明 OpenShare 当前测试体系的分层职责，以及安全测试、压测和 mutation testing 的推荐用法。目标不是把所有检查都塞进一次 `just test`，而是让每一层都在合适的成本下提供稳定反馈。

## 目标

- 尽早发现业务回归，优先在模型、表单、服务和视图级别拦截问题。
- 让 coverage 口径真实反映仓库源码范围，而不是只统计“刚好被报告看见”的文件。
- 让高价值用户路径通过 E2E 得到端到端保障，但避免 E2E 数量失控。
- 用安全回归测试守住 OWASP 基线，减少“功能没坏但安全退化了”的风险。
- 用并发压测验证关键匿名流量场景在高并发下的稳定性。
- 用 mutation testing 检查测试是否真的能识别逻辑被破坏后的行为差异。

## Coverage 口径

- 默认 coverage 范围是 repo-owned Python 源码根目录：
  - `accounts/`
  - `chdb/`
  - `common/`
  - `config/`
  - `contributions/`
  - `homepage/`
  - `messages/`
  - `points/`
  - `scripts/`
  - `shop/`
- 排除项仅限测试、迁移、`__init__.py`、`manage.py` 和 `conftest.py`。
- `admin.py`、管理命令、`config/asgi.py`、`config/wsgi.py`、脚本入口都属于 coverage denominator。
- coverage gate 不只检查 line / branch 阈值，也会检查 coverage 报告是否遗漏了任何应统计源码文件。

## 分层职责

### 1. 单元与领域测试

覆盖对象：
- models
- forms
- services
- template tags
- settings helpers
- 独立脚本与工具函数

职责：
- 验证最小业务规则
- 覆盖边界条件、异常路径、分支行为
- 作为回归的第一道防线

推荐命令：
- `uv run manage.py test points.tests.test_services`
- `uv run manage.py test config.tests.test_coverage_gate`

### 2. 视图与集成测试

覆盖对象：
- 认证与权限
- redirect 与 middleware
- cache / session / CSRF
- 多模型协作的业务流程

职责：
- 验证请求入口、权限边界、数据库状态变化
- 覆盖“单个模块没问题，但组合起来会出错”的场景
- 用固定夹具覆盖外部数据契约，例如 `chdb -> contributions -> points` 的字段形状和序列化约定

推荐命令：
- `just test`

### 3. 浏览器 E2E

覆盖对象：
- 注册、登录、找回密码
- 资料编辑
- 搜索
- 积分、提现、兑换等关键用户路径

职责：
- 验证真实页面交互、前后端连通性和关键文案可见性
- 自动捕获同源页面上的 `pageerror`、`console.error`、失败的 `xhr` / `fetch` / 文档级 5xx 响应
- 只覆盖最核心路径，不承担穷举职责

推荐命令：
- `just test`

## 安全测试策略

安全回归主要对齐 OWASP Top 10 中最容易在日常开发中回归的基线项：

- 安全响应头：HSTS、`X-Content-Type-Options`、`X-Frame-Options`、`Referrer-Policy`、`Cross-Origin-Opener-Policy`
- Cookie 加固：`Secure`、`HttpOnly`、`SameSite`
- CSRF 防护：敏感 POST 入口必须拒绝缺失 token 的请求
- Host Header 防护：未信任主机头必须被拒绝
- Open Redirect：登录后的 `next` 参数不得跳转到外部站点或 scheme-relative 目标

推荐命令：
- `just test-security`
- `uv run manage.py test config.tests.test_security_owasp`

适用时机：
- 修改认证流程
- 修改 middleware / settings
- 调整 session、cookie、反向代理或域名策略

## 负载测试策略

负载测试不进入默认 `just test`，因为它依赖一个已经运行的应用实例，并且本质上属于环境级验证。

当前内置场景：
- `anonymous-browse`
  - `/`
  - `/accounts/login/`
  - `/search/?q=open`

默认指标：
- 并发：20
- 时长：30 秒
- 错误率预算：1%
- p95 预算：750ms

推荐命令：
- `just run_plus`
- `just load-test`
- `just load-test --base-url http://127.0.0.1:8001`
- `just load-test --concurrency 50 --duration 60 --p95-ms 1000`

使用建议：
- 本地开发：用于观察改动前后的相对变化
- 预发布环境：用于验证缓存、数据库和代理链路在真实配置下的表现
- CI：不默认执行，避免引入高波动和过长运行时间

## Mutation Testing 策略

Mutation testing 的目标不是替代 coverage，而是判断“测试是否真的足够敏感”。本仓库目前采用渐进式接入，优先覆盖一组高信噪且高风险的模块：

- `accounts/views.py`
- `common/load_testing.py`
- `common/middleware.py`
- `config/settings_helpers.py`
- `points/allocation_services.py`
- `points/services.py`
- `scripts/check_coverage.py`

这样做的原因：
- 这些模块边界清晰、执行快
- 既覆盖基础设施逻辑，也覆盖账户入口与积分分配这类核心业务链路
- 适合作为当前阶段的基线集合
- 后台 admin、浏览器交互和真实外部环境烟测仍主要依赖常规测试与集成测试

推荐命令：
- `just mutmut`
- `just mutmut-results`

执行建议：
- 夜间任务或预发布前运行
- 当新增 helper / middleware / 核心服务时，优先把它们纳入这组模块
- 如果 mutation 结果长期稳定，再逐步扩展到更多后台与业务代码

## 变更时如何选择测试

如果你修改的是：

- services / models / forms
  - 先跑目标测试，再跑 `just test`
- 登录、权限、域名、session、cookie、middleware
  - 先跑 `just test-security`，再跑 `just test`
- 首页、搜索、缓存、匿名访问链路
  - 跑 `just load-test` 看高并发下是否退化
- helper、middleware、脚本类逻辑
  - 除常规测试外，再跑 `just mutmut`

## 维护原则

- 新功能优先补单元或集成测试，不要默认增加 E2E。
- E2E 只保留高价值主路径，避免把细枝末节堆到浏览器层。
- 外部数据源默认用确定性的契约夹具守住接口形状；真实 ClickHouse 烟测应作为单独环境级检查，而不是默认 CI 前提。
- 安全测试优先验证“禁止发生什么”，例如禁止外部跳转、禁止缺失 CSRF、禁止未信任 Host。
- 压测和 mutation testing 都要控制范围，追求长期可执行，而不是一次性堆满工具。
