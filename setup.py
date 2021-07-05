# -*- coding: utf-8 -*-

import os
import subprocess

from setuptools import find_packages, setup

__version__ = "0.2.13"

extras_require = {
    "test": [
        "pytest>=5.4,<6.0",
        "pytest-cov>=2.10,<3.0",
        "pytest-xdist>=1.32,<2.0",
        "eth-tester[py-evm]>=0.5.0b1,<0.6",
        "web3==5.12.3",
        "tox>=3.15,<4.0",
        "lark-parser==0.10.0",
        "hypothesis[lark]>=5.37.1,<6.0",
    ],
    "lint": [
        "black==19.10b0",
        "flake8==3.8.3",
        "flake8-bugbear==20.1.4",
        "flake8-use-fstring==1.1",
        "isort==5.7.0",
        "mypy==0.780",
    ],
    "docs": ["recommonmark", "sphinx>=3.0,<4.0", "sphinx_rtd_theme>=0.5,<0.6"],
    "dev": ["ipython", "pre-commit", "pyinstaller", "twine"],
}

extras_require["dev"] = (
    extras_require["test"] + extras_require["lint"] + extras_require["docs"] + extras_require["dev"]
)

hash_file_rel_path = os.path.join("vyper", "vyper_git_version.txt")
hashfile = os.path.relpath(hash_file_rel_path)

try:
    commithash = subprocess.check_output("git rev-parse HEAD".split())
    commithash_str = commithash.decode("utf-8").strip()
    with open(hashfile, "w") as fh:
        fh.write(f"{__version__}\n{commithash_str}")
except subprocess.CalledProcessError:
    pass

with open("README.md", "r") as f:
    long_description = f.read()

setup(
    name="vyper",
    version=__version__,
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
    python_requires=">=3.6",
    py_modules=["vyper"],
    install_requires=["asttokens==2.0.4", "pycryptodome>=3.5.1,<4", "semantic-version==2.8.5"],
    setup_requires=["pytest-runner"],
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
        "Programming Language :: Python :: 3.6",
    ],
    data_files=[("", [hash_file_rel_path])],
)
