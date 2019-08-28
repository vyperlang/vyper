#!/usr/bin/env python3

import json
from pathlib import (
    Path,
)
from typing import (
    Any,
    Dict,
    Sequence,
    Union,
)

import vyper
from vyper.signatures.interface import (
    extract_file_interface_imports,
)
from vyper.typing import (
    ContractCodes,
    ContractPath,
)


def exc_handler(contract_path: ContractPath, exception: Exception) -> None:
    # TODO - return error message as JSON
    raise exception


def get_interface_codes(root_path: Union[Path, None],
                        contract_sources: ContractCodes,
                        interface_sources: ContractCodes) -> Any:
    interface_codes: Dict = {}
    interfaces: Dict = {}

    for file_path, code in contract_sources.items():
        interfaces[file_path] = {}

        interface_codes = extract_file_interface_imports(code)
        for interface_name, interface_path in interface_codes.items():

            keys = [
                Path(file_path).parent.joinpath(interface_path).as_posix()+".vy",
                interface_path+".vy"
            ]
            for sources in (interface_sources, contract_sources):
                key = next((i for i in keys if i in sources), None)
                if key:
                    interfaces[file_path][interface_name] = {
                        'type': 'vyper',
                        'code': sources[key]
                    }
                    break
            if key:
                continue

            if root_path is None:
                raise Exception(f'Imported interface "{interface_path}.vy" does not exist.')

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


def get_interface_file_path(base_paths: Sequence, import_path: str) -> Path:
    relative_path = Path(import_path)

    for path in base_paths:
        file_path = path.joinpath(relative_path)
        suffix = next((i for i in ('.vy', '.json') if file_path.with_suffix(i).exists()), None)
        if suffix:
            return file_path.with_suffix(suffix)
    raise Exception(
        f'Imported interface "{import_path}{{.vy,.json}}" does not exist.'
    )


def _standardize_path(path_str: str) -> str:
    path = Path("/vyper/" + path_str.lstrip('/')).resolve()
    try:
        path = path.relative_to("/vyper")
    except ValueError:
        raise ValueError(f"{path_str} - path exists outside base folder")
    return path.as_posix()


def compile_from_input_dict(input_dict, root_folder=None):
    root_path = None
    if root_folder is not None:
        root_path = Path(root_folder).resolve()
        if not root_path.exists():
            raise FileNotFoundError(f"Invalid root path - '{root_path.as_posix()}' does not exist")

    if input_dict['language'] != "Vyper":
        raise ValueError("Wrong language.")

    if 'settings' in input_dict:
        evm_version = input_dict['settings'].get('evmVersion', 'byzantium')
        if evm_version in ('homestead', 'tangerineWhistle', 'spuriousDragon'):
            raise ValueError("Vyper does not support pre-byzantium EVM versions")
        if evm_version not in ('byzantium', 'constantinople', 'petersburg'):
            raise ValueError(f"Unknown EVM version - '{evm_version}'")

    contract_sources: ContractCodes = {}
    for path, value in input_dict['sources'].items():
        # TODO support for URLs
        # TODO support for keccack
        key = _standardize_path(path)
        contract_sources[key] = value['content']

    interface_sources: ContractCodes = {}
    for path, value in input_dict.get('interfaces', {}).items():
        # TODO support for URLs
        # TODO support for keccack
        key = _standardize_path(path)
        interface_sources[key] = value['content']

    output_formats = {}
    for path, outputs in input_dict['outputSelection'].items():

        translate_map = {
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
                raise ValueError(f"Invalid outputSelection - {e}")

        if path == "*":
            output_keys = contract_sources.keys()
        else:
            output_keys = [_standardize_path(path)]
            if output_keys[0] not in contract_sources:
                raise KeyError("outputSelection references an unknown contract - '{}'")

        for key in output_keys:
            output_formats[key] = outputs

    interface_codes = get_interface_codes(root_path, contract_sources, interface_sources)
    return vyper.compile_codes(
        contract_sources,
        output_formats,
        exc_handler=exc_handler,
        interface_codes=interface_codes
    )


def format_to_output_dict(compiler_data):
    output_dict = {
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


def compile_json(input_json):
    input_dict = json.loads(input_json)
    compiler_data = compile_from_input_dict(input_dict)
    output_dict = format_to_output_dict(compiler_data)
    return json.dumps(output_dict, indent=2, default=str, sort_keys=True)
