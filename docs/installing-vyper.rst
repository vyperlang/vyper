Installing Vyper
################

Take a deep breath, follow the instructions, and please
`create an issue <https://github.com/vyperlang/vyper/issues>`_ if you encounter
any errors.

.. note::

    The easiest way to try out the language, experiment with examples, and
    compile code is to use the `Remix online compiler <https://remix.ethereum.org>`_.

Docker
******

Vyper can be downloaded as docker image from dockerhub:
::

    docker pull vyperlang/vyper

To run the compiler use the `docker run` command:
::

    docker run -v $(pwd):/code vyperlang/vyper /code/<contract_file.vy>

Alternatively you can log into the docker image and execute vyper on the prompt.
::

    docker run -v $(pwd):/code/ -it --entrypoint /bin/bash vyperlang/vyper
    root@d35252d1fb1b:/code# vyper <contract_file.vy>

The normal paramaters are also supported, for example:
::

    docker run -v $(pwd):/code vyperlang/vyper -f abi /code/<contract_file.vy>
    [{'name': 'test1', 'outputs': [], 'inputs': [{'type': 'uint256', 'name': 'a'}, {'type': 'bytes', 'name': 'b'}], 'constant': False, 'payable': False, 'type': 'function', 'gas': 441}, {'name': 'test2', 'outputs': [], 'inputs': [{'type': 'uint256', 'name': 'a'}], 'constant': False, 'payable': False, 'type': 'function', 'gas': 316}]

PIP
***

Each tagged version of vyper is also uploaded to `pypi <https://pypi.org/project/vyper/>`_, and can be installed using ``pip``.
::

    pip install vyper

To install a specific version use:
::

    pip install vyper==0.1.0b17

.. note::

    The ``vyper`` package can only be installed using Python 3.6 or higher.

Troubleshooting
*************

Installing Python
=====================

Vyper can only be built using Python 3.6 and higher. If you need to know how to install the correct version of python,
follow the instructions from the official `Python website <https://wiki.python.org/moin/BeginnersGuide/Download>`_.

Creating a virtual environment
==============================

It is **strongly recommended** to install Vyper in **a virtual Python
environment**, so that new packages installed and dependencies built are
strictly contained in your Vyper project and will not alter or affect your
other development environment set-up.
For easy virtualenv management, we recommend either `pyenv <https://github.com/pyenv/pyenv>`_
or `Poetry <https://github.com/python-poetry/poetry>`_.


.. note::

    To find out more about virtual environments, check out:
    `virtualenv guide <https://virtualenv.pypa.io/en/stable/>`_.
