FROM ubuntu:17.04

MAINTAINER Obul <obulpathi@merkletree.vc>

# install dependencies
RUN apt-get update && apt-get install -y git libssl-dev libffi-dev python3.6 python3.6-dev python3-pip
RUN pip install virtualenv

# create virtual environment
RUN virtualenv --python=/usr/bin/python3.6 --no-site-packages /code/.venv
RUN source /code/.venv/bin/activate

# download and install Viper
WORKDIR /code
RUN git clone https://github.com/ethereum/viper.git
WORKDIR /code/viper
RUN python setup.py install
