################
Installing Vyper
################
Don't panic if the installation fails. Vyper is still under development and
undergoes constant changes. Installation will be much more simplified and
optimized after a stable version release.

Take a deep breath, follow the instructions, and please
`create an issue <https://github.com/ethereum/vyper/issues>`_ if you encounter
any errors.

.. note::
   The easiest way to try out the language, experiment with examples, and compile code to ``bytecode``
   or ``LLL`` is to use the online compiler at https://vyper.tools.

*************
Prerequisites
*************
Installing Python 3.6
=====================
Vyper can only be built using Python 3.6 and higher. If you are already running
Python 3.6, skip to the next section, else follow the instructions here to make
sure you have the correct Python version installed, and are using that version.

Ubuntu
------
16.04 and older
^^^^^^^^^^^^^^^
Start by making sure your packages are up-to-date:
::
    sudo apt-get update
    sudo apt-get -y upgrade

Install Python 3.6 and some necessary packages:
::
    sudo apt-get install build-essential libssl-dev libffi-dev
    wget https://www.python.org/ftp/python/3.6.2/Python-3.6.2.tgz
    tar xfz Python-3.6.2.tgz
    cd Python-3.6.2/
    ./configure --prefix /usr/local/lib/python3.6
    sudo make
    sudo make install


16.10 and newer
^^^^^^^^^^^^^^^
From Ubuntu 16.10 onwards, the Python 3.6 version is in the `universe`
repository.

Run the following commands to install:
::
    sudo apt-get update
    sudo apt-get install python3.6

MacOS
-----
Make sure you have Homebrew installed. If you don't have the `brew` command
available on the terminal, follow `these instructions <https://docs.brew.sh/Installation.html>`_
to get Homebrew on your system.

To install Python 3.6, follow the instructions here:
`Installing Python 3 on Mac OS X <http://python-guide.readthedocs.io/en/latest/starting/install3/osx/>`_

Also, ensure the GMP arithmetic library is installed using `brew`:
::
    brew install gmp

Creating a virtual environment
==============================
It is **strongly recommended** to install Vyper in **a virtual Python
environment**, so that new packages installed and dependencies built are
strictly contained in your Vyper project and will not alter or affect your
other development environment set-up.


To create a new virtual environment for Vyper run the following commands:
::
    virtualenv -p python3.6 --no-site-packages ~/vyper-venv
    source ~/vyper-venv/bin/activate

To find out more about virtual environments, check out:
`virtualenv guide <https://virtualenv.pypa.io/en/stable/>`_.

************
Installation
************
Again, it is **strongly recommended to install Vyper** in a **virtual Python environment**. 
This guide assumes you are in a virtual environment containing Python 3.6. 

Get the latest version of Vyper by cloning the Github repository, and run the
install and test commands:
::
    git clone https://github.com/ethereum/vyper.git
    cd vyper
    make
    make test

Additionally, you may try to compile an example contract by running:
::
    vyper examples/crowdfund.v.py

If everything works correctly, you are now able to compile your own smart contracts written in Vyper.
However, please keep in mind that Vyper is still experimental and not ready for production!

.. note::
    If you get the error `fatal error: openssl/aes.h: No such file or directory` in the output of `make`, then run `sudo apt-get install libssl-dev1`, then run `make` again.

    **For MacOS users:**

    Apple has deprecated use of OpenSSL in favor of its own TLS and crypto
    libraries. This means that you will need to export some OpenSSL settings
    yourself, before you can install Vyper.

    Use the following commands:
    ::
        export CFLAGS="-I$(brew --prefix openssl)/include"
        export LDFLAGS="-L$(brew --prefix openssl)/lib"
        pip install scrypt

    Now you can run the install and test commands again:
    ::
        make
        make test
    
    If you get the error `ld: library not found for -lyaml` in the output of `make`, make sure `libyaml` is installed using `brew info libyaml`. If it is installed, add its location to the compile flags as well:
    ::
        export CFLAGS="-I$(brew --prefix openssl)/include -I$(brew --prefix libyaml)/include"
        export LDFLAGS="-L$(brew --prefix openssl)/lib -L$(brew --prefix libyaml)/lib"
        
    You can then run `make` and `make test` again.
******
Docker
******
A Dockerfile is provided in the master branch of the repository. In order to build a Docker Image please run:
::
    docker build https://github.com/ethereum/vyper.git -t vyper:1
    docker run -it vyper:1 /bin/bash
To ensure that everything works correctly after the installtion, please run the test commands
and try compiling a contract:
::
    make test
    vyper examples/crowdfund.v.py

****
Snap
****

Vyper is published in the snap store. In any of the `supported Linux distros <https://snapcraft.io/docs/core/install>`_, install it with:
::
    sudo snap install viper --edge


(Note that this is an experimental and unstable release, at the moment)
