# -*- coding: utf-8 -*-

import os
from setuptools import (
    find_packages,
    setup,
)
import subprocess

extras_require = {
    'test': [
        'pytest>=5.4,<6.0',
        'pytest-cov>=2.10,<3.0',
        'pytest-xdist>=1.32,<2.0',
        'eth-tester[py-evm]>=0.5.0b1,<0.6',
        'web3>=5.11,<6.0',
        'tox>=3.15,<4.0',
        'lark-parser>=0.8,<1.0',
        'hypothesis[lark]>=5.16.2,<6.0',
    ],
    'lint': [
        'black>=19.10b0,<20.0',
        'flake8>=3.8,<4.0',
        'flake8-bugbear>=20.1,<21.0',
        'flake8-use-fstring>=1.1,<2.0',
        'isort>=4.2,<5.0',
        'mypy>=0.780,<1.0',
    ],
    'docs': [
        'recommonmark',
        'sphinx>=3.0,<4.0',
        'sphinx_rtd_theme>=0.5,<0.6',
    ],
    'dev': [
        'ipython',
        'twine',
    ],
}

extras_require['dev'] = (
    extras_require['test'] +
    extras_require['lint'] +
    extras_require['docs'] +
    extras_require['dev']
)

hash_file_rel_path = os.path.join('vyper', 'vyper_git_version.txt')
hashfile = os.path.relpath(hash_file_rel_path)

try:
    commithash = subprocess.check_output("git rev-parse HEAD".split())
    commithash = commithash.decode('utf-8').strip()
    with open(hashfile, 'w') as fh:
        fh.write(commithash)
except subprocess.CalledProcessError:
    pass

setup(
    name='vyper',
    # *IMPORTANT*: Don't manually change the version here. Use the 'bumpversion' utility.
    version='0.1.0-beta.17',
    description='Vyper: the Pythonic Programming Language for the EVM',
    long_description_markdown_filename='README.md',
    long_description_content_type='text/markdown',
    author='Vyper Team',
    author_email='',
    url='https://github.com/vyperlang/vyper',
    license="MIT",
    keywords='ethereum evm smart contract language',
    include_package_data=True,
    packages=find_packages(exclude=('tests', 'docs')),
    python_requires='>=3.6',
    py_modules=['vyper'],
    install_requires=[
        'asttokens==2.0.3',
        'pycryptodome>=3.5.1,<4',
        'semantic-version==2.8.5',
    ],
    setup_requires=[
        'pytest-runner',
        'setuptools-markdown'
    ],
    tests_require=extras_require["test"],
    extras_require=extras_require,
    entry_points={
        'console_scripts': [
            "vyper=vyper.cli.vyper_compile:_parse_cli_args",
            "vyper-serve=vyper.cli.vyper_serve:_parse_cli_args",
            "vyper-lll=vyper.cli.vyper_lll:_parse_cli_args",
            "vyper-json=vyper.cli.vyper_json:_parse_cli_args",
        ]
    },
    classifiers=[
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 3.6',
    ],
    data_files=[('', [hash_file_rel_path])],
)
