#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
import sys

from vyper.cli import vyper_compile, vyper_ir

if __name__ == "__main__":
    allowed_subcommands = ("--vyper-compile", "--vyper-ir")

    if len(sys.argv) <= 1 or sys.argv[1] not in allowed_subcommands:
        # default (no args, no switch in first arg): run vyper_compile
        vyper_compile._parse_cli_args()
    else:
        # pop switch and forward args to subcommand
        subcommand = sys.argv.pop(1)
        if subcommand == "--vyper-ir":
            vyper_ir._parse_cli_args()
        else:
            vyper_compile._parse_cli_args()
