FROM python:3.6

MAINTAINER Obul <obulpathi@merkletree.vc>

# install libgmp
RUN apt-get update
RUN apt-get install -y libgmp-dev

# download and install Viper
WORKDIR /code
RUN git clone https://github.com/ethereum/viper.git
WORKDIR /code/viper
RUN python setup.py install
