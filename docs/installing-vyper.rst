Installing Vyper
################

Take a deep breath, follow the instructions, and please
`create an issue <https://github.com/vyperlang/vyper/issues>`_ if you encounter
any errors.

.. tip::

    New to Vyper? Start with the :ref:`quickstart` guide to get a project running quickly.

.. note::

    The easiest way to experiment with the language is to use an online compiler:

    - `Try Vyper! <https://try.vyperlang.org>`_: maintained by the Vyper team, requires GitHub login
    - `Remix <https://remix.ethereum.org>`_: maintained by the Ethereum Foundation, activate the vyper-remix plugin in the Plugin manager


Standalone
**********

The Vyper CLI can be installed with ``uv tool`` or ``pipx``. If you do not have these installed, first visit their installation pages:

- https://github.com/astral-sh/uv
- https://github.com/pypa/pipx

Then install Vyper:

::

    uv tool install vyper

or:

::

    pipx install vyper


Binaries
********

Alternatively, prebuilt Vyper binaries for Windows, Mac and Linux are available for download from the GitHub releases page: https://github.com/vyperlang/vyper/releases.


PIP
***

Installing Python
=================

Vyper can only be built using Python 3.11 and higher. If you need to know how to install the correct version of python,
follow the instructions from the official `Python website <https://wiki.python.org/moin/BeginnersGuide/Download>`_.

Creating a virtual environment
==============================

Because pip installations are not isolated by default, this method of
installation is meant for more experienced Python developers who are using
Vyper as a library, or want to use it within a Python project with other
pip dependencies.

It is **strongly recommended** to install Vyper in **a virtual Python
environment**, so that new packages installed and dependencies built are
strictly contained in your Vyper project and will not alter or affect your
other development environment set-up.

.. note::

    To find out more about virtual environments, check out:
    `virtualenv guide <https://docs.python.org/3/library/venv.html>`_.

Installing Vyper
================

Each tagged version of vyper is uploaded to `pypi <https://pypi.org/project/vyper/>`_, and can be installed inside a virtual environment:
::

    pip install vyper

or:
::

    uv pip install vyper

To install a specific version use:
::

    pip install vyper==0.4.0

You can check if Vyper is installed completely or not by typing the following in your terminal/cmd:
::

    vyper --version


Docker
******

Vyper can be downloaded as docker image from `dockerhub <https://hub.docker.com/r/vyperlang/vyper/tags?page=1&ordering=last_updated>`_:
::

    docker pull vyperlang/vyper

To run the compiler use the ``docker run`` command:
::

    docker run -v $(pwd):/code vyperlang/vyper /code/<contract_file.vy>

Alternatively you can log into the docker image and execute vyper on the prompt.
::

    docker run -v $(pwd):/code/ -it --entrypoint /bin/bash vyperlang/vyper
    root@d35252d1fb1b:/code# vyper <contract_file.vy>

The normal parameters are also supported, for example:
::

    docker run -v $(pwd):/code vyperlang/vyper -f abi /code/<contract_file.vy>
    [{"stateMutability": "nonpayable", "type": "function", "name": "test1", "inputs": [{"name": "a", "type": "uint256"}, {"name": "b", "type": "bytes"}], "outputs": []}, {"stateMutability": "nonpayable", "type": "function", "name": "test2", "inputs": [{"name": "a", "type": "uint256"}], "outputs": []}]

.. note::

    If you would like to know how to install Docker, please follow their `documentation <https://docs.docker.com/get-docker/>`_.

nix
***

View the versions supported through nix at `nix package search <https://search.nixos.org/packages?show=vyper&query=vyper>`_ 

.. note::

    The derivation for Vyper is located at  `nixpkgs <https://github.com/NixOS/nixpkgs/blob/master/pkgs/development/compilers/vyper/default.nix>`_


Installing Vyper
============================

::

    nix-env -iA nixpkgs.vyper


