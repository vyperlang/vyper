import ast

from vyper.types import (
    get_size_of_type,
    canonicalize_type,
    parse_type,
    ByteArrayType
)
from vyper.utils import (
    sha3,
    is_varname_valid,
    bytes_to_int,
    ceil32
)
from vyper.signatures.function_signature import VariableRecord
from vyper.exceptions import (
    InvalidTypeException,
    VariableDeclarationException,
    EventDeclarationException
)


# Event signature object
class EventSignature():
    def __init__(self, name, args, indexed_list, event_id, sig):
        self.name = name
        self.args = args
        self.indexed_list = indexed_list
        self.sig = sig
        self.event_id = event_id

    # Get a signature from an event declaration
    @classmethod
    def from_declaration(cls, code, custom_units=None):
        name = code.target.id
        pos = 0

        if not is_varname_valid(name, custom_units=custom_units):
            raise EventDeclarationException("Event name invalid: " + name)
        # Determine the arguments, expects something of the form def foo(arg1: num, arg2: num ...
        args = []
        indexed_list = []
        topics_count = 1
        if code.annotation.args:
            keys = code.annotation.args[0].keys
            values = code.annotation.args[0].values
            for i in range(len(keys)):
                typ = values[i]
                arg = keys[i].id
                is_indexed = False
                # Check to see if argument is a topic
                if isinstance(typ, ast.Call) and typ.func.id == 'indexed':
                    typ = values[i].args[0]
                    indexed_list.append(True)
                    topics_count += 1
                    is_indexed = True
                else:
                    indexed_list.append(False)
                if isinstance(typ, ast.Subscript) and getattr(typ.value, 'id', None) == 'bytes' and typ.slice.value.n > 32 and is_indexed:
                    raise EventDeclarationException("Indexed arguments are limited to 32 bytes")
                if topics_count > 4:
                    raise EventDeclarationException("Maximum of 3 topics {} given".format(topics_count - 1), arg)
                if not isinstance(arg, str):
                    raise VariableDeclarationException("Argument name invalid", arg)
                if not typ:
                    raise InvalidTypeException("Argument must have type", arg)
                if not is_varname_valid(arg, custom_units):
                    raise VariableDeclarationException("Argument name invalid or reserved: " + arg, arg)
                if arg in (x.name for x in args):
                    raise VariableDeclarationException("Duplicate function argument name: " + arg, arg)
                parsed_type = parse_type(typ, None, custom_units=custom_units)
                args.append(VariableRecord(arg, pos, parsed_type, False))
                if isinstance(parsed_type, ByteArrayType):
                    pos += ceil32(typ.slice.value.n)
                else:
                    pos += get_size_of_type(parsed_type) * 32
        sig = name + '(' + ','.join([canonicalize_type(arg.typ, indexed_list[pos]) for pos, arg in enumerate(args)]) + ')'  # noqa F812
        event_id = bytes_to_int(sha3(bytes(sig, 'utf-8')))
        return cls(name, args, indexed_list, event_id, sig)

    def to_abi_dict(self):
        return {
            "name": self.name,
            "inputs": [{"type": canonicalize_type(arg.typ, self.indexed_list[pos]), "name": arg.name, "indexed": self.indexed_list[pos]} for pos, arg in enumerate(self.args)] if self.args else [],
            "anonymous": False,
            "type": "event"
        }
