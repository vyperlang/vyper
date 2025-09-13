# Vyper documentation build configuration file, created by
# sphinx-quickstart on Wed Jul 26 11:18:29 2017.

import os
from pathlib import Path

# i18n 说明:
# - 基准语言使用英文(en)，通过环境变量 READTHEDOCS_LANGUAGE 或 DOCS_LANGUAGE 覆盖
# - 翻译目录: locale/<lang>/LC_MESSAGES
# - 生成 .pot: sphinx-build -b gettext docs docs/_build/gettext
# - 更新 zh_CN: sphinx-intl update -p docs/_build/gettext -l zh_CN
# - 构建中文: set DOCS_LANGUAGE=zh_CN && sphinx-build -b html docs docs/_build/html/zh_CN

extensions = [
    "sphinx_copybutton",
    "sphinx.ext.intersphinx",
]

templates_path = ["_templates"]
master_doc = "toctree"

# General information about the project.
project = "Vyper"
copyright = "2017-2024 CC-BY-4.0 Vyper Team"
author = "Vyper Team (originally created by Vitalik Buterin)"

# 动态语言设置
language = os.environ.get("READTHEDOCS_LANGUAGE", os.environ.get("DOCS_LANGUAGE", "en"))
# NOTE: sphinx-intl 默认生成 locale/<lang>/LC_MESSAGES，遵循 Sphinx 最佳实践
locale_dirs = ["locale/"]
gettext_compact = False

# -- Options for HTML output ----------------------------------------------
html_theme = "shibuya"
html_theme_options = {
    "accent_color": "purple",
    "twitter_creator": "vyperlang",
    "twitter_site": "vyperlang",
    "twitter_url": "https://twitter.com/vyperlang",
    "github_url": "https://github.com/vyperlang",
}
# allow missing logo assets without breaking build
_HERE = Path(__file__).parent
_logo = _HERE / "logo.svg"
html_favicon = "logo.svg" if _logo.exists() else None
html_logo = "logo.svg" if _logo.exists() else None

# For the "Edit this page ->" link
_repo_user = os.environ.get("GITHUB_REPOSITORY", "Vyper-CN-Community/vyper-doc-cn").split("/")[0]
_repo_name = os.environ.get("GITHUB_REPOSITORY", "Vyper-CN-Community/vyper-doc-cn").split("/")[-1]
html_context = {
    "source_type": "github",
    # point to current fork by default; override via env GITHUB_REPOSITORY
    "source_user": _repo_user,
    "source_repo": _repo_name,
}

# Read the Docs compatibility
on_rtd = os.environ.get("READTHEDOCS") == "True"
if on_rtd:
    # RTD injects language via READTHEDOCS_LANGUAGE
    pass

# show last updated time in html footer
html_last_updated_fmt = "%Y-%m-%d %H:%M %Z"

# -- Options for HTMLHelp output ------------------------------------------

# Output file base name for HTML help builder.
htmlhelp_basename = "Vyperdoc"


# -- Options for LaTeX output ---------------------------------------------

# Grouping the document tree into LaTeX files. List of tuples
# (source start file, target name, title,
#  author, documentclass [howto, manual, or own class]).
latex_documents = [
    (
        master_doc,
        "Vyper.tex",
        "Vyper Documentation",
        author,
        "manual",
    ),
]


# -- Options for manual page output ---------------------------------------

# One entry per manual page. List of tuples
# (source start file, name, description, authors, manual section).
man_pages = [(master_doc, "vyper", "Vyper Documentation", [author], 1)]


# -- Options for Texinfo output -------------------------------------------

# Grouping the document tree into Texinfo files. List of tuples
# (source start file, target name, title, author,
#  dir menu entry, description, category)
texinfo_documents = [
    (
        master_doc,
        "Vyper",
        "Vyper Documentation",
        author,
        "Vyper",
        "One line description of project.",
        "Miscellaneous",
    ),
]

intersphinx_mapping = {
    "brownie": ("https://eth-brownie.readthedocs.io/en/stable", None),
    "pytest": ("https://docs.pytest.org/en/latest/", None),
    "python": ("https://docs.python.org/3.10/", None),
}

# When building with -n (nitpicky), Sphinx tries to resolve types in
# py:function signatures as Python classes. Our docs use Vyper-specific types
# like "int256", "uint256", "address", etc., which don't exist in the
# Python domain. Silence those via nitpick_ignore to keep strict builds clean.
_vyper_types = {
    "int256",
    "uint256",
    "int128",
    "uint128",
    "uint8",
    "uint16",
    "uint32",
    "uint64",
    "address",
    "bytes32",
    "Bytes",
    "String",
    "Any",
    "Union",
    "bool",
    "decimal",
    "integer",
    "unsigned integer",
    "max_outsize",
    "gasLeft",
    "numeric",
    "type_",
    "DynArray",
    "FixedArray",
    "_Type",
    "_Integer",
    "bytes4",
    "bytes",
    "Bytes[<depends on input>]",
    "Bytes[32]",
    "Bytes[max_outsize]",
}
nitpick_ignore = [("py:class", t) for t in _vyper_types]
