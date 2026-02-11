# OpenShare 命令清单

本文档汇总当前项目里常用/自定义的命令入口与用法，便于日常开发、排障与运维。

## 1) 统一执行约定

- 安装依赖：`uv sync`
- 推荐通过 `just` 执行项目预设命令
- 执行 Django 命令可用：
  - `just manage <django_command> [options]`
  - 或 `uv run manage.py <django_command> [options]`

---

## 2) Just 命令（项目级快捷入口）

> 以下命令定义在 `justfile`。

### `just run`
- 用途：启动本地开发服务器（`runserver_plus`）
- 等价：`uv run manage.py runserver_plus`
- 示例：
  - `just run`

### `just sh`
- 用途：进入增强版 Django Shell（`shell_plus`）
- 等价：`uv run manage.py shell_plus`
- 示例：
  - `just sh`

### `just worker`
- 用途：启动后台任务 Worker（`db_worker`）
- 等价：`uv run manage.py db_worker`
- 示例：
  - `just worker`

### `just manage *args`
- 用途：透传执行任意 Django 管理命令
- 等价：`uv run manage.py {{args}}`
- 示例：
  - `just manage migrate`
  - `just manage showmigrations`
  - `just manage test points.tests.test_commands`

### `just fmt`
- 用途：代码质量与格式化（Ruff + djlint）
- 依次执行：
  - `uvx ruff check --fix`
  - `uvx ruff format`
  - `uv run -m pre_commit run djlint-django --all-files`
- 示例：
  - `just fmt`

### `just migrate`
- 用途：生成并执行数据库迁移
- 依次执行：
  - `uv run manage.py makemigrations`
  - `uv run manage.py migrate`
- 示例：
  - `just migrate`

### `just test`
- 用途：以覆盖率模式并行运行测试（与 CI 对齐）
- 依次执行：
  - `uv run coverage erase`
  - `DJANGO_LOG_LEVEL=ERROR uv run coverage run --concurrency=multiprocessing --parallel-mode manage.py test --parallel --timing --durations 10`
  - `uv run coverage combine`
  - `uv run coverage report`
  - `uv run coverage report --skip-covered --skip-empty`
- 示例：
  - `just test`

### `just docker-build IMAGE='fullsite'`
- 用途：构建 Docker 镜像
- 等价：`docker build --tag {{IMAGE}} .`
- 示例：
  - `just docker-build`
  - `just docker-build IMAGE=openshare-dev`

### `just docker-test IMAGE='fullsite'`
- 用途：在容器中运行测试
- 说明：依赖 `docker-build`
- 等价：`docker run --rm --env-file .env.example {{IMAGE}} python manage.py test --parallel`
- 示例：
  - `just docker-test`
  - `just docker-test IMAGE=openshare-dev`

---

## 3) 项目自定义 Django 管理命令

> 以下为代码仓库内定义的自定义命令（非 Django 内置）。

### `grant_points`
- 用途：给用户或组织发放积分
- 命令：
  - `uv run manage.py grant_points (--user <username> | --user-id <id> | --org <slug> | --org-id <id>) --amount <num> --type <cash|gift> --reason <text> [--tag <slug>] [--expires YYYY-MM-DD] [--reference-id <id>]`
- 常用示例：
  - `uv run manage.py grant_points --user alice --amount 100 --type cash --reason "活动奖励"`
  - `uv run manage.py grant_points --org openshare --amount 500 --type gift --reason "社区计划" --tag docs --expires 2026-12-31`

### `merge_accounts`
- 用途：按合并请求 UUID 执行账号合并
- 命令：
  - `uv run manage.py merge_accounts --request <request_uuid>`
- 示例：
  - `uv run manage.py merge_accounts --request 8a5f66b1-0d1a-4ef9-b4b5-2f36f6f5f2d4`

### `setadmin`
- 用途：将已有用户提升为管理员
- 命令：
  - `uv run manage.py setadmin (--uid <id> | --username <username>)`
