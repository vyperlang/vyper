.PHONY: docs

init:
	python setup.py install

test:
	python setup.py test

docs:
	rm -f docs/viper.rst
	rm -f docs/modules.rst
	sphinx-apidoc -o docs/ -d 2 viper/
	$(MAKE) -C docs clean
	$(MAKE) -C docs html
	open docs/_build/html/index.html
