# -*- coding: utf-8 -*-

import re

from setuptools import find_packages, setup

extras_require = {
    "test": [
        "pytest>=6.2.5,<7.0",
        "pytest-cov>=2.10,<3.0",
        "pytest-instafail>=0.4,<1.0",
        "pytest-xdist>=1.32,<2.0",
        "eth-tester[py-evm]>=0.6.0b4,<0.7",
        "py-evm>=0.5.0a3,<0.6",
        "web3==5.27.0",
        "tox>=3.15,<4.0",
        "lark-parser==0.10.0",
        "hypothesis[lark]>=5.37.1,<6.0",
    ],
    "lint": [
        "black==21.9b0",
        "flake8==3.9.2",
        "flake8-bugbear==20.1.4",
        "flake8-use-fstring==1.1",
        "isort==5.9.3",
        "mypy==0.910",
    ],
    "docs": ["recommonmark", "sphinx>=3.0,<4.0", "sphinx_rtd_theme>=0.5,<0.6"],
    "dev": ["ipython", "pre-commit", "pyinstaller", "twine"],
}

extras_require["dev"] = (
    extras_require["test"] + extras_require["lint"] + extras_require["docs"] + extras_require["dev"]
)

with open("README.md", "r") as f:
    long_description = f.read()


# force commit hash to be appended to version even when tag is exact
# (breaks PEP 440, but this is the debug info, not the version tag for pypi)
def _local_version(version):
    commithash = version.node[1:]  # git describe adds 'g' prefix
    ret = f"+commit.{commithash}"
    if version.dirty:
        ret += "-dirty"
    return ret


def _global_version(version):
    from setuptools_scm.version import guess_next_dev_version

    # strip `.devN` suffix since it is not semver compatible
    # minor regex hack to avoid messing too much with setuptools-scm internals
    version_str = guess_next_dev_version(version)
    return re.sub(r"\.dev\d+", "", version_str)


setup(
    name="vyper",
    use_scm_version={
        "local_scheme": _local_version,
        "version_scheme": _global_version,
        "write_to": "vyper/version.py",
    },
    description="Vyper: the Pythonic Programming Language for the EVM",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Vyper Team",
    author_email="",
    url="https://github.com/vyperlang/vyper",
    license="Apache License 2.0",
    keywords="ethereum evm smart contract language",
    include_package_data=True,
    packages=find_packages(exclude=("tests", "docs")),
    python_requires=">=3.7,<3.11",
    py_modules=["vyper"],
    install_requires=[
        "asttokens==2.0.5",
        "pycryptodome>=3.5.1,<4",
        "semantic-version==2.8.5",
        "cached-property==1.5.2 ; python_version<'3.8'",
        "importlib-metadata ; python_version<'3.8'",
        "wheel",
    ],
    setup_requires=["pytest-runner", "setuptools_scm"],
    tests_require=extras_require["test"],
    extras_require=extras_require,
    entry_points={
        "console_scripts": [
            "vyper=vyper.cli.vyper_compile:_parse_cli_args",
            "vyper-serve=vyper.cli.vyper_serve:_parse_cli_args",
            "vyper-lll=vyper.cli.vyper_lll:_parse_cli_args",
            "vyper-json=vyper.cli.vyper_json:_parse_cli_args",
        ]
    },
    classifiers=[
        "Intended Audience :: Developers",
        "License :: OSI Approved :: Apache Software License",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
    ],
)
