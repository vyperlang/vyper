# TODO does this module not get imported?

import importlib
import pkgutil

import vyper.builtin_interfaces
from vyper import ast as vy_ast
from vyper.ast.signatures import sig_utils
from vyper.ast.signatures.function_signature import FunctionSignature
from vyper.exceptions import StructureException
from vyper.old_codegen.global_context import GlobalContext


# Populate built-in interfaces.
def get_builtin_interfaces():
    interface_names = [x.name for x in pkgutil.iter_modules(vyper.builtin_interfaces.__path__)]
    return {
        name: extract_sigs(
            {
                "type": "vyper",
                "code": importlib.import_module(f"vyper.builtin_interfaces.{name}",).interface_code,
            },
            name,
        )
        for name in interface_names
    }


def abi_type_to_ast(atype, expected_size):
    if atype in ("int128", "uint256", "bool", "address", "bytes32"):
        return vy_ast.Name(id=atype)
    elif atype == "fixed168x10":
        return vy_ast.Name(id="decimal")
    elif atype in ("bytes", "string"):
        # expected_size is the maximum length for inputs, minimum length for outputs
        return vy_ast.Subscript(
            value=vy_ast.Name(id=atype.capitalize()),
            slice=vy_ast.Index(value=vy_ast.Int(value=expected_size)),
        )
    else:
        raise StructureException(f"Type {atype} not supported by vyper.")


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
            code=vy_ast.FunctionDef(
                name=func["name"],
                args=vy_ast.arguments(args=args),
                decorator_list=decorator_list,
                returns=returns,
            ),
            custom_structs=dict(),
            is_from_json=True,
        )
        sigs.append(sig)
    return sigs


def extract_sigs(sig_code, interface_name=None):
    if sig_code["type"] == "vyper":
        interface_ast = [
            i
            for i in vy_ast.parse_to_ast(sig_code["code"], contract_name=interface_name)
            # all the nodes visited by ModuleNodeVisitor.
            if isinstance(
                i,
                (
                    vy_ast.FunctionDef,
                    vy_ast.EventDef,
                    vy_ast.StructDef,
                    vy_ast.InterfaceDef,
                    # parsing import statements at this stage
                    # causes issues with recursive imports
                    # vy_ast.Import,
                    # vy_ast.ImportFrom,
                ),
            )
            or (isinstance(i, vy_ast.AnnAssign) and i.target.id != "implements")
        ]
        global_ctx = GlobalContext.get_global_context(interface_ast)
        return sig_utils.mk_full_signature(global_ctx, sig_formatter=lambda x: x)
    elif sig_code["type"] == "json":
        return mk_full_signature_from_json(sig_code["code"])
    else:
        raise Exception(
            (
                f"Unknown interface signature type '{sig_code['type']}' supplied. "
                "'vyper' & 'json' are supported"
            )
        )
