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
    Dict,
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
    ContractPath,
    OutputFormats,
)

T = TypeVar('T')

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
external_interface - Print the External interface of a contract, used for outside contract calls.
opcodes            - List of opcodes as a string
opcodes_runtime    - List of runtime opcodes as a string
ir                 - Print Intermediate Representation in LLL
"""


def _parse_cli_args():
    return _parse_args(sys.argv[1:])


def _parse_args(argv):

    warnings.simplefilter('always')

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
        version=f'{vyper.__version__}+commit.{vyper.__commit__}',
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
    parser.add_argument(
        '-p',
        help='Set the root path for contract imports',
        default='.', dest='root_folder'
    )

    args = parser.parse_args(argv)

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

    compiled = compile_files(
        args.input_files,
        final_formats,
        args.root_folder,
        args.show_gas_estimates
    )

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


def exc_handler(contract_path: ContractPath, exception: Exception) -> None:
    print(f'Error compiling: {contract_path}')
    raise exception


def get_interface_codes(root_path: Path, contract_sources: ContractCodes) -> Dict:
    interface_codes: Dict = {}
    interfaces: Dict = {}

    for file_path, code in contract_sources.items():
        interfaces[file_path] = {}
        parent_path = root_path.joinpath(file_path).parent

        interface_codes = extract_file_interface_imports(code)
        for interface_name, interface_path in interface_codes.items():

            base_paths = [parent_path]
            if not interface_path.startswith('.') and root_path.joinpath(file_path).exists():
                base_paths.append(root_path)
            elif interface_path.startswith('../') and parent_path == root_path:
                raise FileNotFoundError(
                    f"{file_path} - Cannot perform relative import outside of base folder"
                )

            valid_path = get_interface_file_path(base_paths, interface_path)
            with valid_path.open() as fh:
                code = fh.read()
                if valid_path.suffix == '.json':
                    interfaces[file_path][interface_name] = {
                        'type': 'json',
                        'code': json.loads(code.encode())
                    }
                else:
                    interfaces[file_path][interface_name] = {
                        'type': 'vyper',
                        'code': code
                    }

    return interfaces


def get_interface_file_path(base_paths: Sequence, import_path: str) -> Path:
    relative_path = Path(import_path)
    for path in base_paths:
        file_path = path.joinpath(relative_path)
        suffix = next((i for i in ('.vy', '.json') if file_path.with_suffix(i).exists()), None)
        if suffix:
            return file_path.with_suffix(suffix)
    raise FileNotFoundError(f" Cannot locate interface '{import_path}{{.vy,.json}}'")


def compile_files(input_files: Iterable[str],
                  output_formats: OutputFormats,
                  root_folder: str = '.',
                  show_gas_estimates: bool = False) -> OrderedDict:

    if show_gas_estimates:
        parser_utils.LLLnode.repr_show_gas = True

    root_path = Path(root_folder).resolve()
    if not root_path.exists():
        raise FileNotFoundError(f"Invalid root path - '{root_path.as_posix()}' does not exist")

    contract_sources: ContractCodes = OrderedDict()
    for file_name in input_files:
        file_path = Path(file_name)
        try:
            file_str = file_path.resolve().relative_to(root_path).as_posix()
        except ValueError:
            file_str = file_path.as_posix()
        with file_path.open() as fh:
            contract_sources[file_str] = fh.read()

    show_version = False
    if 'combined_json' in output_formats:
        if len(output_formats) > 1:
            raise ValueError("If using combined_json it must be the only output format requested")
        output_formats = ['bytecode', 'bytecode_runtime', 'abi', 'source_map', 'method_identifiers']
        show_version = True

    compiler_data = vyper.compile_codes(
        contract_sources,
        output_formats,
        exc_handler=exc_handler,
        interface_codes=get_interface_codes(root_path, contract_sources)
    )
    if show_version:
        compiler_data['version'] = vyper.__version__

    return compiler_data
