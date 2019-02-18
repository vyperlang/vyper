# -*- coding: utf-8 -*-

from setuptools import setup, find_packages
import subprocess, os, tempfile


test_deps = [
    'pytest',
    'pytest-cov',
    'py-evm==0.2.0a34',
    'eth-tester==0.1.0b33',
    'web3==4.8.2',
]


extras = {
    'test': test_deps
}


commithash = subprocess.check_output("git rev-parse --short HEAD".split())
commithash = commithash.decode('utf-8').strip()

tmpdir = tempfile.mkdtemp()
hashfile = os.path.relpath(os.path.join(tmpdir, 'GITVER.txt'))
with open(hashfile, 'w') as f :
    f.write(commithash)

setup(
    name='vyper',
    # *IMPORTANT*: Don't manually change the version here. Use the 'bumpversion' utility.
    version='0.1.0-beta.8',
    description='Vyper Programming Language for Ethereum',
    long_description_markdown_filename='README.md',
    author='Vitalik Buterin',
    author_email='',
    url='https://github.com/ethereum/vyper',
    license="MIT",
    keywords='ethereum',
    include_package_data=True,
    data_files=[('vyper', [hashfile])],
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
