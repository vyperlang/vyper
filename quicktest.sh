#!/usr/bin/env bash

# examples:
# ./quicktest.sh
# ./quicktest.sh -m "not fuzzing"
# ./quicktest.sh -m "not fuzzing" -n<cpu cores - 2> (this is the most useful)
# ./quicktest.sh -m "not fuzzing" -n0
# ./quicktest.sh tests/.../mytest.py

# run pytest but bail out on first error
# useful for dev workflow.

pytest -q -s --instafail -x --disable-warnings "$@"

# useful options include:
# -n0  (uses only one core but faster startup)
# -nauto  (uses only one core but faster startup)
# -m "not fuzzing" - skip slow/fuzzing tests
