Installing Vyper
################

Take a deep breath, follow the instructions, and please
`create an issue <https://github.com/vyperlang/vyper/issues>`_ if you encounter
any errors.

.. note::

    The easiest way to try out the language, experiment with examples, and
    compile code to ``bytecode`` or ``LLL`` is to use the
    `Remix online compiler <https://remix.ethereum.org>`_.

Docker
******

Dockerhub
=========

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

.. note::

    It is highly recommended to use `pyenv <https://github.com/pyenv/pyenv>`_ to manage your Python installation.

Troubleshooting
*************

Installing Python 3.6
=====================

Vyper can only be built using Python 3.6 and higher. If you are not already running
Python 3.6, follow the instructions here to make sure you have the correct Python
version installed, and are using that version.

Ubuntu
------

Run the following commands to install:
::

    sudo apt-get update
    sudo apt-get install python3.6

.. note::

   If you get the error ``Python.h: No such file or directory`` you need to install the python header files for the Python C API with
   ::

       sudo apt-get install python3-dev

.. note::

    If you get the error ``fatal error: openssl/aes.h: No such file or directory`` in the output of ``make``, then run ``sudo apt-get install libssl-dev1``, then run ``make`` again.

Arch
----

Using your aur helper of choice (``yay`` in this example).

::

    yay -S vyper

MacOS
-----

Make sure you have Homebrew installed. If you don't have the ``brew`` command
available on the terminal, follow `these instructions <https://docs.brew.sh/Installation.html>`_
to get Homebrew on your system.

To install Python 3.6, follow the instructions here:
`Installing Python 3 on Mac OS X <https://python-guide.readthedocs.io/en/latest/starting/install3/osx/>`_

Also, ensure the following libraries are installed using ``brew``:
::

    brew install gmp leveldb
    


.. note::

    Apple has deprecated use of OpenSSL in favor of its own TLS and crypto
    libraries. This means that you will need to export some OpenSSL settings
    yourself, before you can install Vyper.

    Use the following commands:
    ::

        export CFLAGS="-I$(brew --prefix openssl)/include"
        export LDFLAGS="-L$(brew --prefix openssl)/lib"
        pip install scrypt

.. note::

    If you get the error ``ld: library not found for -lyaml`` in the output of `make`, make sure ``libyaml`` is installed using ``brew info libyaml``. If it is installed, add its location to the compile flags as well:
    ::

        export CFLAGS="-I$(brew --prefix openssl)/include -I$(brew --prefix libyaml)/include"
        export LDFLAGS="-L$(brew --prefix openssl)/lib -L$(brew --prefix libyaml)/lib"
        

Windows
--------

Windows users can first `install Windows Subsystem for Linux <https://docs.microsoft.com/en-us/windows/wsl/install-win10>`_ and then follow the instructions for Ubuntu, or `install Docker for Windows <https://docs.docker.com/docker-for-windows/install/>`_ and then follow the instructions for Docker.

.. note::
    - Windows Subsystem for Linux is only available for Windows 10.
    - Windows versions that are < 10 and Windows 10 Home should install the slightly outdated `Docker Toolbox <https://docs.docker.com/toolbox/toolbox_install_windows/>`_, as explained in the link.


Creating a virtual environment
==============================

It is **strongly recommended** to install Vyper in **a virtual Python
environment**, so that new packages installed and dependencies built are
strictly contained in your Vyper project and will not alter or affect your
other development environment set-up.


To create a new virtual environment for Vyper run the following commands:
::

    sudo apt install virtualenv
    virtualenv -p python3.6 --no-site-packages ~/vyper-venv
    source ~/vyper-venv/bin/activate

To find out more about virtual environments, check out:
`virtualenv guide <https://virtualenv.pypa.io/en/stable/>`_.


You can also create a virtual environment without virtualenv:
::

   python3.6 -m venv ~/vyper-env
   source ~/vyper-env/bin/activate
    
