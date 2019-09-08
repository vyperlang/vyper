#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
import sys
from vyper.cli import (
    vyper_compile,
    vyper_lll,
    vyper_serve
)

if __name__ == "__main__":

    allowed_subcommands = {
        "--vyper-compile": vyper_compile,
        "--vyper-lll": vyper_lll,
        "--vyper-serve": vyper_serve
    }

    if not len(sys.argv) > 1 or sys.argv[1] not in allowed_subcommands.keys():
        # default (no args, no switch in first arg): run vyper_compile
        vyper_compile._parse_cli_args()
    else:
        # pop switch and forward args to subcommand
        allowed_subcommands.get(sys.argv.pop(1), vyper_compile)._parse_cli_args()
