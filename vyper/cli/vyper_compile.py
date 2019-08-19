#!/usr/bin/env python3
import argparse
from collections import (
    OrderedDict,
)
import json
from pathlib import (
    Path,
)
import sys
from typing import (
    Any,
    Iterable,
    Iterator,
    Sequence,
    Set,
    TypeVar,
)
import warnings

import vyper
from vyper.parser import (
    parser_utils,
)
from vyper.settings import (
    VYPER_TRACEBACK_LIMIT,
)
from vyper.signatures.interface import (
    extract_file_interface_imports,
)
from vyper.typing import (
    ContractCodes,
    ContractName,
)

T = TypeVar('T')


def _parse_cli_args():

    warnings.simplefilter('always')

    format_options_help = """Format to print, one or more of:
    bytecode (default) - Deployable bytecode
    bytecode_runtime   - Bytecode at runtime
    abi                - ABI in JSON format
    abi_python         - ABI in python format
    ast                - AST in JSON format
    source_map         - Vyper source map
    method_identifiers - Dictionary of method signature to method identifier.
    combined_json      - All of the above format options combined as single JSON output.
    interface          - Print Vyper interface of a contract
    external_interface - Print Externa Contract of a contract, to be used as outside contract calls.
    opcodes            - List of opcodes as a string
    opcodes_runtime    - List of runtime opcodes as a string
    """

    parser = argparse.ArgumentParser(
        description='Vyper programming language for Ethereum',
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        'input_files',
        help='Vyper sourcecode to compile',
        nargs='+',
    )
    parser.add_argument(
        '--version',
        action='version',
        version='{0}+commit.{1}'.format(vyper.__version__, vyper.__commit__),
    )
    parser.add_argument(
        '--show-gas-estimates',
        help='Show gas estimates in ir output mode.',
        action="store_true",
    )
    parser.add_argument(
        '-f',
        help=format_options_help,
        default='bytecode', dest='format',
    )
    parser.add_argument(
        '--traceback-limit',
        help='Set the traceback limit for error messages reported by the compiler',
        type=int,
    )

    args = parser.parse_args()

    if args.traceback_limit is not None:
        sys.tracebacklimit = args.traceback_limit
    elif VYPER_TRACEBACK_LIMIT is not None:
        sys.tracebacklimit = VYPER_TRACEBACK_LIMIT
    else:
        # Python usually defaults sys.tracebacklimit to 1000.  We use a default
        # setting of zero so error printouts only include information about where
        # an error occurred in a Vyper source file.
        sys.tracebacklimit = 0

    output_formats = tuple(uniq(args.format.split(',')))

    translate_map = {
        'abi_python': 'abi',
        'json': 'abi',
        'ast': 'ast_dict'
    }
    final_formats = []

    for f in output_formats:
        final_formats.append(translate_map.get(f, f))

    compiled = compile_files(args.input_files, final_formats, args.show_gas_estimates)

    if output_formats == ('combined_json',):
        print(json.dumps(compiled))
        return

    for contract_data in list(compiled.values()):
        for f in output_formats:
            o = contract_data[translate_map.get(f, f)]
            if f in ('abi', 'json', 'ast', 'source_map'):
                print(json.dumps(o))
            else:
                print(o)


def uniq(seq: Iterable[T]) -> Iterator[T]:
    """
    Yield unique items in ``seq`` in order.
    """
    seen: Set[T] = set()

    for x in seq:
        if x in seen:
            continue

        seen.add(x)
        yield x


def exc_handler(contract_name: ContractName, exception: Exception) -> None:
    print('Error compiling: ', contract_name)
    raise exception


def get_interface_codes(codes: ContractCodes) -> Any:
    interface_codes = {}
    interfaces = {}

    for code in codes.values():
        interface_codes.update(extract_file_interface_imports(code))

    if interface_codes:
        for interface_name, interface_path in interface_codes.items():
            file_path = Path(interface_path.replace('.', '/')).resolve()

            try:
                suffix = next(i for i in ('.vy', '.json') if file_path.with_suffix(i).exists())
            except StopIteration:
                raise Exception(
                    f'Imported interface "{interface_path}{{.vy,.json}}" does not exist.'
                )

            valid_path = file_path.with_suffix(suffix)
            with valid_path.open() as fh:
                code = fh.read()
                if valid_path.suffix == '.json':
                    interfaces[interface_name] = {
                        'type': 'json',
                        'code': json.loads(code.encode())
                    }
                else:
                    interfaces[interface_name] = {
                        'type': 'vyper',
                        'code': code
                    }

    return interfaces


def compile_files(input_files: Iterable[str],
                  output_formats: Sequence[str],
                  show_gas_estimates: bool = False) -> OrderedDict:

    if show_gas_estimates:
        parser_utils.LLLnode.repr_show_gas = True

    codes: ContractCodes = OrderedDict()
    for file_name in input_files:
        with open(file_name) as fh:
            codes[file_name] = fh.read()

    if 'combined_json' in output_formats:
        if len(output_formats) > 1:
            raise ValueError("If using combined_json it must be the only output format requested")
        output_formats = ['bytecode', 'bytecode_runtime', 'abi', 'source_map', 'method_identifiers']

    compiler_data = vyper.compile_codes(
        codes,
        output_formats,
        exc_handler=exc_handler,
        interface_codes=get_interface_codes(codes)
    )
    if 'combined_json' in output_formats:
        compiler_data['version'] = vyper.__version__

    return compiler_data
