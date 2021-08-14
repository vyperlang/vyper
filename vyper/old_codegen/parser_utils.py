from decimal import Decimal, getcontext

from vyper import ast as vy_ast
from vyper.exceptions import (
    CompilerPanic,
    InvalidLiteral,
    StructureException,
    TypeCheckFailure,
    TypeMismatch,
)
from vyper.old_codegen.arg_clamps import int128_clamp
from vyper.old_codegen.lll_node import LLLnode
from vyper.old_codegen.types import (
    BaseType,
    ByteArrayLike,
    ByteArrayType,
    ListType,
    MappingType,
    StructType,
    TupleLike,
    TupleType,
    ceil32,
    get_size_of_type,
    has_dynamic_data,
    is_base_type,
)
from vyper.utils import GAS_IDENTITY, GAS_IDENTITYWORD, MemoryPositions

getcontext().prec = 78  # MAX_UINT256 < 1e78


def type_check_wrapper(fn):
    def _wrapped(*args, **kwargs):
        return_value = fn(*args, **kwargs)
        if return_value is None:
            raise TypeCheckFailure(f"{fn.__name__} did not return a value")
        return return_value

    return _wrapped


# Get a decimal number as a fraction with denominator multiple of 10
def get_number_as_fraction(expr, context):
    literal = Decimal(expr.value)
    sign, digits, exponent = literal.as_tuple()

    if exponent < -10:
        raise InvalidLiteral(
            f"`decimal` literal cannot have more than 10 decimal places: {literal}", expr
        )

    sign = -1 if sign == 1 else 1  # Positive Decimal has `sign` of 0, negative `sign` of 1
    # Decimal `digits` is a tuple of each digit, so convert to a regular integer
    top = int(Decimal((0, digits, 0)))
    top = sign * top * 10 ** (exponent if exponent > 0 else 0)  # Convert to a fixed point integer
    bottom = 1 if exponent > 0 else 10 ** abs(exponent)  # Make denominator a power of 10
    assert Decimal(top) / Decimal(bottom) == literal  # Sanity check

    # TODO: Would be best to raise >10 decimal place exception here
    #       (unless Decimal is used more widely)

    return expr.node_source_code, top, bottom


