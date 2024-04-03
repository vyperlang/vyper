#!/usr/bin/env bash

# examples:
# ./quicktest.sh
# ./quicktest.sh tests/.../mytest.py

# run pytest but bail out on first error
# useful for dev workflow
pytest -q -s --instafail -x --disable-warnings "$@"
