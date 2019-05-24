
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

clean: clean-build clean-pyc clean-test

clean-build:
	rm -fr build/
	rm -fr dist/
	rm -fr *.egg-info

clean-pyc:
	find . -name '*.pyc' -exec rm -f {} +
	find . -name '*.pyo' -exec rm -f {} +
	find . -name '*~' -exec rm -f {} +
	find . -name '__pycache__' -exec rmdir {} +

clean-test:
	find . -name 'htmlcov' -exec rm -rf {} +

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


release: clean
	bumpversion devnum
	git push upstream && git push upstream --tags
	python setup.py sdist bdist_wheel
	twine upload dist/*
