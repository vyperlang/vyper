# -*- coding: utf-8 -*-

from setuptools import setup, find_packages


with open('README.md') as f:
    readme = f.read()

with open('LICENSE') as f:
    license = f.read()

# *IMPORTANT*: Don't manually change the version here. Use the 'bumpversion' utility.
version = '0.0.4'

setup(
    name='vyper',
    version=version,
    description='Vyper Programming Language for Ethereum',
    long_description=readme,
    author='Vitalik Buterin',
    author_email='',
    url='https://github.com/ethereum/vyper',
    license=license,
    packages=find_packages(exclude=('tests', 'docs')),
    install_requires=['py-evm==0.2.0a12'],
    setup_requires=['pytest-runner'],
    python_requires='>=3.6',
    tests_require=['pytest', 'pytest-cov', 'ethereum==2.3.1'],
    scripts=['bin/vyper', 'bin/vyper-serve', 'bin/vyper-run']
)
