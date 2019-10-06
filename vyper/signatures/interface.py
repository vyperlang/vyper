import copy
import importlib
from pathlib import (
    Path,
)
import pkgutil
from typing import (
    Sequence,
    Tuple,
)

from vyper import ast
from vyper.exceptions import (
    ParserException,
    StructureException,
)
import vyper.interfaces
from vyper.parser import (
    parser,
)
from vyper.parser.constants import (
    Constants,
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
from vyper.typing import (
    InterfaceImports,
    SourceCode,
)


# Populate built-in interfaces.
def get_builtin_interfaces():
    interface_names = [x.name for x in pkgutil.iter_modules(vyper.interfaces.__path__)]
    return {
        name: extract_sigs({
            'type': 'vyper',
            'code': importlib.import_module(
                f'vyper.interfaces.{name}',
            ).interface_code,
        })
        for name in interface_names
    }


def render_return(sig):
    if sig.output_type:
        return " -> " + str(sig.output_type)
    return ""


def abi_type_to_ast(atype):
    if atype in ('int128', 'uint256', 'bool', 'address', 'bytes32'):
        return ast.Name(id=atype)
    elif atype == 'decimal':
        return ast.Name(id='int128')
    elif atype == 'bytes':
        return ast.Subscript(
            value=ast.Name(id='bytes'),
            slice=ast.Index(256)
        )
    elif atype == 'string':
        return ast.Subscript(
            value=ast.Name(id='string'),
            slice=ast.Index(256)
        )
    else:
        raise ParserException(f'Type {atype} not supported by vyper.')


def mk_full_signature_from_json(abi):
    funcs = [func for func in abi if func['type'] == 'function']
    sigs = []

    for func in funcs:
        args = []
        returns = None
        for a in func['inputs']:
            arg = ast.arg(
                arg=a['name'],
                annotation=abi_type_to_ast(a['type']),
                lineno=0,
                col_offset=0
            )
            args.append(arg)

        if len(func['outputs']) == 1:
            returns = abi_type_to_ast(func['outputs'][0]['type'])
        elif len(func['outputs']) > 1:
            returns = ast.Tuple(
                elts=[
                    abi_type_to_ast(a['type'])
                    for a in func['outputs']
                ]
            )

        decorator_list = [ast.Name(id='public')]
        if func['constant']:
            decorator_list.append(ast.Name(id='constant'))
        if func['payable']:
            decorator_list.append(ast.Name(id='payable'))

        sig = FunctionSignature.from_definition(
            code=ast.FunctionDef(
                name=func['name'],
                args=ast.arguments(args=args),
                decorator_list=decorator_list,
                returns=returns,
            ),
            custom_units=set(),
            custom_structs=dict(),
            constants=Constants()
        )
        sigs.append(sig)
    return sigs


def extract_sigs(sig_code):
    if sig_code['type'] == 'vyper':
        interface_ast = parser.parse_to_ast(sig_code['code'])
        return sig_utils.mk_full_signature(
            [i for i in interface_ast if not isinstance(i, (ast.Import, ast.ImportFrom))],
            sig_formatter=lambda x, y: x
        )
    elif sig_code['type'] == 'json':
        return mk_full_signature_from_json(sig_code['code'])
    else:
        raise Exception(
            (f"Unknown interface signature type '{sig_code['type']}' supplied. "
             "'vyper' & 'json' are supported")
        )


def extract_interface_str(code, contract_name, interface_codes=None):
    sigs = sig_utils.mk_full_signature(
        parser.parse_to_ast(code),
        sig_formatter=lambda x, y: (x, y),
        interface_codes=interface_codes,
    )
    events = [sig for sig, _ in sigs if isinstance(sig, EventSignature)]
    functions = [sig for sig, _ in sigs if isinstance(sig, FunctionSignature)]
    out = ""
    # Print events.
    for idx, event in enumerate(events):
        if idx == 0:
            out += "# Events\n\n"
        event_args_str = ', '.join([arg.name + ': ' + str(arg.typ) for arg in event.args])
        out += f"{event.name}: event({{{event_args_str}}})\n"

    # Print functions.
    def render_decorator(sig):
        o = "\n"
        if sig.const:
            o += "@constant\n"
        if not sig.private:
            o += "@public\n"
        return o

    for idx, func in enumerate(functions):
        if idx == 0:
            out += "\n# Functions\n"
        if not func.private and func.name != '__init__':
            args = ", ".join([arg.name + ": " + str(arg.typ) for arg in func.args])
            out += f"{render_decorator(func)}def {func.name}({args}){render_return(func)}:\n    pass\n"  # noqa: E501
    out += "\n"

    return out


def extract_external_interface(code, contract_name, interface_codes=None):
    sigs = sig_utils.mk_full_signature(
        parser.parse_to_ast(code),
        sig_formatter=lambda x, y: (x, y),
        interface_codes=interface_codes,
    )
    functions = [sig for sig, _ in sigs if isinstance(sig, FunctionSignature)]
    cname = Path(contract_name).stem.capitalize()

    out = ""
    offset = 4 * " "
    for idx, func in enumerate(functions):
        if idx == 0:
            out += f"\n# External Contracts\ncontract {cname}:\n"
        if not func.private and func.name != '__init__':
            args = ", ".join([arg.name + ": " + str(arg.typ) for arg in func.args])
            func_type = "constant" if func.const else "modifying"
            out += offset + f"def {func.name}({args}){render_return(func)}: {func_type}\n"
    out += "\n"
    return out


def extract_file_interface_imports(code: SourceCode) -> InterfaceImports:
    ast_tree = parser.parse_to_ast(code)

    imports_dict: InterfaceImports = {}
    for item in ast_tree:
        if isinstance(item, ast.Import):
            for a_name in item.names:  # type: ignore
                if not a_name.asname:
                    raise StructureException(
                        'Interface statement requires an accompanying `as` statement.',
                        item,
                    )
                if a_name.asname in imports_dict:
                    raise StructureException(
                        f'Interface with alias {a_name.asname} already exists',
                        item,
                    )
                imports_dict[a_name.asname] = a_name.name.replace('.', '/')
        elif isinstance(item, ast.ImportFrom):
            for a_name in item.names:  # type: ignore
                if a_name.asname:
                    raise StructureException("From imports cannot use aliases", item)
            level = item.level  # type: ignore
            module = item.module or ""  # type: ignore
            if not level and module == 'vyper.interfaces':
                continue
            if level:
                base_path = f"{'.'*level}/{module.replace('.','/')}"
            else:
                base_path = module.replace('.', '/')
            for a_name in item.names:  # type: ignore
                if a_name.name in imports_dict:
                    raise StructureException(
                        f'Interface with name {a_name.name} already exists',
                        item,
                    )
                imports_dict[a_name.name] = f"{base_path}/{a_name.name}"

    return imports_dict


Conflict = Tuple[FunctionSignature, FunctionSignature]
Conflicts = Tuple[Conflict, ...]


def find_signature_conflicts(sigs: Sequence[FunctionSignature]) -> Conflicts:
    """
    Takes a sequence of function signature records and returns a tuple of
    pairs of signatures from that sequence that produce the same internal
    method id.
    """
    # Consider self-comparisons as having been seen by default (they will be
    # skipped)
    comparisons_seen = set([frozenset((sig.sig,)) for sig in sigs])
    conflicts = []

    for sig in sigs:
        method_id = sig.method_id

        for other_sig in sigs:
            comparison_id = frozenset((sig.sig, other_sig.sig))
            if comparison_id in comparisons_seen:
                continue  # Don't make redundant or useless comparisons

            other_method_id = other_sig.method_id
            if method_id == other_method_id:
                conflicts.append((sig, other_sig))

            comparisons_seen.add(comparison_id)

    return tuple(conflicts)


def check_valid_contract_interface(global_ctx, contract_sigs):
    public_func_sigs = [
        sig for sig in contract_sigs.values()
        if isinstance(sig, FunctionSignature) and not sig.private
    ]
    func_conflicts = find_signature_conflicts(public_func_sigs)

    if len(func_conflicts) > 0:
        sig_1, sig_2 = func_conflicts[0]

        raise StructureException(
            f'Methods {sig_1.sig} and {sig_2.sig} have conflicting IDs '
            f'(id {sig_1.method_id})',
            sig_1.func_ast_code,
        )

    if global_ctx._interface:
        funcs_left = global_ctx._interface.copy()

        for sig, func_sig in contract_sigs.items():
            if isinstance(func_sig, FunctionSignature):
                # Remove units, as inteface signatures should not enforce units.
                clean_sig_output_type = func_sig.output_type
                if func_sig.output_type:
                    clean_sig_output_type = copy.deepcopy(func_sig.output_type)
                    clean_sig_output_type.unit = {}
                if (
                    sig in funcs_left and  # noqa: W504
                    not func_sig.private and  # noqa: W504
                    funcs_left[sig].output_type == clean_sig_output_type
                ):
                    del funcs_left[sig]
            if isinstance(func_sig, EventSignature) and func_sig.sig in funcs_left:
                del funcs_left[func_sig.sig]

        if funcs_left:
            error_message = 'Contract does not comply to supplied Interface(s).\n'
            missing_functions = [
                str(func_sig)
                for sig_name, func_sig
                in funcs_left.items()
                if isinstance(func_sig, FunctionSignature)
            ]
            missing_events = [
                sig_name
                for sig_name, func_sig
                in funcs_left.items()
                if isinstance(func_sig, EventSignature)
            ]
            if missing_functions:
                err_join = "\n\t".join(missing_functions)
                error_message += f'Missing interface functions:\n\t{err_join}'
            if missing_events:
                err_join = "\n\t".join(missing_events)
                error_message += f'Missing interface events:\n\t{err_join}'
            raise StructureException(error_message)
