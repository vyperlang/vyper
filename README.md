# Vyper 中文文档 

欢迎来到 Vyper 中文文档项目！

Vyper 是一种面向合约的、类似 Python 的智能合约语言，专为以太坊虚拟机（EVM）设计。为了帮助中文开发者更好地学习和使用 Vyper，我们发起了这个翻译项目。

我们的目标是：

*   **与官方同步**：提供与 [Vyper 官方文档](https://vyper.readthedocs.io/) 内容一致的中文版本。
*   **体验一致**：确保在本地构建和阅读的体验与官方保持一致。
*   **持续更新**：通过自动化流程，持续跟踪上游变更，并更新翻译进度。


无论你是 Vyper 专家，还是热心的开源贡献者，我们都欢迎新的贡献者！你可以通过以下方式参与：

*   认领未翻译的章节，提交 PR 进行翻译或校对。
*   在 [Issues](https://github.com/Vyper-CN-Community/vyper-doc-cn/issues) 中直接报告文档中的错误。
*   提出其他改进建议。

如果你想立即开始，请阅读下方的“贡献指南”。

## 贡献指南：从零开始参与翻译

本指南包括搭建环境、翻译内容到提交贡献的完整流程。

### ✨ 第 1 步：准备工作

在开始之前，请确保安装了以下工具：

*   **Python 3.11+**
*   **Git**
*   **uv** (推荐): [安装指南](https://github.com/astral-sh/uv)

### ⚙️ 第 2 步：环境设置

首先，克隆本仓库并设置好 Python 虚拟环境。

```bash
# 1. 克隆仓库
git clone https://github.com/your-username/vyper-translation-zh.git
cd vyper-translation-zh

# 2. 创建并激活虚拟环境 (推荐使用 uv)
uv venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

# 3. 安装所有必需的依赖
uv pip install -e .[docs]
```
> **提示**：如果命令行提示找不到 `sphinx-build`，请始终使用 `python -m sphinx` 作为替代。

### 📚 第 3 步：翻译与本地预览

核心：更新翻译文件、进行翻译、在本地预览效果。

```bash
# 1. 生成最新的翻译模板 (.pot) 并更新中文翻译文件 (.po)
# 这会从英文源文档中提取需要翻译的文本
python -m sphinx -b gettext docs docs/_build/gettext
sphinx-intl update -p docs/_build/gettext -l zh_CN
```

现在，所有需要翻译的文本都已经准备好了！

*   **找到翻译文件**：所有 `.po` 文件都位于 `docs/locale/zh_CN/LC_MESSAGES/` 目录下。
*   **选择翻译工具**：推荐使用 [Poedit](https://poedit.net/)，它是一款免费且专业的翻译编辑器。当然，任何你喜欢的文本编辑器都可以。
*   **开始翻译**：打开一个 `.po` 文件，将 `msgid`（原文）对应的 `msgstr`（译文）填写完整。

完成一部分翻译后，你可以在本地构建中文文档来检查效果。

```bash
# 2. 构建中文 HTML 文档
python -m sphinx -b html -D language=zh_CN docs docs/_build/html/zh_CN

# 3. 在浏览器中预览
# 打开 docs/_build/html/zh_CN/index.html 文件，查看你的翻译效果！
```

### ✔️ 第 4 步：构建检查

为了保证文档质量，我们要求所有提交都必须通过构建检查（无任何警告或错误）。

```bash
# 运行严格检查脚本
python scripts/check_docs.py
```
如果出现任何警告或错误，请根据提示进行修正。

### 🚀 第 5 步：提交你的贡献

当你对自己的翻译感到满意并通过了检查后，就可以提交 Pull Request 了！

```bash
# 1. （可选）更新 README 中的翻译进度统计
python scripts/po_stats.py > po_stats.json
python scripts/update_readme_progress.py

# 2. 创建一个新的分支
git checkout -b feature/translate-built-in-functions

# 3. 添加你的修改并提交
# 遵循“约定式提交”规范，这很重要！
git add docs/locale/zh_CN/LC_MESSAGES/ a-file-you-translated.po README.md
git commit -m "docs(i18n): translate built-in-functions chapter"

# 4. 推送到你的 Fork 仓库
git push -u origin feature/translate-built-in-functions
```

最后，在 GitHub 上打开一个 Pull Request。请在 PR 描述中说明你翻译或校对的章节。我们会尽快审查并合并你的贡献。


## 翻译规范与建议

为了保持文档的一致性和专业性，请在翻译时遵循以下规范：

*   **术语一致**：请务必参考项目根目录下的 `TERMS.md` 或 `TERMS.csv` 文件，确保专业术语的翻译保持统一。
*   **风格指南**：遵循通用的中文技术文档书写规范，例如在中文与英文、数字之间添加空格，正确使用全角和半角标点符号。
*   **保持结构**：请勿改动源文件（RST）中的标号、交叉引用锚点（如 ``:ref:``）和格式标记。

## 项目维护与自动化


*   **与上游保持一致**：
    *   **Sphinx 版本**：我们严格遵循上游 `vyperlang/vyper` 项目中 `pyproject.toml` 和 `requirements-docs.txt` 定义的版本。
    *   **构建配置**：`docs/conf.py` 文件与上游对齐，并配置为在严格模式（`-n -W`）下无警告通过。
    *   **Read the Docs**：仓库已包含 `.readthedocs.yaml` 配置文件，可直接在 Read the Docs 平台部署。

*   **CI 与自动化流程**：
    *   **上游文档同步**：GitHub Action (`sync_docs.yml`) 会每日检查上游仓库的 `docs/` 目录变更，并自动创建同步 PR，附带翻译统计摘要。
    *   **翻译进度更新**：GitHub Action (`update_readme_progress.yml`) 会在 `master` 分支有新提交时，自动计算并更新下方“翻译进度”区块的内容。
    *   **智能 CI 过滤**：对于仅修改文档的提交，CI 会自动跳过不相关的构建、测试和代码分析任务，以节省资源和时间。

## 翻译进度（自动更新）

以下区块由 CI 自动维护，请勿手动修改：

<!-- START:PO_STATS -->
尚无统计，等待 CI 生成…
<!-- END:PO_STATS -->

> 你也可以在本地运行以下命令来手动更新进度：
>
> ```bash
> python scripts/po_stats.py > po_stats.json
> python scripts/update_readme_progress.py
> ```

## 常见问题

*   **Sphinx 引用类型未解析**：我们已在 `docs/conf.py` 中使用 `nitpick_ignore` 屏蔽了 Vyper 伪类型导致的严格校验错误，以保证构建通过。
*   **重复的锚点/链接名**：当遇到链接名冲突时，优先使用匿名链接（`__`）或重命名本地锚点。
*   **Windows 路径问题**：本指南中的示例路径可能使用 `/`。如果你在 `cmd.exe` 中遇到问题，请尝试将其替换为 `\`。