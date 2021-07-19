SHELL := /bin/bash
OS := $(shell uname -s | tr A-Z a-z)
VERSION := $(shell PYTHONPATH=. python vyper/cli/vyper_compile.py --version)

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

# run pytest but bail out on first error. useful for dev workflow
quicktest:
	python setup.py test --addopts -x

mypy:
	tox -e mypy

lint:
	tox -e lint

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
	pyinstaller --clean --onefile vyper/cli/vyper_compile.py --name vyper.$(VERSION).$(OS) --add-data vyper:vyper

clean: clean-build clean-docs clean-pyc clean-test

clean-build:
	@echo Cleaning python build files...
	@rm -fr build/
	@rm -fr dist/
	@rm -fr *.egg-info
	@rm -f vyper/vyper_git_version.txt
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
