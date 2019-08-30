#!/usr/bin/env python3

import argparse
import json
from pathlib import (
    Path,
)
import sys
from typing import (
    Callable,
    Dict,
    Tuple,
    Union,
)
import warnings

import vyper
from vyper.cli.vyper_compile import (
    get_interface_file_path,
)
from vyper.exceptions import (
    JSONError,
)
from vyper.signatures.interface import (
    extract_file_interface_imports,
)
from vyper.typing import (
    ContractCodes,
)
from vyper.utils import (
    keccak256,
)


def _parse_cli_args():
    parser = argparse.ArgumentParser(
        description='Vyper programming language for Ethereum - JSON Compiler',
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        'input_file',
        help='JSON file to compile from. If none is given, Vyper will receive it from stdin.',
        nargs='?',
    )
    parser.add_argument(
        '--version',
        action='version',
        version='{0}+commit.{1}'.format(vyper.__version__, vyper.__commit__),
    )
    parser.add_argument(
        '-o',
        help="Filename to save JSON output to. If the file exists it will be overwritten.",
        default=None,
        dest="output_file"
    )
    parser.add_argument(
        '-p',
        help='Set a base import path. Vyper searches here if a file is not found in the JSON.',
        default=None, dest='root_folder'
    )
    parser.add_argument(
        '--pretty-json',
        help='Output JSON in pretty format.',
        action='store_true'
    )
    parser.add_argument(
        '--traceback',
        help='Show python traceback on error instead of returning JSON',
        action='store_true'
    )

    args = parser.parse_args()
    if args.input_file:
        with Path(args.input_file).open() as fh:
            input_json = fh.read()
        json_path = Path(args.input_file).resolve().as_posix()
    else:
        input_json = "".join(sys.stdin.read()).strip()
        json_path = "<stdin>"

    exc_handler = exc_handler_raises if args.traceback else exc_handler_to_json
    output_json = json.dumps(
        compile_json(input_json, exc_handler, args.root_folder, json_path),
        indent=2 if args.pretty_json else None,
        sort_keys=True,
        default=str
    )

    if args.output_file is not None:
        output_path = Path(args.output_file).resolve()
        with output_path.open('w') as fh:
            fh.write(output_json)
        print(f"Results saved to {output_path}")
    else:
        print(output_json)


def get_interface_codes(root_path: Union[Path, None],
                        contract_sources: ContractCodes,
                        interface_sources: Dict) -> Dict:
    interface_codes: Dict = {}
    interfaces: Dict = {}

    for file_path, code in contract_sources.items():
        interfaces[file_path] = {}

        interface_codes = extract_file_interface_imports(code)
        for interface_name, interface_path in interface_codes.items():
            keys = [Path(file_path).parent.joinpath(interface_path).as_posix(), interface_path]

            key = next((i for i in keys if i in interface_sources), None)
            if key:
                interfaces[file_path][interface_name] = interface_sources[key]
                continue

            key = next((i for i in keys if i in contract_sources), None)
            if key:
                interfaces[file_path][interface_name] = {
                    'type': 'vyper',
                    'code': contract_sources[key]
                }
                continue

            if root_path is None:
                raise FileNotFoundError(f"Cannot locate interface '{interface_path}{{.vy,.json}}'")

            parent_path = root_path.joinpath(file_path).parent
            base_paths = [parent_path]
            if not interface_path.startswith('.'):
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


def _standardize_path(path_str: str) -> str:
    path = Path("/vyper/" + path_str.lstrip('/')).resolve()
    try:
        path = path.relative_to("/vyper")
    except ValueError:
        raise JSONError(f"{path_str} - path exists outside base folder")
    return path.as_posix()


def get_input_dict_settings(input_dict: Dict) -> None:
    if 'settings' not in input_dict:
        return
    evm_version = input_dict['settings'].get('evmVersion', 'byzantium')
    if evm_version in ('homestead', 'tangerineWhistle', 'spuriousDragon'):
        raise JSONError("Vyper does not support pre-byzantium EVM versions")
    if evm_version not in ('byzantium', 'constantinople', 'petersburg'):
        raise JSONError(f"Unknown EVM version - '{evm_version}'")


