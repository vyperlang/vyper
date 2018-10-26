# -*- coding: utf-8 -*-

from setuptools import setup, find_packages


setup(
    name='vyper',
    # *IMPORTANT*: Don't manually change the version here. Use the 'bumpversion' utility.
    version='0.1.0-beta.4',
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
        'pytest-runner'
    ],
    tests_require=[
        'pytest',
        'pytest-cov',
        'py-evm==0.2.0a32',
        'eth-tester[py-evm]==0.1.0b32',
        'web3==4.4.1',
    ],
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