# cost per byte of the identity precompile
def _identity_gas_bound(num_bytes):
    return GAS_IDENTITY + GAS_IDENTITYWORD * (ceil32(num_bytes) // 32)


# Copy byte array word-for-word (including layout)
def make_byte_array_copier(destination, source, pos=None):
    if not isinstance(source.typ, ByteArrayLike):
        btype = "byte array" if isinstance(destination.typ, ByteArrayType) else "string"
        raise TypeMismatch(f"Can only set a {btype} to another {btype}", pos)
    if isinstance(source.typ, ByteArrayLike) and source.typ.maxlen > destination.typ.maxlen:
        raise TypeMismatch(
            f"Cannot cast from greater max-length {source.typ.maxlen} to shorter "
            f"max-length {destination.typ.maxlen}"
        )

    # stricter check for zeroing a byte array.
    if isinstance(source.typ, ByteArrayLike):
        if source.value is None and source.typ.maxlen != destination.typ.maxlen:
            raise TypeMismatch(
                f"Bad type for clearing bytes: expected {destination.typ}" f" but got {source.typ}"
            )

    # Special case: memory to memory
    if source.location == "memory" and destination.location == "memory":
        o = LLLnode.from_list(
            [
                "with",
                "_source",
                source,
                [
                    "with",
                    "_sz",
                    ["add", 32, ["mload", "_source"]],
                    ["assert", ["call", ["gas"], 4, 0, "_source", "_sz", destination, "_sz"]],
                ],
            ],  # noqa: E501
            typ=None,
            add_gas_estimate=_identity_gas_bound(source.typ.maxlen),
            annotation="Memory copy",
        )
        return o

    if source.value is None:
        pos_node = source
    else:
        pos_node = LLLnode.from_list("_pos", typ=source.typ, location=source.location)
    # Get the length
    if source.value is None:
        length = 1
    elif source.location == "memory":
        length = ["add", ["mload", "_pos"], 32]
    elif source.location == "storage":
        length = ["add", ["sload", "_pos"], 32]
        pos_node = LLLnode.from_list(pos_node, typ=source.typ, location=source.location,)
    else:
        raise CompilerPanic(f"Unsupported location: {source.location}")
    if destination.location == "storage":
        destination = LLLnode.from_list(
            destination, typ=destination.typ, location=destination.location,
        )
    # Maximum theoretical length
    max_length = 32 if source.value is None else source.typ.maxlen + 32
    return LLLnode.from_list(
        [
            "with",
            "_pos",
            0 if source.value is None else source,
            make_byte_slice_copier(destination, pos_node, length, max_length, pos=pos),
        ],
        typ=None,
    )


# Copy bytes
# Accepts 4 arguments:
# (i) an LLL node for the start position of the source
# (ii) an LLL node for the start position of the destination
# (iii) an LLL node for the length
# (iv) a constant for the max length
def make_byte_slice_copier(destination, source, length, max_length, pos=None):
    # Special case: memory to memory
    if source.location == "memory" and destination.location == "memory":
        return LLLnode.from_list(
            [
                "with",
                "_l",
                max_length,
                ["pop", ["call", ["gas"], 4, 0, source, "_l", destination, "_l"]],
            ],
            typ=None,
            annotation=f"copy byte slice dest: {str(destination)}",
            add_gas_estimate=_identity_gas_bound(max_length),
        )

    # special case: rhs is zero
    if source.value is None:

        if destination.location == "memory":
            return mzero(destination, max_length)

        else:
            loader = 0
    # Copy over data
    elif source.location == "memory":
        loader = ["mload", ["add", "_pos", ["mul", 32, ["mload", MemoryPositions.FREE_LOOP_INDEX]]]]
    elif source.location == "storage":
        loader = ["sload", ["add", "_pos", ["mload", MemoryPositions.FREE_LOOP_INDEX]]]
    elif source.location == "calldata":
        loader = [
            "calldataload",
            ["add", "_pos", ["mul", 32, ["mload", MemoryPositions.FREE_LOOP_INDEX]]],
        ]
    else:
        raise CompilerPanic(f"Unsupported location: {source.location}")
    # Where to paste it?
    if destination.location == "memory":
        setter = [
            "mstore",
            ["add", "_opos", ["mul", 32, ["mload", MemoryPositions.FREE_LOOP_INDEX]]],
            loader,
        ]
    elif destination.location == "storage":
        setter = ["sstore", ["add", "_opos", ["mload", MemoryPositions.FREE_LOOP_INDEX]], loader]
    else:
        raise CompilerPanic(f"Unsupported location: {destination.location}")
    # Check to see if we hit the length
    checker = [
        "if",
        ["gt", ["mul", 32, ["mload", MemoryPositions.FREE_LOOP_INDEX]], "_actual_len"],
        "break",
    ]
    # Make a loop to do the copying
    ipos = 0 if source.value is None else source
    o = [
        "with",
        "_pos",
        ipos,
        [
            "with",
            "_opos",
            destination,
            [
                "with",
                "_actual_len",
                length,
                [
                    "repeat",
                    MemoryPositions.FREE_LOOP_INDEX,
                    0,
                    (max_length + 31) // 32,
                    ["seq", checker, setter],
                ],
            ],
        ],
    ]
    return LLLnode.from_list(
        o, typ=None, annotation=f"copy byte slice src: {source} dst: {destination}", pos=pos,
    )


# Takes a <32 byte array as input, and outputs a number.
def byte_array_to_num(
    arg, expr, out_type, offset=32,
):
    if arg.location == "memory":
        lengetter = LLLnode.from_list(["mload", "_sub"], typ=BaseType("int256"))
        first_el_getter = LLLnode.from_list(["mload", ["add", 32, "_sub"]], typ=BaseType("int256"))
    elif arg.location == "storage":
        lengetter = LLLnode.from_list(["sload", "_sub"], typ=BaseType("int256"))
        first_el_getter = LLLnode.from_list(["sload", ["add", 1, "_sub"]], typ=BaseType("int256"))
    if out_type == "int128":
        result = int128_clamp(["div", "_el1", ["exp", 256, ["sub", 32, "_len"]]])
    elif out_type in ("int256", "uint256"):
        result = ["div", "_el1", ["exp", 256, ["sub", offset, "_len"]]]
    return LLLnode.from_list(
        [
            "with",
            "_sub",
            arg,
            [
                "with",
                "_el1",
                first_el_getter,
                ["with", "_len", ["clamp", 0, lengetter, 32], result],
            ],
        ],
        typ=BaseType(out_type),
        annotation=f"bytearray to number ({out_type})",
    )


def get_bytearray_length(arg):
    typ = BaseType("uint256")
    if arg.location == "memory":
        return LLLnode.from_list(["mload", arg], typ=typ)
    elif arg.location == "storage":
        return LLLnode.from_list(["sload", arg], typ=typ)
    elif arg.location == "calldata":
        return LLLnode.from_list(["calldataload", arg], typ=typ)
    raise CompilerPanic("unreachable", arg)  # pragma: no test


def getpos(node):
    return (
        node.lineno,
        node.col_offset,
        getattr(node, "end_lineno", None),
        getattr(node, "end_col_offset", None),
    )


# Take a value representing a memory or storage location, and descend down to
# an element or member variable
@type_check_wrapper
def add_variable_offset(parent, key, pos, array_bounds_check=True):
    typ, location = parent.typ, parent.location
    if isinstance(typ, TupleLike):
        if isinstance(typ, StructType):
            subtype = typ.members[key]
            attrs = list(typ.tuple_keys())
            index = attrs.index(key)
            annotation = key
        else:
            attrs = list(range(len(typ.members)))
            index = key
            annotation = None

        # generated by empty()
        if parent.value is None:
            return LLLnode.from_list(None, typ=subtype)

        if location == "storage":
            # for arrays and structs, calculate the storage slot by adding an offset
            # of [index value being accessed] * [size of each item within the sequence]
            offset = 0
            for i in range(index):
                offset += get_size_of_type(typ.members[attrs[i]])
            return LLLnode.from_list(["add", parent, offset], typ=subtype, location="storage",)
        elif location == "storage_prehashed":
            return LLLnode.from_list(
                ["add", parent, LLLnode.from_list(index, annotation=annotation)],
                typ=subtype,
                location="storage",
            )
        elif location in ("calldata", "memory"):
            offset = 0
            for i in range(index):
                offset += 32 * get_size_of_type(typ.members[attrs[i]])
            return LLLnode.from_list(
                ["add", offset, parent],
                typ=typ.members[key],
                location=location,
                annotation=annotation,
            )

    elif isinstance(typ, MappingType):

        sub = None
        if isinstance(key.typ, ByteArrayLike):
            if isinstance(typ.keytype, ByteArrayLike) and (typ.keytype.maxlen >= key.typ.maxlen):

                subtype = typ.valuetype
                if len(key.args[0].args) >= 3:  # handle bytes literal.
                    sub = LLLnode.from_list(
                        [
                            "seq",
                            key,
                            [
                                "sha3",
                                ["add", key.args[0].args[-1], 32],
                                ["mload", key.args[0].args[-1]],
                            ],
                        ]
                    )
                else:
                    value = key.args[0].value
                    if value == "add":
                        # special case, key is a bytes array within a tuple/struct
                        value = key.args[0]
                    sub = LLLnode.from_list(["sha3", ["add", value, 32], key])
        else:
            subtype = typ.valuetype
            sub = unwrap_location(key)

        if sub is not None and location == "storage":
            return LLLnode.from_list(["sha3_64", parent, sub], typ=subtype, location="storage")

    elif isinstance(typ, ListType) and is_base_type(key.typ, ("int128", "int256", "uint256")):
        subtype = typ.subtype

        if parent.value is None:
            return LLLnode.from_list(None, typ=subtype)

        k = unwrap_location(key)
        if not array_bounds_check:
            sub = k
        elif key.typ.is_literal:  # note: BaseType always has is_literal attr
            # perform the check at compile time and elide the runtime check.
            if key.value < 0 or key.value >= typ.count:
                return
            sub = k
        else:
            # this works, even for int128. for int128, since two's-complement
            # is used, if the index is negative, (unsigned) LT will interpret
            # it as a very large number, larger than any practical value for
            # an array index, and the clamp will throw an error.
            sub = ["uclamplt", k, typ.count]

        if location == "storage":
            # storage slot determined as [initial storage slot] + [index] * [size of base type]
            offset = get_size_of_type(subtype)
            return LLLnode.from_list(
                ["add", parent, ["mul", sub, offset]], typ=subtype, location="storage", pos=pos
            )
        elif location == "storage_prehashed":
            return LLLnode.from_list(["add", parent, sub], typ=subtype, location="storage", pos=pos)
        elif location in ("calldata", "memory"):
            offset = 32 * get_size_of_type(subtype)
            return LLLnode.from_list(
                ["add", ["mul", offset, sub], parent], typ=subtype, location=location, pos=pos
            )


# Unwrap location
def unwrap_location(orig):
    if orig.location == "memory":
        return LLLnode.from_list(["mload", orig], typ=orig.typ)
    elif orig.location == "storage":
        return LLLnode.from_list(["sload", orig], typ=orig.typ)
    elif orig.location == "calldata":
        return LLLnode.from_list(["calldataload", orig], typ=orig.typ)
    else:
        # handle None value inserted by `empty`
        if orig.value is None:
            return LLLnode.from_list(0, typ=orig.typ)
        return orig


# Pack function arguments for a call
@type_check_wrapper
def pack_arguments(signature, args, context, stmt_expr, is_external_call):
    pos = getpos(stmt_expr)
    setters = []
    staticarray_offset = 0

    maxlen = sum([get_size_of_type(arg.typ) for arg in signature.args]) * 32
    if is_external_call:
        maxlen += 32

    placeholder_typ = ByteArrayType(maxlen=maxlen)
    placeholder = context.new_internal_variable(placeholder_typ)
    if is_external_call:
        setters.append(["mstore", placeholder, signature.method_id])
        placeholder += 32

    if len(signature.args) != len(args):
        return

    # check for dynamic-length types
    dynamic_remaining = len([i for i in signature.args if isinstance(i.typ, ByteArrayLike)])
    needpos = bool(dynamic_remaining)

    for i, (arg, typ) in enumerate(zip(args, [arg.typ for arg in signature.args])):
        if isinstance(typ, BaseType):
            setters.append(
                make_setter(
                    LLLnode.from_list(placeholder + staticarray_offset + i * 32, typ=typ,),
                    arg,
                    "memory",
                    pos=pos,
                    in_function_call=True,
                )
            )

        elif isinstance(typ, ByteArrayLike):
            dynamic_remaining -= 1
            setters.append(["mstore", placeholder + staticarray_offset + i * 32, "_poz"])
            arg_copy = LLLnode.from_list("_s", typ=arg.typ, location=arg.location)
            target = LLLnode.from_list(["add", placeholder, "_poz"], typ=typ, location="memory",)
            pos_setter = "pass"

            # if `arg.value` is None, this is a call to `empty()`
            # if `arg.typ.maxlen` is 0, this is a literal "" or b""
            if arg.value is None or arg.typ.maxlen == 0:
                if dynamic_remaining:
                    # only adjust the dynamic pointer if this is not the last dynamic type
                    pos_setter = ["set", "_poz", ["add", "_poz", 64]]
                setters.append(["seq", mzero(target, 64), pos_setter])
            else:
                if dynamic_remaining:
                    pos_setter = [
                        "set",
                        "_poz",
                        ["add", 32, ["ceil32", ["add", "_poz", get_bytearray_length(arg_copy)]]],
                    ]
                setters.append(
                    [
                        "with",
                        "_s",
                        arg,
                        ["seq", make_byte_array_copier(target, arg_copy, pos), pos_setter],
                    ]
                )

        elif isinstance(typ, (StructType, ListType)):
            if has_dynamic_data(typ):
                return
            target = LLLnode.from_list(
                [placeholder + staticarray_offset + i * 32], typ=typ, location="memory",
            )
            setters.append(make_setter(target, arg, "memory", pos=pos))
            staticarray_offset += 32 * (get_size_of_type(typ) - 1)

        else:
            return

    if is_external_call:
        returner = [[placeholder - 4]]
        inargsize = placeholder_typ.maxlen - 28
    else:
        # internal call does not use a returner or adjust max length for signature
        returner = []
        inargsize = placeholder_typ.maxlen

    if needpos:
        return (
            LLLnode.from_list(
                ["with", "_poz", len(args) * 32 + staticarray_offset, ["seq"] + setters + returner],
                typ=placeholder_typ,
                location="memory",
            ),
            inargsize,
            placeholder,
        )
    else:
        return (
            LLLnode.from_list(["seq"] + setters + returner, typ=placeholder_typ, location="memory"),
            inargsize,
            placeholder,
        )


def _make_array_index_setter(target, target_token, pos, location, offset):
    if location == "memory" and isinstance(target.value, int):
        offset = target.value + 32 * get_size_of_type(target.typ.subtype) * offset
        return LLLnode.from_list([offset], typ=target.typ.subtype, location=location, pos=pos)
    else:
        return add_variable_offset(
            target_token,
            LLLnode.from_list(offset, typ="int256"),
            pos=pos,
            array_bounds_check=False,
        )


# Create an x=y statement, where the types may be compound
@type_check_wrapper
def make_setter(left, right, location, pos, in_function_call=False):
    # Basic types
    if isinstance(left.typ, BaseType):
        right = unwrap_location(right)
        if location == "storage":
            return LLLnode.from_list(["sstore", left, right], typ=None)
        elif location == "memory":
            return LLLnode.from_list(["mstore", left, right], typ=None)
    # Byte arrays
    elif isinstance(left.typ, ByteArrayLike):
        return make_byte_array_copier(left, right, pos)
    # Can't copy mappings
    elif isinstance(left.typ, MappingType):
        raise TypeMismatch("Cannot copy mappings; can only copy individual elements", pos)
    # Arrays
    elif isinstance(left.typ, ListType):
        # Cannot do something like [a, b, c] = [1, 2, 3]
        if left.value == "multi":
            return
        if not isinstance(right.typ, ListType):
            return
        if right.typ.count != left.typ.count:
            return

        left_token = LLLnode.from_list("_L", typ=left.typ, location=left.location)
        # If the right side is a literal
        if right.value in ["multi", "seq_unchecked"] and right.typ.is_literal:
            if right.value == "seq_unchecked":
                # when the LLL is `seq_unchecked`, this is a literal where one or
                # more values must be pre-processed to avoid memory corruption
                subs = right.args[:-1]
                right = right.args[-1]
            else:
                subs = []
            for i in range(left.typ.count):
                lhs_setter = _make_array_index_setter(left, left_token, pos, location, i)
                subs.append(make_setter(lhs_setter, right.args[i], location, pos=pos,))
            if left.location == "memory" and isinstance(left.value, int):
                return LLLnode.from_list(["seq"] + subs, typ=None)
            else:
                return LLLnode.from_list(["with", "_L", left, ["seq"] + subs], typ=None)
        elif right.value is None:
            if right.typ != left.typ:
                return
            if left.location == "memory":
                return mzero(left, 32 * get_size_of_type(left.typ))

            subs = []
            for i in range(left.typ.count):
                subs.append(
                    make_setter(
                        add_variable_offset(
                            left_token,
                            LLLnode.from_list(i, typ="int256"),
                            pos=pos,
                            array_bounds_check=False,
                        ),
                        LLLnode.from_list(None, typ=right.typ.subtype),
                        location,
                        pos=pos,
                    )
                )
            return LLLnode.from_list(["with", "_L", left, ["seq"] + subs], typ=None)
        # If the right side is a variable
        else:
            right_token = LLLnode.from_list("_R", typ=right.typ, location=right.location)
            subs = []
            for i in range(left.typ.count):
                lhs_setter = _make_array_index_setter(left, left_token, pos, left.location, i)
                rhs_setter = _make_array_index_setter(right, right_token, pos, right.location, i)
                subs.append(make_setter(lhs_setter, rhs_setter, location, pos=pos,))
            lll_node = ["seq"] + subs
            if right.location != "memory" or not isinstance(right.value, int):
                lll_node = ["with", "_R", right, lll_node]
            if left.location != "memory" or not isinstance(left.value, int):
                lll_node = ["with", "_L", left, lll_node]
            return LLLnode.from_list(lll_node, typ=None)
    # Structs
    elif isinstance(left.typ, TupleLike):
        if left.value == "multi" and isinstance(left.typ, StructType):
            return
        if right.value is not None:
            if not isinstance(right.typ, left.typ.__class__):
                return
            if isinstance(left.typ, StructType):
                for k in left.typ.members:
                    if k not in right.typ.members:
                        return
                for k in right.typ.members:
                    if k not in left.typ.members:
                        return
                if left.typ.name != right.typ.name:
                    return
            else:
                if len(left.typ.members) != len(right.typ.members):
                    return

        left_token = LLLnode.from_list("_L", typ=left.typ, location=left.location)
        keyz = left.typ.tuple_keys()

        # If the left side is a literal
        if left.value == "multi":
            locations = [arg.location for arg in left.args]
        else:
            locations = [location for _ in keyz]

        # If the right side is a literal
        if right.value == "multi":
            if len(right.args) != len(keyz):
                return
            # get the RHS arguments into a dict because
            # they are not guaranteed to be in the same order
            # the LHS keys.
            right_args = dict(zip(right.typ.tuple_keys(), right.args))
            subs = []
            for (key, loc) in zip(keyz, locations):
                subs.append(
                    make_setter(
                        add_variable_offset(left_token, key, pos=pos),
                        right_args[key],
                        loc,
                        pos=pos,
                    )
                )
            return LLLnode.from_list(["with", "_L", left, ["seq"] + subs], typ=None)
        # If the right side is a null
        elif right.value is None:
            if left.typ != right.typ:
                return

            if left.location == "memory":
                return mzero(left, 32 * get_size_of_type(left.typ))

            subs = []
            for key, loc in zip(keyz, locations):
                subs.append(
                    make_setter(
                        add_variable_offset(left_token, key, pos=pos),
                        LLLnode.from_list(None, typ=right.typ.members[key]),
                        loc,
                        pos=pos,
                    )
                )
            return LLLnode.from_list(["with", "_L", left, ["seq"] + subs], typ=None)
        # If tuple assign.
        elif isinstance(left.typ, TupleType) and isinstance(right.typ, TupleType):
            subs = []
            for var_arg in left.args:
                if var_arg.location == "calldata":
                    return

            right_token = LLLnode.from_list("_R", typ=right.typ, location=right.location)
            for left_arg, key, loc in zip(left.args, keyz, locations):
                subs.append(
                    make_setter(
                        left_arg, add_variable_offset(right_token, key, pos=pos), loc, pos=pos
                    )
                )

            return LLLnode.from_list(
                ["with", "_R", right, ["seq"] + subs], typ=None, annotation="Tuple assignment",
            )
        # If the left side is a variable i.e struct type
        else:
            subs = []
            right_token = LLLnode.from_list("_R", typ=right.typ, location=right.location)
            for typ, loc in zip(keyz, locations):
                subs.append(
                    make_setter(
                        add_variable_offset(left_token, typ, pos=pos),
                        add_variable_offset(right_token, typ, pos=pos),
                        loc,
                        pos=pos,
                    )
                )
            return LLLnode.from_list(
                ["with", "_L", left, ["with", "_R", right, ["seq"] + subs]], typ=None,
            )


def is_return_from_function(node):
    if isinstance(node, vy_ast.Expr) and node.get("value.func.id") == "selfdestruct":
        return True
    if isinstance(node, vy_ast.Return):
        return True
    elif isinstance(node, vy_ast.Raise):
        return True
    else:
        return False


def check_single_exit(fn_node):
    _check_return_body(fn_node, fn_node.body)
    for node in fn_node.get_descendants(vy_ast.If):
        _check_return_body(node, node.body)
        if node.orelse:
            _check_return_body(node, node.orelse)


def _check_return_body(node, node_list):
    return_count = len([n for n in node_list if is_return_from_function(n)])
    if return_count > 1:
        raise StructureException(
            "Too too many exit statements (return, raise or selfdestruct).", node
        )
    # Check for invalid code after returns.
    last_node_pos = len(node_list) - 1
    for idx, n in enumerate(node_list):
        if is_return_from_function(n) and idx < last_node_pos:
            # is not last statement in body.
            raise StructureException(
                "Exit statement with succeeding code (that will not execute).", node_list[idx + 1]
            )


def _return_check(node):
    if is_return_from_function(node):
        return True
    elif isinstance(node, list):
        return any(_return_check(stmt) for stmt in node)
    elif isinstance(node, vy_ast.If):
        if_body_check = _return_check(node.body)
        else_body_check = _return_check(node.orelse)
        if if_body_check and else_body_check:  # both side need to match.
            return True
        else:
            return False
    return False


def mzero(dst, nbytes):
    # calldatacopy from past-the-end gives zero bytes.
    # cf. YP H.2 (ops section) with CALLDATACOPY spec.
    return LLLnode.from_list(
        # calldatacopy mempos calldatapos len
        ["calldatacopy", dst, "calldatasize", nbytes],
        annotation="mzero",
    )


# zero pad a bytearray according to the ABI spec. The last word
# of the byte array needs to be right-padded with zeroes.
def zero_pad(bytez_placeholder):
    len_ = ["mload", bytez_placeholder]
    dst = ["add", ["add", bytez_placeholder, 32], "len"]
    # the runtime length of the data rounded up to nearest 32
    # from spec:
    #   the actual value of X as a byte sequence,
    #   followed by the *minimum* number of zero-bytes
    #   such that len(enc(X)) is a multiple of 32.
    num_zero_bytes = ["sub", ["ceil32", "len"], "len"]
    return LLLnode.from_list(
        ["with", "len", len_, ["with", "dst", dst, mzero("dst", num_zero_bytes)]],
        annotation="Zero pad",
    )
