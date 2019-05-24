# -*- coding: utf-8 -*-

from setuptools import setup, find_packages


test_deps = [
    'pytest>=3.6',
    'pytest-cov==2.4.0',
    'coveralls[yaml]==1.6.0',
    'pytest-xdist==1.18.1',
    'py-evm==0.2.0a39',
    'eth-tester==0.1.0b37',
    'web3==5.0.0a6',
    'tox>=3.7,<4',
    'hypothesis==4.11.7'
]
lint_deps = [
    'flake8>=3.7,<4',
    'flake8-bugbear==18.8.0',
    'isort>=4.2.15,<5',
    'mypy==0.701',
]


extras = {
    'test': test_deps,
    'lint': lint_deps,
}


setup(
    name='vyper',
    # *IMPORTANT*: Don't manually change the version here. Use the 'bumpversion' utility.
    version='0.1.0-beta.10',
    description='Vyper Programming Language for Ethereum',
    long_description_markdown_filename='README.md',
    author='Vitalik Buterin',
    author_email='',
    url='https://github.com/ethereum/vyper',
    license="MIT",
    keywords='ethereum',
    include_package_data=True,
    packages=find_packages(exclude=('tests', 'docs')),
    python_requires='>=3.6',
    py_modules=['vyper'],
    install_requires=[
        'pycryptodome>=3.5.1,<4',
    ],
    setup_requires=[
        'pytest-runner',
        'setuptools-markdown'
    ],
    tests_require=test_deps,
    extras_require=extras,
    scripts=[
        'bin/vyper',
        'bin/vyper-serve',
        'bin/vyper-lll'
    ],
    classifiers=[
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 3.6',
    ]
)
