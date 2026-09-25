# 开发与诊断手册

## 已验证的本地基线

截至 2026-09-25，当前实现已在 Python 3.14.4 上成功解析依赖；精确版本见 uv.lock。后端以单用户本地服务为目标，默认数据库路径为仓库根 `.data/kairos.sqlite3`。

## 安装与启动

```sh
cd 后端
uv sync --locked --dev
uv run uvicorn kairos.main:app --host 127.0.0.1 --port 8000
```

首次使用事件 API 时，在另一终端执行 `uv run python scripts/init_db.py` 初始化数据库。依赖尚未同步时，可在后端本地虚拟环境中安装 uv：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install uv
.venv/bin/uv sync --dev
```

服务默认只绑定本机回环地址。健康检查 `GET http://127.0.0.1:8000/health` 不访问数据库，也不需要 AI 凭据。首次使用事件读取前，在后端目录执行 `uv run python scripts/init_db.py` 显式创建仓库根 `.data/kairos.sqlite3`；调用 API 或导入应用不会自动创建数据库。

## 当前能力

提供健康接口、事件状态查询、重复系列与单次例外，自然语言接口 `POST /api/v1/drafts`，后续澄清 `POST /api/v1/drafts/{id}/clarifications`，以及确认 `POST /api/v1/drafts/{id}/commit`。规划预览接口 `POST /api/v1/planning/preview` 也可单独使用。草稿保存原文、固定 reference_now 和 30 分钟有效期；正式事件仅在确认提交时写入。导入 app 不创建数据库或目录。未初始化数据库时事件接口返回 503 DATABASE_NOT_INITIALIZED。

## 配置约定

- `KAIROS_DB_PATH`：数据库文件路径，默认仓库根 `.data/kairos.sqlite3`。
- `KAIROS_AI_PROVIDER=openai_compatible`、`KAIROS_AI_MODEL`、`KAIROS_AI_API_KEY`、`KAIROS_AI_BASE_URL`：启用 OpenAI 兼容预览；模型名需填服务实际支持的 ID。当前服务模型 ID 尚未确认。
- 从启动服务的 shell 环境导出以上变量；不要把密钥写入仓库、命令记录或日志。`.env` 已加入 Git 忽略规则。
- 查询服务支持的模型时，在已设置 `KAIROS_AI_BASE_URL` 和 `KAIROS_AI_API_KEY` 的同一终端执行 `uv run python scripts/list_models.py`。脚本只打印模型 ID，认证错误不会打印响应正文。
- 未配置模型时，规划预览返回 503；事件读取和 `/health` 不依赖模型服务。
- 在线模型发现需要服务认证。当前未运行真实请求；离线测试使用假响应。

测试使用临时文件，绝不写入默认数据库路径。

## 当前验证命令

在后端目录执行：

```sh
uv sync --locked --dev
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run python scripts/check_docs.py
```

当前 schema 由 migration 001–003 初始化，重复事件、单次例外与自然语言草稿均使用版本迁移。没有公网部署流程。
