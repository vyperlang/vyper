SHELL := /bin/bash

ifeq (, $(shell which pip3))
	pip := $(shell which pip3)
else
	pip := $(shell which pip)
endif

.PHONY: test dev-deps lint clean clean-pyc clean-build clean-test docs docker-build

init:
	${pip} install .

dev-deps:
	${pip} install .[test,lint]

test:
	python setup.py test

lint:
	tox -e lint

clean: clean-build clean-pyc clean-snap clean-test

clean-build:
	@echo Cleaning python build files...
	@rm -fr build/
	@rm -fr dist/
	@rm -fr *.egg-info

clean-pyc:
	@echo Cleaning python files...
	@find . -name '*.pyc' -exec rm -f {} +
	@find . -name '*.pyo' -exec rm -f {} +
	@find . -name '*~' -exec rm -f {} +
	@find . -name '__pycache__' -exec rmdir {} +

clean-test:
	@echo Cleaning test files...
	@find . -name 'htmlcov' -exec rm -rf {} +

docs:
	rm -f docs/vyper.rst
	rm -f docs/modules.rst
	sphinx-apidoc -o docs/ -d 2 vyper/
	$(MAKE) -C docs clean
	$(MAKE) -C docs html
	open docs/_build/html/index.html

docker-build:
	@docker build -t vyper \
		--build-arg VCS_REF=`git rev-parse --short HEAD` \
		--build-arg BUILD_DATE=`date -u +"%Y-%m-%dT%H:%M:%SZ"` .

# Get the part number from the built docker image, before the '+' symbol
docker-release:
	docker login
	docker tag vyper ethereum/vyper:latest
	docker push ethereum/vyper:latest
	docker tag vyper ethereum/vyper:$(firstword $(subst +, ,$(shell docker run vyper --version)))
	docker push ethereum/vyper:$(firstword $(subst +, ,$(shell docker run vyper --version)))

snap-build:
	snapcraft

vyper-snap := $(wildcard vyper*.snap)

clean-snap: $(vyper-snap)
	@echo Cleaning snapcraft build files...
	@snapcraft clean
ifdef vyper-snap
	@rm -fr $<

snap-release: $(vyper-snap)
	snapcraft login
	snapcraft push $<
endif

# Asks to bump the dev partnumber
# TODO Use semver automatic versioning via git log
git-tag:
	@echo -n "Bump the part number? [y/N]: "
	@read line; if [ $$line == "y" ]; then \
		bumpversion devnum; \
		git push upstream && git push upstream --tags; \
	 fi

pypi-build:
	python setup.py sdist bdist_wheel

pypi-release:
	twine check dist/*
	twine upload dist/*

release: clean
ifndef SKIP_TAG
	$(MAKE) git-tag
endif
ifndef SKIP_SNAP
	$(MAKE) snap-build
	$(MAKE) snap-release
endif
ifndef SKIP_DOCKER
	$(MAKE) docker-build
	$(MAKE) docker-release
endif
ifndef SKIP_PYPI
	$(MAKE) pypi-build
	$(MAKE) pypi-release
endif
