#!/usr/bin/env python3

from copy import (
    deepcopy,
)

import pytest

import vyper
from vyper.cli.vyper_json import (
    TRANSLATE_MAP,
    compile_from_input_dict,
    exc_handler_raises,
    exc_handler_to_dict,
)
from vyper.exceptions import (
    JSONError,
    PythonSyntaxException,
    TypeMismatchException,
)

FOO_CODE = """
import contracts.bar as Bar

@public
def foo(a: address) -> bool:
    return Bar(a).bar(1)
"""

BAR_CODE = """
@public
def bar(a: uint256) -> bool:
    return True
"""

BAD_SYNTAX_CODE = """
def bar()>:
"""

BAD_COMPILER_CODE = """
@public
def oopsie(a: uint256) -> bool:
    return 42
"""

BAR_ABI = [{
    'name': 'bar',
    'outputs': [{'type': 'bool', 'name': 'out'}],
    'inputs': [{'type': 'uint256', 'name': 'a'}],
    'constant': False,
    'payable': False,
    'type': 'function',
    'gas': 313
}]

INPUT_JSON = {
    'language': "Vyper",
    'sources': {
        'contracts/foo.vy': {'content': FOO_CODE},
        'contracts/bar.vy': {'content': BAR_CODE},
    },
    'interfaces': {
        'contracts/bar.json': {'abi': BAR_ABI}
    },
    'outputSelection': {'*': ["*"]}
}


def test_root_folder_not_exists():
    with pytest.raises(FileNotFoundError):
        compile_from_input_dict({}, root_folder="/path/that/does/not/exist")


def test_wrong_language():
    with pytest.raises(JSONError):
        compile_from_input_dict({'language': "Solidity"})


def test_exc_handler_raises_syntax():
    input_json = deepcopy(INPUT_JSON)
    input_json['sources']['badcode.vy'] = {'content': BAD_SYNTAX_CODE}
    with pytest.raises(PythonSyntaxException):
        compile_from_input_dict(input_json, exc_handler_raises)


def test_exc_handler_to_dict_syntax():
    input_json = deepcopy(INPUT_JSON)
    input_json['sources']['badcode.vy'] = {'content': BAD_SYNTAX_CODE}
    result, _ = compile_from_input_dict(input_json, exc_handler_to_dict)
    assert 'errors' in result
    assert len(result['errors']) == 1
    error = result['errors'][0]
    assert error['component'] == "parser"
    assert error['type'] == "PythonSyntaxException"


def test_exc_handler_raises_compiler():
    input_json = deepcopy(INPUT_JSON)
    input_json['sources']['badcode.vy'] = {'content': BAD_COMPILER_CODE}
    with pytest.raises(TypeMismatchException):
        compile_from_input_dict(input_json, exc_handler_raises)


def test_exc_handler_to_dict_compiler():
    input_json = deepcopy(INPUT_JSON)
    input_json['sources']['badcode.vy'] = {'content': BAD_COMPILER_CODE}
    result, _ = compile_from_input_dict(input_json, exc_handler_to_dict)
    assert sorted(result.keys()) == ['compiler', 'errors']
    assert result['compiler'] == f"vyper-{vyper.__version__}"
    assert len(result['errors']) == 1
    error = result['errors'][0]
    assert error['component'] == "compiler"
    assert error['type'] == "TypeMismatchException"


def test_source_ids_increment():
    input_json = deepcopy(INPUT_JSON)
    input_json['outputSelection'] = {'*': ['evm.deployedBytecode.sourceMap']}
    result, _ = compile_from_input_dict(input_json)
    assert result['contracts/bar.vy']['source_map']['pc_pos_map_compressed'].startswith('-1:-1:0')
    assert result['contracts/foo.vy']['source_map']['pc_pos_map_compressed'].startswith('-1:-1:1')


def test_outputs():
    result, _ = compile_from_input_dict(INPUT_JSON)
    assert sorted(result.keys()) == ['contracts/bar.vy', 'contracts/foo.vy']
    assert sorted(result['contracts/bar.vy'].keys()) == sorted(TRANSLATE_MAP.values())
