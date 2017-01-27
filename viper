#!/usr/bin/env python3

from compiler_plugin import Compiler
import argparse

compiler = Compiler()
parser = argparse.ArgumentParser()
parser.add_argument("input")
args = parser.parse_args()

if __name__ == '__main__':
    with open(args.input) as fh:
        code = fh.read()
        print(compiler.compile(code).hex())
