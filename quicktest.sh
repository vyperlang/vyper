#!/usr/bin/env bash

# examples:
# ./quicktest.sh
# ./quicktest.sh tests/.../mytest.py

# run pytest but bail out on first error and suppress coverage.
# useful for dev workflow
pytest -q --no-cov -s --instafail -x --disable-warnings "$@"
