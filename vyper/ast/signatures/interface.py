# TODO does this module not get imported?

import importlib
import pkgutil

import vyper.builtins.interfaces
from vyper import ast as vy_ast
from vyper.ast.signatures.function_signature import FunctionSignature
from vyper.codegen.global_context import GlobalContext
from vyper.exceptions import StructureException
from vyper.semantics.types import AddressT, BoolT, BytesM_T, DecimalT, IntegerT


# Populate built-in interfaces.
# NOTE: code duplication with vyper/semantics/analysis/module.py
def get_builtin_interfaces():
    interface_names = [x.name for x in pkgutil.iter_modules(vyper.builtins.interfaces.__path__)]
    return {
        name: extract_sigs(
            {
                "type": "vyper",
                "code": importlib.import_module(f"vyper.builtins.interfaces.{name}").interface_code,
            },
            name,
        )
        for name in interface_names
    }


_abi_type_map = {
    t.abi_type.selector_name(): t
    for t in (AddressT(), BoolT(), DecimalT()) + IntegerT.all() + BytesM_T.all()
}


# TODO: overlapping functionality with `type_from_abi`
def abi_type_to_ast(atype, expected_size):
    if atype in _abi_type_map:
        return vy_ast.Name(id=str(_abi_type_map[atype]))

    if atype in ("bytes", "string"):
        # expected_size is the maximum length for inputs, minimum length for outputs
        return vy_ast.Subscript(
            value=vy_ast.Name(id=atype.capitalize()),
            slice=vy_ast.Index(value=vy_ast.Int(value=expected_size)),
        )

    raise StructureException(f"Type {atype} not supported by vyper.")


# TODO: overlapping functionality with ContractFunction.from_abi
# Vyper defines a maximum length for bytes and string types, but Solidity does not.
# To maximize interoperability, we internally considers these types to have a
# a length of 1Mb (1024 * 1024 * 1 byte) for inputs, and 1 for outputs.
# Ths approach solves the issue because Vyper allows for an implicit casting
# from a lower length into a higher one.  (@iamdefinitelyahuman)
def mk_full_signature_from_json(abi):
    funcs = [func for func in abi if func["type"] == "function"]
    sigs = []

    for func in funcs:
        args = []
        returns = None
        for a in func["inputs"]:
            arg = vy_ast.arg(
                arg=a["name"],
                annotation=abi_type_to_ast(a["type"], 1048576),
                lineno=0,
                col_offset=0,
            )
            args.append(arg)

        if len(func["outputs"]) == 1:
            returns = abi_type_to_ast(func["outputs"][0]["type"], 1)
        elif len(func["outputs"]) > 1:
            returns = vy_ast.Tuple(
                elements=[abi_type_to_ast(a["type"], 1) for a in func["outputs"]]
            )

        decorator_list = [vy_ast.Name(id="external")]
        # Handle either constant/payable or stateMutability field
        if ("constant" in func and func["constant"]) or (
            "stateMutability" in func and func["stateMutability"] == "view"
        ):
            decorator_list.append(vy_ast.Name(id="view"))
        if ("payable" in func and func["payable"]) or (
            "stateMutability" in func and func["stateMutability"] == "payable"
        ):
            decorator_list.append(vy_ast.Name(id="payable"))

        sig = FunctionSignature.from_definition(
            vy_ast.FunctionDef(
                name=func["name"],
                args=vy_ast.arguments(args=args),
                decorator_list=decorator_list,
                returns=returns,
            ),
            GlobalContext(),  # dummy
            is_from_json=True,
        )
        sigs.append(sig)
    return sigs


def extract_sigs(sig_code, interface_name=None):
    if sig_code["type"] == "vyper":
        ast = vy_ast.parse_to_ast(sig_code["code"], contract_name=interface_name)
        return [s for s in ast if isinstance(s, vy_ast.FunctionDef)]
    elif sig_code["type"] == "json":
        return mk_full_signature_from_json(sig_code["code"])
    else:
        raise Exception(
            (
                f"Unknown interface signature type '{sig_code['type']}' supplied. "
                "'vyper' & 'json' are supported"
            )
        )
