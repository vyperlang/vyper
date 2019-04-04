import copy
import importlib
import os
import pkgutil

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


# Populate built-in interfaces.
def get_builtin_interfaces():
    interface_names = [x.name for x in pkgutil.iter_modules(vyper.interfaces.__path__)]
    return {
        name: extract_sigs({
            'type': 'vyper',
            'code': importlib.import_module(
                'vyper.interfaces.{}'.format(name),
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
        raise ParserException('Type {} not supported by vyper.'.format(atype))


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
        return sig_utils.mk_full_signature(
            parser.parse_to_ast(sig_code['code']),
            sig_formatter=lambda x, y: x
        )
    elif sig_code['type'] == 'json':
        return mk_full_signature_from_json(sig_code['code'])
    else:
        raise Exception(
            ("Unknown interface signature type '{}' supplied. "
             "'vyper' & 'json' are supported").format(sig_code['type'])
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
        out += "{event_name}: event({{{args}}})\n".format(
            event_name=event.name,
            args=", ".join([arg.name + ": " + str(arg.typ) for arg in event.args])
        )

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
            out += "{decorator}def {name}({args}){ret}:\n    pass\n".format(
                decorator=render_decorator(func),
                name=func.name,
                args=", ".join([arg.name + ": " + str(arg.typ) for arg in func.args]),
                ret=render_return(func)
            )
    out += "\n"

    return out


def extract_external_interface(code, contract_name, interface_codes=None):
    sigs = sig_utils.mk_full_signature(
        parser.parse_to_ast(code),
        sig_formatter=lambda x, y: (x, y),
        interface_codes=interface_codes,
    )
    functions = [sig for sig, _ in sigs if isinstance(sig, FunctionSignature)]
    cname = os.path.basename(contract_name).split('.')[0].capitalize()

    out = ""
    offset = 4 * " "
    for idx, func in enumerate(functions):
        if idx == 0:
            out += "\n# External Contracts\ncontract %s:\n" % cname
        if not func.private and func.name != '__init__':
            out += offset + "def {name}({args}){ret}: {func_type}\n".format(
                name=func.name,
                args=", ".join([arg.name + ": " + str(arg.typ) for arg in func.args]),
                ret=render_return(func),
                func_type="constant" if func.const else "modifying",
            )
    out += "\n"
    return out


def extract_file_interface_imports(code):
    ast_tree = parser.parse_to_ast(code)
    imports_dict = {}
    for item in ast_tree:
        if isinstance(item, ast.Import):
            for a_name in item.names:
                if not a_name.asname:
                    raise StructureException(
                        'Interface statement requires an accompanying `as` statement.',
                        item,
                    )
                if a_name.asname in imports_dict:
                    raise StructureException(
                        'Interface with Alias {} already exists'.format(a_name.asname),
                        item,
                    )
                imports_dict[a_name.asname] = a_name.name
    return imports_dict


def check_valid_contract_interface(global_ctx, contract_sigs):

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
                error_message += 'Missing interface functions:\n\t{}'.format(
                    '\n\t'.join(missing_functions)
                )
            if missing_events:
                error_message += 'Missing interface events:\n\t{}'.format(
                    '\n\t'.join(missing_events)
                )
            raise StructureException(error_message)
