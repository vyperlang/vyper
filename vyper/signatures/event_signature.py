from vyper import ast as vy_ast
from vyper.exceptions import EventDeclarationException, TypeCheckFailure
from vyper.signatures.function_signature import VariableRecord
from vyper.types import ByteArrayType, canonicalize_type, get_size_of_type
from vyper.utils import (
    bytes_to_int,
    ceil32,
    check_valid_varname,
    iterable_cast,
    keccak256,
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
    def from_declaration(cls, class_node, global_ctx):
        name = class_node.name
        pos = 0

        check_valid_varname(
            name,
            global_ctx._structs,
            pos=class_node,
            error_prefix="Event name invalid. ",
            exc=EventDeclarationException,
        )

        args = []
        indexed_list = []
        if len(class_node.body) != 1 or not isinstance(class_node.body[0], vy_ast.Pass):
            for node in class_node.body:
                arg_item = node.target
                arg = node.target.id
                typ = node.annotation

                if isinstance(typ, vy_ast.Call) and typ.get("func.id") == "indexed":
                    indexed_list.append(True)
                    typ = typ.args[0]
                else:
                    indexed_list.append(False)
                check_valid_varname(
                    arg,
                    global_ctx._structs,
                    pos=arg_item,
                    error_prefix="Event argument name invalid or reserved.",
                )
                if arg in (x.name for x in args):
                    raise TypeCheckFailure(f"Duplicate function argument name: {arg}")
                # Can struct be logged?
                parsed_type = global_ctx.parse_type(typ, None)
                args.append(VariableRecord(arg, pos, parsed_type, False))
                if isinstance(parsed_type, ByteArrayType):
                    pos += ceil32(typ.slice.value.n)
                else:
                    pos += get_size_of_type(parsed_type) * 32

        sig = (
            name
            + "("
            + ",".join(
                [canonicalize_type(arg.typ, indexed_list[pos]) for pos, arg in enumerate(args)]
            )
            + ")"
        )  # noqa F812
        event_id = bytes_to_int(keccak256(bytes(sig, "utf-8")))
        return cls(name, args, indexed_list, event_id, sig)

    @iterable_cast(dict)
    def to_abi_event_dict(self, arg, pos):
        yield "type", canonicalize_type(arg.typ, self.indexed_list[pos]),
        yield "name", arg.name,
        yield "indexed", self.indexed_list[pos],

    def to_abi_dict(self):
        abi_dict = {
            "name": self.name,
            "inputs": [self.to_abi_event_dict(arg, pos) for pos, arg in enumerate(self.args)]
            if self.args
            else [],
            "anonymous": False,
            "type": "event",
        }
        return abi_dict
