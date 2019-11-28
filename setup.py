# -*- coding: utf-8 -*-

import os
from setuptools import (
    find_packages,
    setup,
)
import subprocess

test_deps = [
    'pytest>=5.2.0,<6',
    'pytest-cov>=2.8.1,<3',
    'coveralls[yaml]>=1.8.2,<2',
    'pytest-xdist>=1.30.0,<2',
    'eth-tester[py-evm]>=0.3.0b1,<0.4',
    'web3>=5.2.0,<5.3.0',
    'tox>=3.7,<4',
    'hypothesis>=4.41.3,<5'
]
lint_deps = [
    'flake8>=3.7,<4',
    'flake8-bugbear>=19.8.0,<20',
    'isort>=4.2.15,<5',
    'mypy>=0.740,<1',
]


extras = {
    'test': test_deps,
    'lint': lint_deps,
}

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
    version='0.1.0-beta.14',
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
        'asttokens==1.1.13',
        'pycryptodome>=3.5.1,<4',
    ],
    setup_requires=[
        'pytest-runner',
        'setuptools-markdown'
    ],
    tests_require=test_deps,
    extras_require=extras,
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
