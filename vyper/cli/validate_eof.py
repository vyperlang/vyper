#!/usr/bin/env python3
import sys
import argparse

from vyper.evm.eof import EOFReader

def _parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Vyper EOFv1 validation utility",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "input_file",
        help="Input file containing the EOFv1 formated bytecode",
        nargs="?",
    )

    args = parser.parse_args(argv)

    if args.input_file:
      with open(args.input_file, "r") as f:
        code = bytes.fromhex(f.read())
        EOFReader(code)

if __name__ == "__main__":
    _parse_args(sys.argv[1:])
