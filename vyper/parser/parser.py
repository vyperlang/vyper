from typing import (
    Any,
    List,
)

from vyper import ast
from vyper.ast_utils import (
    parse_to_ast,
)
from vyper.exceptions import (
    EventDeclarationException,
    FunctionDeclarationException,
    StructureException,
)
from vyper.parser.function_definitions import (
    is_default_func,
    is_initializer,
    parse_function,
)
from vyper.parser.global_context import (
    GlobalContext,
)
from vyper.parser.lll_node import (
    LLLnode,
)
from vyper.signatures import (
    sig_utils,
)
from vyper.signatures.event_signature import (
    EventSignature,
)
from vyper.signatures.function_signature import (
    FunctionSignature,
)
from vyper.signatures.interface import (
    check_valid_contract_interface,
)
from vyper.utils import (
    LOADED_LIMIT_MAP,
)

if not hasattr(ast, 'AnnAssign'):
    raise Exception("Requires python 3.6 or higher for annotation support")

# Header code
STORE_CALLDATA: List[Any] = ['seq', ['mstore', 28, ['calldataload', 0]]]
# Store limit constants at fixed addresses in memory.
LIMIT_MEMORY_SET: List[Any] = [
    ['mstore', pos, limit_size]
    for pos, limit_size in LOADED_LIMIT_MAP.items()
]
FUNC_INIT_LLL = LLLnode.from_list(
    STORE_CALLDATA + LIMIT_MEMORY_SET, typ=None
)
INIT_FUNC_INIT_LLL = LLLnode.from_list(
    ['seq'] + LIMIT_MEMORY_SET, typ=None
)


# Header code
INITIALIZER_LIST = ['seq', ['mstore', 28, ['calldataload', 0]]]
# Store limit constants at fixed addresses in memory.
INITIALIZER_LIST += [['mstore', pos, limit_size] for pos, limit_size in LOADED_LIMIT_MAP.items()]
INITIALIZER_LLL = LLLnode.from_list(INITIALIZER_LIST, typ=None)


def parse_events(sigs, global_ctx):
    for event in global_ctx._events:
        sigs[event.target.id] = EventSignature.from_declaration(event, global_ctx)
    return sigs


def parse_external_contracts(external_contracts, global_ctx):
    for _contractname in global_ctx._contracts:
        _contract_defs = global_ctx._contracts[_contractname]
        _defnames = [_def.name for _def in _contract_defs]
        contract = {}
        if len(set(_defnames)) < len(_contract_defs):
            raise FunctionDeclarationException(
                "Duplicate function name: %s" % (
                    [name for name in _defnames if _defnames.count(name) > 1][0]
                )
            )

        for _def in _contract_defs:
            constant = False
            # test for valid call type keyword.
            if len(_def.body) == 1 and \
               isinstance(_def.body[0], ast.Expr) and \
               isinstance(_def.body[0].value, ast.Name) and \
               _def.body[0].value.id in ('modifying', 'constant'):
                constant = True if _def.body[0].value.id == 'constant' else False
            else:
                raise StructureException('constant or modifying call type must be specified', _def)
            # Recognizes already-defined structs
            sig = FunctionSignature.from_definition(
                _def,
                contract_def=True,
                constant=constant,
                custom_structs=global_ctx._structs,
                constants=global_ctx._constants
            )
            contract[sig.name] = sig
        external_contracts[_contractname] = contract

    for interface_name, interface in global_ctx._interfaces.items():
        external_contracts[interface_name] = {
            sig.name: sig
            for sig in interface
            if isinstance(sig, FunctionSignature)
        }

    return external_contracts


def parse_other_functions(o,
                          otherfuncs,
                          sigs,
                          external_contracts,
                          origcode,
                          global_ctx,
                          default_function,
                          runtime_only):
    sub = ['seq', FUNC_INIT_LLL]
    add_gas = FUNC_INIT_LLL.gas

    for _def in otherfuncs:
        sub.append(
            parse_function(_def, {**{'self': sigs}, **external_contracts}, origcode, global_ctx)
        )
        sub[-1].total_gas += add_gas
        add_gas += 30
        for sig in sig_utils.generate_default_arg_sigs(_def, external_contracts, global_ctx):
            sig.gas = sub[-1].total_gas
            sigs[sig.sig] = sig

    # Add fallback function
    if default_function:
        default_func = parse_function(
            default_function[0],
            {**{'self': sigs}, **external_contracts},
            origcode,
            global_ctx,
        )
        sub.append(default_func)
    else:
        sub.append(LLLnode.from_list(['revert', 0, 0], typ=None, annotation='Default function'))
    if runtime_only:
        return sub
    else:
        o.append(['return', 0, ['lll', sub, 0]])
        return o


# Main python parse tree => LLL method
def parse_tree_to_lll(code, origcode, runtime_only=False, interface_codes=None):
    global_ctx = GlobalContext.get_global_context(code, interface_codes=interface_codes)
    _names_def = [_def.name for _def in global_ctx._defs]
    # Checks for duplicate function names
    if len(set(_names_def)) < len(_names_def):
        raise FunctionDeclarationException(
            "Duplicate function name: %s" % (
                [name for name in _names_def if _names_def.count(name) > 1][0]
            )
        )
    _names_events = [_event.target.id for _event in global_ctx._events]
    # Checks for duplicate event names
    if len(set(_names_events)) < len(_names_events):
        raise EventDeclarationException(
            "Duplicate event name: %s" % (
                [name for name in _names_events if _names_events.count(name) > 1][0]
            )
        )
    # Initialization function
    initfunc = [_def for _def in global_ctx._defs if is_initializer(_def)]
    # Default function
    defaultfunc = [_def for _def in global_ctx._defs if is_default_func(_def)]
    # Regular functions
    otherfuncs = [
        _def
        for _def
        in global_ctx._defs
        if not is_initializer(_def) and not is_default_func(_def)
    ]
    sigs = {}
    external_contracts = {}
    # Create the main statement
    o = ['seq']
    if global_ctx._events:
        sigs = parse_events(sigs, global_ctx)
    if global_ctx._contracts or global_ctx._interfaces:
        external_contracts = parse_external_contracts(external_contracts, global_ctx)
    # If there is an init func...
    if initfunc:
        o.append(INIT_FUNC_INIT_LLL)
        o.append(parse_function(
            initfunc[0],
            {**{'self': sigs}, **external_contracts},
            origcode,
            global_ctx,
        ))

    # If there are regular functions...
    if otherfuncs or defaultfunc:
        o = parse_other_functions(
            o, otherfuncs, sigs, external_contracts, origcode, global_ctx, defaultfunc, runtime_only
        )

    # Check if interface of contract is correct.
    check_valid_contract_interface(global_ctx, sigs)

    return LLLnode.from_list(o, typ=None)


def parse_to_lll(kode, runtime_only=False, interface_codes=None):
    code = parse_to_ast(kode)
    return parse_tree_to_lll(code, kode, runtime_only=runtime_only, interface_codes=interface_codes)
