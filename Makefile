.PHONY: docsclean-pyc clean-build docs

init:
	python setup.py install

test:
	python setup.py test

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
	rm -f docs/viper.rst
	rm -f docs/modules.rst
	sphinx-apidoc -o docs/ -d 2 viper/
	$(MAKE) -C docs clean
	$(MAKE) -C docs html
	open docs/_build/html/index.html

docker-build:
	@docker build -t viper \
		--build-arg VCS_REF=`git rev-parse --short HEAD` \
		--build-arg BUILD_DATE=`date -u +"%Y-%m-%dT%H:%M:%SZ"` .
