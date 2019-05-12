from vyper import ast
from vyper.exceptions import (
    EventDeclarationException,
    InvalidTypeException,
    VariableDeclarationException,
)
from vyper.signatures.function_signature import (
    VariableRecord,
)
from vyper.types import (
    ByteArrayType,
    canonicalize_type,
    delete_unit_if_empty,
    get_size_of_type,
    print_unit,
    unit_from_type,
)
from vyper.utils import (
    bytes_to_int,
    ceil32,
    check_valid_varname,
    sha3,
)


# Event signature object
class EventSignature:
    def __init__(self, name, args, indexed_list, event_id, sig):
        self.name = name
        self.args = args
        self.indexed_list = indexed_list
        self.sig = sig
        self.event_id = event_id

    # Get a signature from an event declaration
    @classmethod
    def from_declaration(cls, code, global_ctx):
        name = code.target.id
        pos = 0

        check_valid_varname(
            name, global_ctx._custom_units, global_ctx._structs, global_ctx._constants,
            pos=code, error_prefix="Event name invalid. ", exc=EventDeclarationException
        )

        # Determine the arguments, expects something of the form def foo(arg1: num, arg2: num ...
        args = []
        indexed_list = []
        topics_count = 1
        if code.annotation.args:
            keys = code.annotation.args[0].keys
            values = code.annotation.args[0].values
            for i in range(len(keys)):
                typ = values[i]
                if not isinstance(keys[i], ast.Name):
                    raise EventDeclarationException(
                        'Invalid key type, expected a valid name.',
                        keys[i],
                    )
                if not isinstance(typ, (ast.Name, ast.Call, ast.Subscript)):
                    raise EventDeclarationException('Invalid event argument type.', typ)
                if isinstance(typ, ast.Call) and not isinstance(typ.func, ast.Name):
                    raise EventDeclarationException('Invalid event argument type', typ)
                arg = keys[i].id
                arg_item = keys[i]
                is_indexed = False

                # Check to see if argument is a topic
                if isinstance(typ, ast.Call) and typ.func.id == 'indexed':
                    typ = values[i].args[0]
                    indexed_list.append(True)
                    topics_count += 1
                    is_indexed = True
                else:
                    indexed_list.append(False)
                if isinstance(typ, ast.Subscript) and getattr(typ.value, 'id', None) == 'bytes' and typ.slice.value.n > 32 and is_indexed:  # noqa: E501
                    raise EventDeclarationException("Indexed arguments are limited to 32 bytes")
                if topics_count > 4:
                    raise EventDeclarationException(
                        "Maximum of 3 topics {} given".format(topics_count - 1),
                        arg,
                    )
                if not isinstance(arg, str):
                    raise VariableDeclarationException("Argument name invalid", arg)
                if not typ:
                    raise InvalidTypeException("Argument must have type", arg)
                check_valid_varname(
                    arg,
                    global_ctx._custom_units,
                    global_ctx._structs,
                    global_ctx._constants,
                    pos=arg_item,
                    error_prefix="Event argument name invalid or reserved.",
                )
                if arg in (x.name for x in args):
                    raise VariableDeclarationException(
                        "Duplicate function argument name: " + arg,
                        arg_item,
                    )
                # Can struct be logged?
                parsed_type = global_ctx.parse_type(typ, None)
                args.append(VariableRecord(arg, pos, parsed_type, False))
                if isinstance(parsed_type, ByteArrayType):
                    pos += ceil32(typ.slice.value.n)
                else:
                    pos += get_size_of_type(parsed_type) * 32
        sig = name + '(' + ','.join([canonicalize_type(arg.typ, indexed_list[pos]) for pos, arg in enumerate(args)]) + ')'  # noqa F812
        event_id = bytes_to_int(sha3(bytes(sig, 'utf-8')))
        return cls(name, args, indexed_list, event_id, sig)

    def to_abi_dict(self, custom_units_descriptions=None):
        abi_dict = {
            "name": self.name,
            "inputs": [{
                "type": canonicalize_type(arg.typ, self.indexed_list[pos]),
                "name": arg.name,
                "indexed": self.indexed_list[pos],
                "unit": print_unit(unit_from_type(arg.typ), custom_units_descriptions)
            } for pos, arg in enumerate(self.args)] if self.args else [],
            "anonymous": False,
            "type": "event"
        }

        for abi_input in abi_dict['inputs']:
            delete_unit_if_empty(abi_input)

        return abi_dict
