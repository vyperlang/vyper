# -*- coding: utf-8 -*-

from setuptools import setup, find_packages


with open('README.md') as f:
    readme = f.read()

with open('LICENSE') as f:
    license = f.read()


setup(
    name='vyper',
    # *IMPORTANT*: Don't manually change the version here. Use the 'bumpversion' utility.
    version='0.1.0-beta.1',
    description='Vyper Programming Language for Ethereum',
    long_description=readme,
    author='Vitalik Buterin',
    author_email='',
    url='https://github.com/ethereum/vyper',
    license=license,
    packages=find_packages(exclude=('tests', 'docs')),
    python_requires='>=3.6',
    install_requires=['py-evm==0.2.0a18'],
    setup_requires=['pytest-runner'],
    tests_require=[
       'pytest',
       'pytest-cov',
       'eth-tester==0.1.0b26',
       'py-evm==0.2.0a18',
    ],
    scripts=[
       'bin/vyper',
       'bin/vyper-serve',
       'bin/vyper-run',
    ]
)