def get_input_dict_contracts(input_dict: Dict) -> ContractCodes:
    contract_sources: ContractCodes = {}
    for path, value in input_dict['sources'].items():
        if 'urls' in value:
            raise JSONError(f"{path} - 'urls' is not a supported field, use 'content' instead")
        if 'content' not in value:
            raise JSONError(f"{path} missing required field - 'content'")
        if 'keccak256' in value:
            hash_ = value['keccak256'].lower()
            if hash_.startswith('0x'):
                hash_ = hash_[2:]
            if hash_ != keccak256(value['content'].encode('utf-8')):
                raise JSONError(
                    f"Calculated keccak of '{path}' does not match keccak given in input JSON"
                )
        key = _standardize_path(path)
        contract_sources[key] = value['content']
    return contract_sources


def get_input_dict_interfaces(input_dict: Dict) -> Dict:
    interface_sources = {}
    for path, value in input_dict.get('interfaces', {}).items():
        key = _standardize_path(path)
        if key.endswith(".json"):
            if 'abi' not in value:
                raise JSONError(f"Interface '{path}' must have 'abi' field")
            interface = {'type': "json", 'code': value['abi']}
        elif key.endswith(".vy"):
            if 'content' not in value:
                raise JSONError(f"Interface '{path}' must have 'content' field")
            interface = {'type': "vyper", 'code': value['content']}
        else:
            raise JSONError(f"Interface '{path}' must have suffix '.vy' or '.json'")
        key = key.rsplit('.', maxsplit=1)[0]
        interface_sources[key] = interface
    return interface_sources


def get_input_dict_output_formats(input_dict: Dict, contract_sources: ContractCodes) -> Dict:
    output_formats = {}
    for path, outputs in input_dict['outputSelection'].items():

        translate_map = {
            'abi': 'abi',
            'ast': 'ast_dict',
            'evm.methodIdentifiers': 'method_identifiers',
            'evm.bytecode.object': 'bytecode',
            'evm.bytecode.opcodes': 'opcodes',
            'evm.deployedBytecode.object': 'bytecode_runtime',
            'evm.deployedBytecode.opcodes': 'opcodes_runtime',
            'evm.deployedBytecode.sourceMap': 'source_map',
            'interface': 'interface',
            'ir': 'ir',
        }

        if isinstance(outputs, dict):
            # if outputs are given in solc json format, collapse them into a single list
            outputs = set(x for i in outputs.values() for x in i)
        else:
            outputs = set(outputs)

        for key in [i for i in ('evm', 'evm.bytecode', 'evm.deployedBytecode') if i in outputs]:
            outputs.remove(key)
            outputs.update([i for i in translate_map if i.startswith(key)])
        if '*' in outputs:
            outputs = list(translate_map.values())
        else:
            try:
                outputs = [translate_map[i] for i in outputs]
            except KeyError as e:
                raise JSONError(f"Invalid outputSelection - {e}")

        if path == "*":
            output_keys = list(contract_sources.keys())
        else:
            output_keys = [_standardize_path(path)]
            if output_keys[0] not in contract_sources:
                raise JSONError(f"outputSelection references unknown contract '{output_keys[0]}'")

        for key in output_keys:
            output_formats[key] = outputs

    return output_formats


def compile_from_input_dict(input_dict: Dict,
                            exc_handler: Callable,
                            root_folder: Union[str, None] = None) -> Tuple[Dict, Dict]:
    root_path = None
    if root_folder is not None:
        root_path = Path(root_folder).resolve()
        if not root_path.exists():
            raise FileNotFoundError(f"Invalid root path - '{root_path.as_posix()}' does not exist")

    if input_dict['language'] != "Vyper":
        raise JSONError(f"Invalid language '{input_dict['language']}' - Only Vyper is supported.")

    get_input_dict_settings(input_dict)

    contract_sources: ContractCodes = get_input_dict_contracts(input_dict)
    interface_sources = get_input_dict_interfaces(input_dict)
    output_formats = get_input_dict_output_formats(input_dict, contract_sources)
    interface_codes = get_interface_codes(root_path, contract_sources, interface_sources)

    compiler_data, warning_data = {}, {}
    warnings.simplefilter('always')
    for id_, key in enumerate(sorted(contract_sources)):
        with warnings.catch_warnings(record=True) as caught_warnings:
            data = vyper.compile_codes(
                {key: contract_sources[key]},
                output_formats[key],
                exc_handler=exc_handler,
                interface_codes=interface_codes[key],
                initial_id=id_
            )

            if 'errors' in data:
                return data, {}
            compiler_data[key] = data[key]
            if caught_warnings:
                warning_data[key] = caught_warnings

    return compiler_data, warning_data


