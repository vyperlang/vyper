FROM python:3.7-slim

# Specify label-schema specific arguments and labels.
ARG BUILD_DATE
ARG VCS_REF
LABEL org.label-schema.build-date=$BUILD_DATE \
    org.label-schema.name="Vyper" \
    org.label-schema.description="Vyper is an experimental programming language" \
    org.label-schema.url="https://vyper.readthedocs.io/en/latest/" \
    org.label-schema.vcs-ref=$VCS_REF \
    org.label-schema.vcs-url="https://github.com/vyperlang/vyper" \
    org.label-schema.vendor="Vyper Team" \
    org.label-schema.schema-version="1.0"

# coincurve requires libgmp
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        apt-utils \
        gcc \
        git \
        libc6-dev \
        libc-dev \
        libssl-dev \
        libgmp-dev \
    && rm -rf /var/lib/apt/lists/*

ADD . /code

WORKDIR /code

# Pass `--addopts "--version"` because want to execute `python setup.py test` to include test dependencies in built docker-image, but avoid to execute the whole test suite here.
RUN python setup.py install && \
    python setup.py test --addopts "--version" && \
    apt-get purge -y --auto-remove apt-utils gcc libc6-dev libc-dev libssl-dev

ENTRYPOINT ["/usr/local/bin/vyper"]
