#!/usr/bin/env bash

if [[ -z "${COVERALLS_REPO_TOKEN}" ]]; then
  printf 'COVERALLS_REPO_TOKEN env var not set\n'
else
  coveralls
fi