def format_to_output_dict(compiler_data: Dict) -> Dict:
    output_dict: Dict = {
        'compiler': f"vyper-{vyper.__version__}",
        'contracts': {},
        'sources': {},
    }
    for id_, (path, data) in enumerate(compiler_data.items()):

        output_dict['sources'][path] = {'id': id_}
        if 'ast_dict' in data:
            output_dict['sources'][path]['ast'] = data['ast_dict']['ast']

        name = Path(path).stem
        output_dict['contracts'][path] = {name: {}}
        output_contracts = output_dict['contracts'][path][name]
        if 'abi' in data:
            output_contracts['abi'] = data['abi']
        if 'interface' in data:
            output_contracts['interface'] = data['interface']
        if 'ir' in data:
            output_contracts['ir'] = data['ir']
        if 'method_identifiers' in data:
            output_contracts['evm'] = {'methodIdentifiers': data['method_identifiers']}

        evm_keys = ('bytecode', 'opcodes')
        if next((i for i in evm_keys if i in data), False):
            evm = output_contracts.setdefault('evm', {}).setdefault('bytecode', {})
            if 'bytecode' in data:
                evm['object'] = data['bytecode']
            if 'opcodes' in data:
                evm['opcodes'] = data['opcodes']

        if next((i for i in evm_keys if i+'_runtime' in data), False) or 'source_map' in data:
            evm = output_contracts.setdefault('evm', {}).setdefault('deployedBytecode', {})
            if 'bytecode_runtime' in data:
                evm['object'] = data['bytecode_runtime']
            if 'opcodes_runtime' in data:
                evm['opcodes'] = data['opcodes_runtime']
            if 'source_map' in data:
                evm['sourceMap'] = data['source_map']['pc_pos_map_compressed']

    return output_dict


def compile_json(input_json: Union[Dict, str],
                 exc_handler: Callable,
                 root_path: Union[str, None] = None,
                 json_path: Union[str, None] = None) -> Dict:

    try:
        if isinstance(input_json, str):
            try:
                input_dict: Dict = json.loads(input_json)
            except json.decoder.JSONDecodeError as exc:
                new_exc = JSONError(str(exc), exc.lineno, exc.colno)
                return exc_handler(json_path, new_exc, "json")
        else:
            input_dict = input_json

        try:
            compiler_data, warn_data = compile_from_input_dict(input_dict, exc_handler, root_path)
            if 'errors' in compiler_data:
                return compiler_data
        except KeyError as exc:
            new_exc = JSONError(f"Input JSON missing required field: {str(exc)}")
            return exc_handler(json_path, new_exc, "json")
        except (FileNotFoundError, JSONError) as exc:
            return exc_handler(json_path, exc, "json")

        output_dict = format_to_output_dict(compiler_data)
        if warn_data:
            output_dict['errors'] = []
            for path, msg in ((k, x) for k, v in warn_data.items() for x in v):
                output_dict['errors'].append({
                    "type": msg.category.__name__,
                    "component": "compiler",
                    "severity": "warning",
                    "message": msg.message,
                    "sourceLocation": {'file': path}
                })
        return output_dict

    except Exception as exc:
        if hasattr(exc, '_exc_handler'):
            raise
        exc.lineno = sys.exc_info()[-1].tb_lineno  # type: ignore
        file_path = sys.exc_info()[-1].tb_frame.f_code.co_filename  # type: ignore
        return exc_handler(file_path, exc, "vyper")


def exc_handler_raises(file_path: Union[str, None],
                       exception: Exception,
                       component: str = "compiler") -> None:
    if file_path:
        print(f"Unhandled exception in '{file_path}':")
    exception._exc_handler = True  # type: ignore
    raise exception


def exc_handler_to_json(file_path: Union[str, None],
                        exception: Exception,
                        component: str = "compiler") -> Dict:
    err_dict: Dict = {
        "type": type(exception).__name__,
        "component": component,
        "severity": "error",
        "message": str(exception).strip('"'),
    }
    if hasattr(exception, 'message'):
        err_dict.update({
            'message': exception.message,  # type: ignore
            'formattedMessage': str(exception)
        })
    if file_path is not None:
        err_dict['sourceLocation'] = {'file': file_path}
        if getattr(exception, 'lineno', None) is not None:
            err_dict['sourceLocation'].update({
                'lineno': exception.lineno,  # type: ignore
                'col_offset': getattr(exception, 'col_offset', None),
            })
    return {'errors': [err_dict]}
