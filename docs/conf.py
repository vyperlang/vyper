# Vyper documentation build configuration file, created by
# sphinx-quickstart on Wed Jul 26 11:18:29 2017.

extensions = [
    "sphinx_copybutton",
    "sphinx.ext.intersphinx",
]

templates_path = ["_templates"]
master_doc = "toctree"

# General information about the project.
project = "Vyper"
copyright = "2017-2025 CC-BY-4.0 Vyper Team"
author = "Vyper Team (originally created by Vitalik Buterin)"

# The language for content autogenerated by Sphinx. Refer to documentation
# for a list of supported languages.
#
# This is also used if you do content translation via gettext catalogs.
# Usually you set "language" from the command line for these cases.
language = "vyper"

# -- Options for HTML output ----------------------------------------------
html_theme = "shibuya"
html_theme_options = {
    "accent_color": "purple",
    "twitter_creator": "vyperlang",
    "twitter_site": "vyperlang",
    "twitter_url": "https://twitter.com/vyperlang",
    "github_url": "https://github.com/vyperlang",
}
html_favicon = "logo.svg"
html_logo = "logo.svg"

# For the "Edit this page ->" link
html_context = {
    "source_type": "github",
    "source_user": "vyperlang",
    "source_repo": "vyper",
}

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
