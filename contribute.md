# 贡献指南

感谢你愿意参与 OpenShare！本指南说明如何搭建环境、提交变更并保持代码质量。

## 贡献方式
- **问题反馈**：描述问题现象、期望结果、复现步骤，并附上系统/数据库/Python 版本。
- **功能建议**：请先开 Issue 讨论，以避免重复或方向偏差。
- **代码贡献**：从 fork 或分支提交 PR，保持改动聚焦。

## 本地开发环境
建议先通读 `README.md` 和 `development.md`，这里给出最短路径：

```bash
# 1) 安装依赖
pip install uv
brew install just   # 或使用你的系统包管理器
uv sync

# 2) 环境变量
cp .env.example .env

# 3) 初始化数据库
uv run manage.py migrate
uv run manage.py createsuperuser

# 4) 启动开发
just run
just worker
```

## 开发流程建议
1) 新建分支：`feature/<topic>`、`fix/<topic>`、`chore/<topic>`。
2) 按模块修改代码（避免跨域耦合），补充对应测试与文档。
3) 提交前执行：`just fmt` 与 `just test`。
4) 使用 Conventional Commits，例如：`feat: add point tag validation`。
5) 提交 PR 时附上：
   - 变更目的/背景
   - 关键改动
   - 测试说明（命令或手工步骤）
   - 数据库/迁移影响
   - UI 变更截图（如适用）

## 代码规范
- Python 3.12+，Ruff 统一格式与导入；行宽 88；双引号优先。
- Django 模板尽量少逻辑，复用模板标签/过滤器。
- 命名：函数/变量 `snake_case`，类/模型 `PascalCase`，文件 `lowercase_with_underscores`。
- 禁止提交真实密钥与 `.env`。

## 测试规范
- 使用 Django `TestCase`/`APITestCase`；测试放在各 app 的 `tests/` 目录。
- 避免修改全局状态；外部服务（邮件、S3、Mailgun、ClickHouse）应做 mock。
- 新功能/修复需覆盖关键路径，确保 `just test` 通过。

## 评审与协作
- PR 保持小而聚焦，避免混入无关改动。
- 主动说明风险与未覆盖测试。
- 及时响应 review，并根据反馈修正。

## 行为准则
保持尊重与建设性的沟通，欢迎新贡献者。
