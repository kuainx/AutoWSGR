# Agent Guidelines

## 开发环境

```bash
git clone git@github.com:OpenWSGR/AutoWSGR.git
cd AutoWSGR
uv sync
pre-commit install
```

激活虚拟环境后可直接运行命令（无需 `uv run` 前缀）：

```bash
source .venv/bin/activate   # Linux/macOS
# .venv\Scripts\activate    # Windows
pytest
pre-commit run --all-files
```

## 代码风格

- Python 版本：3.12+
- 格式化与 lint：**Ruff**（已覆盖 isort / black 功能），配置见 `pyproject.toml`
- 目标行宽 100，单引号字符串
- 禁止相对导入（`ban-relative-imports = all`）
- 英语拼写检查：**codespell**，忽略词表见 `docs/spelling_wordlist.txt`

提交前务必运行：

```bash
pre-commit run --all-files
```

## 测试

- 单元测试：`pytest`（测试目录 `testing/`）
- 功能测试：运行 `examples/` 目录中的脚本进行端到端验证

```bash
pytest
```

## 约定式提交（Conventional Commits）

提交信息格式：

```
<type>(<scope>): <简短描述>

<正文>
```

常用类型：

- `feat`：新功能
- `fix`：修复
- `build`：构建系统或依赖变更
- `docs`：文档
- `style`：不影响代码逻辑的格式调整
- `refactor`：重构
- `test`：测试

示例：

```
build: migrate from setuptools to hatchling

- Replace setuptools with hatchling as build backend
- Remove obsolete MANIFEST.in
```

## 构建与打包

- Build backend：**hatchling**
- 包数据（图片、YAML、JAR 等）位于 `autowsgr/data/`，由 hatchling 自动包含，无需 `MANIFEST.in`

```bash
uv build
```

## 文档

- 用户文档地址：https://docs-autowsgr.notion.site
- 代码变更后同步更新文档，并鼓励在代码中编写注释和文档字符串。
