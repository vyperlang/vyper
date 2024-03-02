SHELL := /bin/bash

ifeq (, $(shell which pip3))
	pip := $(shell which pip3)
else
	pip := $(shell which pip)
endif

.PHONY: test dev-deps lint clean clean-pyc clean-build clean-test docs

init:
	python setup.py install

dev-init:
	${pip} install .[dev]

test:
	pytest

lint: mypy black flake8 isort

mypy:
	mypy --install-types --non-interactive --follow-imports=silent --ignore-missing-imports --implicit-optional -p vyper

black:
	black -C -t py311 vyper/ tests/ setup.py --force-exclude=vyper/version.py

flake8: black
	flake8 vyper/ tests/

isort: black
	isort vyper/ tests/ setup.py

docs:
	rm -f docs/vyper.rst
	rm -f docs/modules.rst
	sphinx-apidoc -o docs/ -d 2 vyper/
	$(MAKE) -C docs clean
	$(MAKE) -C docs html
	# To display docs, run:
	# open docs/_build/html/index.html (macOS)
	# start docs/_build/html/index.html (Windows)
	# xdg-open docs/_build/html/index.html (Linux)

release: clean
	python setup.py sdist bdist_wheel
	twine check dist/*
	#twine upload dist/*

freeze: clean init
	echo Generating binary...
	export OS="$$(uname -s | tr A-Z a-z)" && \
	export VERSION="$$(PYTHONPATH=. python vyper/cli/vyper_compile.py --version)" && \
	pyinstaller --target-architecture=universal2 --clean --onefile vyper/cli/vyper_compile.py --name "vyper.$${VERSION}.$${OS}" --add-data vyper:vyper

clean: clean-build clean-docs clean-pyc clean-test

clean-build:
	@echo Cleaning python build files...
	@rm -fr build/
	@rm -fr _build/ # docs build dir
	@rm -fr dist/
	@rm -fr *.egg-info
	@rm -f vyper/version.py vyper/vyper_git_version.txt vyper/vyper_git_commithash.txt
	@rm -f *.spec

clean-docs:
	@echo Cleaning doc build files...
	@rm -rf docs/_build/
	@rm -f docs/modules.rst
	@rm -f docs/vyper.rst
	@rm -f docs/vyper.*.rst

clean-pyc:
	@echo Cleaning python files...
	@find . -name '*.pyc' -exec rm -f {} +
	@find . -name '*.pyo' -exec rm -f {} +
	@find . -name '*~' -exec rm -f {} +
	@find . -name '__pycache__' -exec rmdir {} +

clean-test:
	@echo Cleaning test files...
	@find . -name 'htmlcov' -exec rm -rf {} +
	@rm -fr coverage.xml
	@rm -fr .coverage
	@rm -fr .eggs/
	@rm -fr .hypothesis/
	@rm -fr .pytest_cache/
	@rm -rf .tox/
	@rm -fr .mypy_cache/