- 示例：
  - `uv run manage.py setadmin --uid 1`
  - `uv run manage.py setadmin --username alice`

### `rollback_pending_claims`
- 用途：回退某个用户已领取的待领取积分，并扣除对应已发放积分
- 命令：
  - `uv run manage.py rollback_pending_claims (--user <username> | --user-id <id>) [--grant-id <grant_id> ...] [--dry-run]`
- 参数说明：
  - `--grant-id`：可重复传入，仅回退指定待领取记录
  - `--dry-run`：仅预览，不执行回退
- 常用示例：
  - `uv run manage.py rollback_pending_claims --user alice`
  - `uv run manage.py rollback_pending_claims --user alice --grant-id 12 --grant-id 15`
  - `uv run manage.py rollback_pending_claims --user-id 42 --dry-run`

### `retrigger_pending_point_claims`
- 用途：手动重新触发存量用户的待领取积分发放
- 命令：
  - `uv run manage.py retrigger_pending_point_claims (--all | --user <username> | --user-id <id>) [--include-without-github] [--dry-run]`
- 参数说明：
  - `--all`：处理所有已绑定 GitHub 的用户
  - `--include-without-github`：仅可与 `--all` 一起使用，表示包含未绑定 GitHub 的用户
  - `--dry-run`：仅预览，不执行实际发放
- 常用示例：
  - `uv run manage.py retrigger_pending_point_claims --all`
  - `uv run manage.py retrigger_pending_point_claims --all --include-without-github`
  - `uv run manage.py retrigger_pending_point_claims --user alice --dry-run`

---

## 4) 查看“全部可用” Django 命令（含内置/第三方）

由于 Django 与第三方 app（如扩展包）会动态注册命令，完整清单请实时查看：

- 列出全部命令：
  - `uv run manage.py help --commands`
- 查看某个命令帮助：
  - `uv run manage.py help <command>`

例如：
- `uv run manage.py help migrate`
- `uv run manage.py help retrigger_pending_point_claims`

---

## 5) 当前 `manage.py` 命令快照（2026-02-12）

> 该清单来自 `uv run manage.py help --commands`，包含 Django 内置、第三方与项目自定义命令。  
> 具体参数请查看：`uv run manage.py help <command>`。

```
admin_generator
changepassword
check
clean_pyc
clear_cache
clearsessions
clearsocial
collectstatic
compile_pyc
compilemessages
create_command
create_jobs
create_template_tags
createcachetable
createsuperuser
db_worker
dbshell
debugsqlshell
delete_squashed_migrations
describe_form
diffsettings
drop_test_database
dumpdata
dumpscript
export_emails
find_template
findstatic
flush
generate_password
generate_secret_key
grant_points
graph_models
inspectdb
list_model_info
list_signals
loaddata
mail_debug
makemessages
makemigrations
managestate
merge_accounts
merge_model_instances
migrate
notes
optimizemigration
print_settings
print_user_for_session
prune_db_task_results
raise_test_exception
remove_stale_contenttypes
reset_db
reset_schema
retrigger_pending_point_claims
rollback_pending_claims
runjob
runjobs
runprofileserver
runscript
runserver
runserver_plus
sendtestemail
set_default_site
set_fake_emails
set_fake_passwords
setadmin
shell
shell_plus
show_permissions
show_template_tags
show_urls
showmigrations
sqlcreate
sqldiff
sqldsn
sqlflush
sqlmigrate
sqlsequencereset
squashmigrations
startapp
startproject
sync_s3
syncdata
test
testserver
unreferenced_files
update_permissions
validate_templates
```

---

## 6) 常见组合

- 初始化数据库：
  - `just migrate`
- 本地开发（双终端）：
  - 终端 1：`just run`
  - 终端 2：`just worker`
- 执行单个 Django 命令：
  - `just manage showmigrations`
- 回退前先预览：
  - `uv run manage.py rollback_pending_claims --user alice --dry-run`
- 批量补发前先预览：
  - `uv run manage.py retrigger_pending_point_claims --all --dry-run`
