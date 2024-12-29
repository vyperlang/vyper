FROM python:3.11-slim

# Specify label-schema specific arguments and labels.
ARG BUILD_DATE
ARG VCS_REF
LABEL org.label-schema.build-date=$BUILD_DATE \
    org.label-schema.name="Vyper" \
    org.label-schema.description="Vyper is an experimental programming language" \
    org.label-schema.url="https://docs.vyperlang.org/en/latest/" \
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

# force repository to be clean so the version string is right
RUN git reset --hard

# Using "test" optional to include test dependencies in built docker-image
RUN pip install --no-cache-dir .[test] && \
    apt-get purge -y --auto-remove apt-utils gcc libc6-dev libc-dev libssl-dev

ENTRYPOINT ["/usr/local/bin/vyper"]
