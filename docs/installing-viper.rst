################
Installing Viper
################
Don't panic if the installation fails. Viper is still under development and
undergoes constant changes. Installation will be much more simplified and
optimized after a stable version release.

Take a deep breath and follow, and please
`create an issue <https://github.com/ethereum/viper/issues>`_ if you encounter
any errors.

It is **strongly recommended** to install Viper in **a virtual Python
environment**, so that new packages installed and dependencies built are
strictly contained in your Viper project and will not alter or affect your
other dev environment set-up.

To find out how to set-up a virtual environment, check out:
`virtualenv guide <https://virtualenv.pypa.io/en/stable/>`_.

*********************
Installing Python 3.6
*********************
Viper can only be built using Python 3.6 and higher. If you are already running
Python 3.6, skip to the next section, else follow the instructions here to make
sure you have the correct Python version installed, and are using that version.

Ubuntu
======

16.04 and older
---------------
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
    ./configure –prefix /usr/local/lib/python3.6
    sudo make
    sudo make install


16.10 and newer
---------------
From Ubuntu 16.10 onwards, the Python 3.6 version is in the `universe`
repository.

Run the following commands to install:
::
    sudo apt-get update
    sudo apt-get install python3.6

MacOS
=====
Make sure you have Homebrew installed. If you don't have the `brew` command
available on the terminal, follow `these instructions <https://docs.brew.sh/Installation.html>`_
to get Homebrew on your system.

To install Python 3.6, follow the instructions here:
`Installing Python 3 on Mac OS X <http://python-guide.readthedocs.io/en/latest/starting/install3/osx/>`_

*****
Viper
*****
This guide assumes you are in a virtual environment containing Python 3.6. If
this is not the case, use the following commands to enter create a new virtual
environment:
::
    virtualenv -p /usr/local/lib/python3.6/bin/python --no-site-packages ~/viper-venv
    source ~/viper-venv/bin/activate

Get the latest version of Viper by cloning the Github repository, and run the
install and test commands
::
    git clone https://github.com/ethereum/viper.git
    cd viper
    python setup.py install
    python setup.py test

.. note::
    For the MacOS users:

    Apple has deprecated use of OpenSSL in favor of its own TLS and crypto
    libraries. This means that you will need to export some OpenSSL settings
    yourself, before you can install Viper.

    Use the following commands:
    ::
        export CFLAGS="-I$(brew --prefix openssl)/include"
        export LDFLAGS="-L$(brew --prefix openssl)/lib"
        pip install scrypt

    Now you can run the install and test commands again:
    ::
        python setup.py install
        python setup.py test
