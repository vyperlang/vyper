SHELL := /bin/bash

.PHONY: test lint clean clean-pyc clean-build clean-test docs

test:
	uv run pytest

lint: mypy black flake8 isort

mypy:
	uv run mypy -p vyper

black:
	uv run black vyper/ tests/ setup.py

flake8: black
	uv run flake8 vyper/ tests/

isort: black
	uv run isort vyper/ tests/ setup.py

docs:
	rm -f docs/vyper.rst
	rm -f docs/modules.rst
	uv run sphinx-apidoc -o docs/ -d 2 vyper/
	$(MAKE) -C docs clean
	$(MAKE) -C docs html
	# To display docs, run:
	# open docs/_build/html/index.html (macOS)
	# start docs/_build/html/index.html (Windows)
	# xdg-open docs/_build/html/index.html (Linux)

release: clean
	uv build
	uv run twine check dist/*
	#uv run twine upload dist/*

freeze: clean
	echo Generating binary...
	export OS="$$(uname -s | tr A-Z a-z)" && \
	export VERSION="$$(uv run --no-dev vyper --version)" && \
	uv run --no-dev --group freeze pyinstaller --target-architecture=universal2 --clean --onefile vyper/cli/vyper_compile.py --name "vyper.$${VERSION}.$${OS}" --add-data vyper:vyper

clean: clean-build clean-docs clean-pyc clean-test

clean-build:
	@echo Cleaning python build files...
	@rm -fr build/
	@rm -fr _build/ # docs build dir
	@rm -fr dist/
	@rm -fr *.egg-info
	@rm -f vyper/version.py
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
