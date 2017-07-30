# -*- coding: utf-8 -*-

from setuptools import setup, find_packages


with open('README.md') as f:
    readme = f.read()

with open('LICENSE') as f:
    license = f.read()

setup(
    name='viper',
    version='0.0.1',
    description='Viper Programming Language for Ethereum',
    long_description=readme,
    author='Vitalik Buterin',
    author_email='',
    url='https://github.com/ethereum/viper',
    license=license,
    packages=find_packages(exclude=('tests', 'docs')),
    install_requires=[
        #'ethereum == 2.0.4',
        #'serpent',
        'pytest-cov',
        'pytest-runner', # Must be after pytest-cov or it will not work
        #           due to https://github.com/pypa/setuptools/issues/196
    ],
    scripts=['bin/viper']
)
