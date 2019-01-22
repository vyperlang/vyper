import ast
import os

import importlib
import pkgutil
import vyper.interfaces

from vyper.exceptions import StructureException
from vyper.parser import parser
from vyper.signatures.event_signature import EventSignature
from vyper.signatures.function_signature import FunctionSignature


# Populate built-in interfaces.
def get_builtin_interfaces():
    interface_names = [x.name for x in pkgutil.iter_modules(vyper.interfaces.__path__)]
    return {
        name: extract_sigs(importlib.import_module('vyper.interfaces.{}'.format(name)).interface_code)
        for name in interface_names
    }


def render_return(sig):
    if sig.output_type:
        return " -> " + str(sig.output_type)
    return ""


def extract_sigs(code):
    sigs = parser.mk_full_signature(parser.parse_to_ast(code), sig_formatter=lambda x, y: x)
    return sigs


def extract_interface_str(code, contract_name):
    sigs = parser.mk_full_signature(parser.parse_to_ast(code), sig_formatter=lambda x, y: (x, y))
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


def extract_external_interface(code, contract_name):
    sigs = parser.mk_full_signature(parser.parse_to_ast(code), sig_formatter=lambda x, y: (x, y))
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
                    raise StructureException('Interface statement requires an accompanying `as` statement.', item)
                if a_name.asname in imports_dict:
                    raise StructureException('Interface with Alias {} already exists'.format(a_name.asname), item)
                imports_dict[a_name.asname] = a_name.name
    return imports_dict
