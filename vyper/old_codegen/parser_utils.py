from decimal import Decimal, getcontext

from vyper import ast as vy_ast
from vyper.evm.opcodes import version_check
from vyper.exceptions import (
    CompilerPanic,
    InvalidLiteral,
    StructureException,
    TypeCheckFailure,
    TypeMismatch,
)
from vyper.old_codegen.arg_clamps import int128_clamp
from vyper.old_codegen.lll_node import Encoding, LLLnode
from vyper.old_codegen.types import (
    BaseType,
    ByteArrayLike,
    ListType,
    MappingType,
    StructType,
    TupleLike,
    TupleType,
    ceil32,
    get_size_of_type,
    is_base_type,
)
from vyper.utils import (
    GAS_CALLDATACOPY_WORD,
    GAS_CODECOPY_WORD,
    GAS_IDENTITY,
    GAS_IDENTITYWORD,
    MemoryPositions,
)

getcontext().prec = 78  # MAX_UINT256 < 1e78


def type_check_wrapper(fn):
    def _wrapped(*args, **kwargs):
        return_value = fn(*args, **kwargs)
        if return_value is None:
            raise TypeCheckFailure(f"{fn.__name__} {args} did not return a value")
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


def _calldatacopy_gas_bound(num_bytes):
    return GAS_CALLDATACOPY_WORD * ceil32(num_bytes) // 32


def _codecopy_gas_bound(num_bytes):
    return GAS_CODECOPY_WORD * ceil32(num_bytes) // 32


# Copy byte array word-for-word (including layout)
def make_byte_array_copier(destination, source, pos=None):
    if not isinstance(source.typ, ByteArrayLike):
        raise TypeMismatch(f"Cannot cast from {source.typ} to {destination.typ}", pos)
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
    # TODO: this should be handled by make_byte_slice_copier.
    if destination.location == "memory" and source.location in ("memory", "code", "calldata"):
        if source.location == "memory":
            # TODO turn this into an LLL macro: memorycopy
            copy_op = ["assert", ["call", ["gas"], 4, 0, "src", "sz", destination, "sz"]]
            gas_bound = _identity_gas_bound(source.typ.maxlen)
        elif source.location == "calldata":
            copy_op = ["calldatacopy", destination, "src", "sz"]
            gas_bound = _calldatacopy_gas_bound(source.typ.maxlen)
        elif source.location == "code":
            copy_op = ["codecopy", destination, "src", "sz"]
            gas_bound = _codecopy_gas_bound(source.typ.maxlen)
        _sz_lll = ["add", 32, [load_op(source.location), "src"]]
        o = LLLnode.from_list(
            ["with", "src", source, ["with", "sz", _sz_lll, copy_op]],
            typ=None,
            add_gas_estimate=gas_bound,
            annotation="copy bytestring to memory",
        )
        return o

    if source.value is None:
        pos_node = source
    else:
        pos_node = LLLnode.from_list("_pos", typ=source.typ, location=source.location)
    # Get the length
    if source.value is None:
        length = 1
    elif source.location in ("memory", "code", "calldata"):
        length = ["add", [load_op(source.location), "_pos"], 32]
    elif source.location == "storage":
        length = ["add", ["sload", "_pos"], 32]
        pos_node = LLLnode.from_list(pos_node, typ=source.typ, location=source.location,)
    else:
        raise CompilerPanic(f"Unsupported location: {source.location} to {destination.location}")
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
                max_length,  # CMC 20210917 shouldn't this just be length
                ["pop", ["call", ["gas"], 4, 0, source, "_l", destination, "_l"]],
            ],
            typ=None,
            annotation=f"copy byte slice dest: {str(destination)}",
            add_gas_estimate=_identity_gas_bound(max_length),
        )

    # special case: rhs is zero
    if source.value is None:

        if destination.location == "memory":
            # CMC 20210917 shouldn't this just be length
            return mzero(destination, max_length)

        else:
            loader = 0
    # Copy over data
    elif source.location in ("memory", "calldata", "code"):
        loader = [
            load_op(source.location),
            ["add", "_pos", ["mul", 32, ["mload", MemoryPositions.FREE_LOOP_INDEX]]],
        ]
    elif source.location == "storage":
        loader = ["sload", ["add", "_pos", ["mload", MemoryPositions.FREE_LOOP_INDEX]]]
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
    if arg.location == "storage":
        lengetter = LLLnode.from_list(["sload", "_sub"], typ=BaseType("int256"))
        first_el_getter = LLLnode.from_list(["sload", ["add", 1, "_sub"]], typ=BaseType("int256"))
    else:
        op = load_op(arg.location)
        lengetter = LLLnode.from_list([op, "_sub"], typ=BaseType("int256"))
        first_el_getter = LLLnode.from_list([op, ["add", 32, "_sub"]], typ=BaseType("int256"))

    if out_type == "int128":
        result = int128_clamp(["div", "_el1", ["exp", 256, ["sub", 32, "_len"]]])
    elif out_type in ("int256", "uint256"):
        result = ["div", "_el1", ["exp", 256, ["sub", offset, "_len"]]]
    # TODO decimal clamp?
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
    return LLLnode.from_list([load_op(arg.location), arg], typ=typ)


def getpos(node):
    return (
        node.lineno,
        node.col_offset,
        getattr(node, "end_lineno", None),
        getattr(node, "end_col_offset", None),
    )


def _add_ofst(loc, ofst):
    if isinstance(loc.value, int) and isinstance(ofst, int):
        ret = loc.value + ofst
    else:
        ret = ["add", loc, ofst]
    return LLLnode.from_list(ret, location=loc.location, encoding=loc.encoding)


# Take a value representing a memory or storage location, and descend down to
# an element or member variable
# This is analogous (but not necessarily equivalent to) getelementptr in LLVM.
# TODO refactor / streamline this code, especially the ABI decoding
@type_check_wrapper
def get_element_ptr(parent, key, pos, array_bounds_check=True):
    # TODO rethink this circular import
    from vyper.old_codegen.abi import abi_type_of

    typ, location = parent.typ, parent.location

    def _abi_helper(member_t, ofst, clamp=True):
        member_abi_t = abi_type_of(member_t)
        ofst_lll = _add_ofst(parent, ofst)

        if member_abi_t.is_dynamic():
            # double dereference, according to ABI spec
            # TODO optimize special case: first dynamic item
            # offset is statically known.
            ofst_lll = _add_ofst(parent, unwrap_location(ofst_lll))

        x = LLLnode.from_list(
            ["ofst"], typ=member_t, location=parent.location, annotation=f"&({typ}->{member_t})"
        )

        if clamp and _needs_clamp(member_t, parent.encoding):
            # special handling for unsanitized external data that need clamping
            # TODO optimize me. this results in a double dereference because
            # it returns a pointer and not a value. probably the best thing
            # is to move the clamp to make_setter
            ret = ["with", x, ofst_lll, ["seq", clamp_basetype(x), x]]
        else:
            ret = ofst_lll

        return LLLnode.from_list(
            ret,
            typ=member_t,
            location=parent.location,
            encoding=parent.encoding,
            pos=pos,
            # annotation=f"({parent.typ})[{key.typ}]",
        )

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

        if parent.value == "multi":
            assert parent.encoding != Encoding.ABI, "no abi-encoded literals"
            return parent.args[index]

        if parent.encoding in (Encoding.ABI, Encoding.JSON_ABI):
            if parent.location == "storage":
                raise CompilerPanic("storage variables should not be abi encoded")

            # parent_abi_t = abi_type_of(parent.typ)
            member_t = typ.members[attrs[index]]

            ofst = 0  # offset from parent start

            for i in range(index):
                member_abi_t = abi_type_of(typ.members[attrs[i]])
                ofst += member_abi_t.embedded_static_size()

            return _abi_helper(member_t, ofst)

        if location == "storage":
            # for arrays and structs, calculate the storage slot by adding an offset
            # of [index value being accessed] * [size of each item within the sequence]
            offset = 0
            for i in range(index):
                offset += get_size_of_type(typ.members[attrs[i]])
            return LLLnode.from_list(
                ["add", parent, offset], typ=subtype, location="storage", pos=pos,
            )

        elif location in ("calldata", "memory", "code"):
            offset = 0
            for i in range(index):
                offset += 32 * get_size_of_type(typ.members[attrs[i]])
            return LLLnode.from_list(
                _add_ofst(parent, offset),
                typ=typ.members[key],
                location=location,
                annotation=annotation,
                pos=pos,
            )

    elif isinstance(typ, ListType):
        if not is_base_type(key.typ, ("int128", "int256", "uint256")):
            return

        subtype = typ.subtype

        if parent.value is None:
            return LLLnode.from_list(None, typ=subtype)

        if parent.value == "multi":
            assert isinstance(key.value, int)
            return parent.args[key.value]

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

        if parent.encoding in (Encoding.ABI, Encoding.JSON_ABI):
            if parent.location == "storage":
                raise CompilerPanic("storage variables should not be abi encoded")

            member_t = typ.subtype
            member_abi_t = abi_type_of(member_t)

            if key.typ.is_literal:
                # TODO this constant folding in LLL optimizer
                ofst = k.value * member_abi_t.embedded_static_size()
            else:
                ofst = ["mul", k, member_abi_t.embedded_static_size()]

            return _abi_helper(member_t, ofst)

        if location == "storage":
            # storage slot determined as [initial storage slot] + [index] * [size of base type]
            offset = get_size_of_type(subtype)
            return LLLnode.from_list(
                ["add", parent, ["mul", sub, offset]], typ=subtype, location="storage", pos=pos
            )
        elif location in ("calldata", "memory", "code"):
            offset = 32 * get_size_of_type(subtype)
            return LLLnode.from_list(
                ["add", ["mul", offset, sub], parent], typ=subtype, location=location, pos=pos
            )

    elif isinstance(typ, MappingType):
        sub = None
        if isinstance(key.typ, ByteArrayLike):
            # CMC 20210916 pretty sure this is dead code. TODO double check
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


def load_op(location):
    if location == "memory":
        return "mload"
    if location == "storage":
        return "sload"
    if location == "calldata":
        return "calldataload"
    if location == "code":
        return "codeload"
    raise CompilerPanic(f"unreachable {location}")  # pragma: no test


# Unwrap location
def unwrap_location(orig):
    if orig.location in ("memory", "storage", "calldata", "code"):
        return LLLnode.from_list([load_op(orig.location), orig], typ=orig.typ)
    else:
        # CMC 20210909 TODO double check if this branch can be removed
        # handle None value inserted by `empty`
        if orig.value is None:
            return LLLnode.from_list(0, typ=orig.typ)
        return orig


# utility function, constructs an LLL tuple out of a list of LLL nodes
def lll_tuple_from_args(args):
    typ = TupleType([x.typ for x in args])
    return LLLnode.from_list(["multi"] + [x for x in args], typ=typ)


def _needs_external_call_wrap(lll_typ):
    # for calls to ABI conforming contracts.
    # according to the ABI spec, return types are ALWAYS tuples even
    # if only one element is being returned.
    # https://solidity.readthedocs.io/en/latest/abi-spec.html#function-selector-and-argument-encoding
    # "and the return values v_1, ..., v_k of f are encoded as
    #
    #    enc((v_1, ..., v_k))
    #    i.e. the values are combined into a tuple and encoded.
    # "
    # therefore, wrap it in a tuple if it's not already a tuple.
    # for example, `bytes` is returned as abi-encoded (bytes,)
    # and `(bytes,)` is returned as abi-encoded ((bytes,),)
    # In general `-> X` gets returned as (X,)
    # including structs. MyStruct is returned as abi-encoded (MyStruct,).
    # (Sorry this is so confusing. I didn't make these rules.)

    return not (isinstance(lll_typ, TupleType) and len(lll_typ.members) > 1)


def calculate_type_for_external_return(lll_typ):
    if _needs_external_call_wrap(lll_typ):
        return TupleType([lll_typ])
    return lll_typ


def wrap_value_for_external_return(lll_val):
    # used for LHS promotion
    if _needs_external_call_wrap(lll_val.typ):
        return lll_tuple_from_args([lll_val])
    else:
        return lll_val


def set_type_for_external_return(lll_val):
    # used for RHS promotion
    lll_val.typ = calculate_type_for_external_return(lll_val.typ)


# Create an x=y statement, where the types may be compound
@type_check_wrapper
def make_setter(left, right, pos):

    # Basic types
    if isinstance(left.typ, BaseType):
        right = unwrap_location(right)
        if left.location == "storage":
            return LLLnode.from_list(["sstore", left, right], typ=None)
        elif left.location == "memory":
            return LLLnode.from_list(["mstore", left, right], typ=None)

    # Byte arrays
    elif isinstance(left.typ, ByteArrayLike):
        return make_byte_array_copier(left, right, pos)

    # Arrays
    elif isinstance(left.typ, (ListType, TupleLike)):
        return _complex_make_setter(left, right, pos)


def _typecheck_list_make_setter(left, right):
    if left.value == "multi":
        # Cannot do something like [a, b, c] = [1, 2, 3]
        return False
    if not isinstance(right.typ, ListType):
        return False
    if right.typ.count != left.typ.count:
        return False
    return True


def _typecheck_tuple_make_setter(left, right):
    if right.value is not None:
        if not isinstance(right.typ, left.typ.__class__):
            return False
        if isinstance(left.typ, StructType):
            for k in left.typ.members:
                if k not in right.typ.members:
                    return False
            for k in right.typ.members:
                if k not in left.typ.members:
                    return False
            if left.typ.name != right.typ.name:
                return False
        else:
            if len(left.typ.members) != len(right.typ.members):
                return False
    return True


@type_check_wrapper
def _complex_make_setter(left, right, pos):
    if isinstance(left.typ, ListType):
        # CMC 20211002 this might not be necessary
        if not _typecheck_list_make_setter(left, right):
            return
        keys = [LLLnode.from_list(i, typ="uint256") for i in range(left.typ.count)]

    if isinstance(left.typ, TupleLike):
        # CMC 20211002 this might not be necessary
        if not _typecheck_tuple_make_setter(left, right):
            return
        keys = left.typ.tuple_keys()

    # if len(keyz) == 0:
    #    return LLLnode.from_list(["pass"])

    if right.value is None and left.location == "memory":
        # optimize memzero
        return mzero(left, 32 * get_size_of_type(left.typ))

    else:
        # general case
        if right.is_complex_lll:
            # create a reference to the R pointer
            _r = LLLnode.from_list(
                "_R", typ=right.typ, location=right.location, encoding=right.encoding
            )
        else:
            # optimization: don't cache, faster for ints
            _r = right

        rhs_items = [get_element_ptr(_r, k, pos=pos, array_bounds_check=False) for k in keys]

    if left.is_complex_lll:
        _l = LLLnode.from_list("_L", typ=left.typ, location=left.location, encoding=left.encoding)
    else:
        _l = left
    lhs_items = [get_element_ptr(_l, k, pos=pos, array_bounds_check=False) for k in keys]

    assert len(lhs_items) == len(rhs_items), "you've been bad!"
    ret = ["seq"] + [make_setter(l, r, pos) for (l, r) in zip(lhs_items, rhs_items)]
    if right.is_complex_lll:
        ret = ["with", "_R", right, ret]
    if left.is_complex_lll:
        ret = ["with", "_L", left, ret]
    return LLLnode.from_list(ret, typ=None)


# TODO move return checks to vyper/semantics/validation
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


# convenience rewrites for shr/sar/shl
def _shr(x, bits):
    if version_check(begin="constantinople"):
        return ["shr", bits, x]
    return ["div", x, ["exp", 2, bits]]


def _sar(x, bits):
    if version_check(begin="constantinople"):
        return ["sar", bits, x]

    # emulate for older arches. keep in mind note from EIP 145:
    # This is not equivalent to PUSH1 2 EXP SDIV, since it rounds
    # differently. See SDIV(-1, 2) == 0, while SAR(-1, 1) == -1.
    return ["sdiv", ["add", ["slt", x, 0], x], ["exp", 2, bits]]


def _needs_clamp(t, encoding):
    assert encoding in (Encoding.ABI, Encoding.JSON_ABI)
    if isinstance(t, ByteArrayLike):
        if encoding == Encoding.JSON_ABI:
            # don't have bytestring size bound from json, don't clamp
            return False
        return True
    if isinstance(t, BaseType) and t.typ not in ("int256", "uint256", "bytes32"):
        return True
    return False


# clampers for basetype
@type_check_wrapper
def clamp_basetype(lll_node):
    t = lll_node.typ
    if isinstance(t, ByteArrayLike):
        return ["assert", ["le", get_bytearray_length(lll_node), t.maxlen]]
    if isinstance(t, BaseType):
        lll_node = unwrap_location(lll_node)
        if t.typ in ("int128"):
            return int_clamp(lll_node, 128, signed=True)
        if t.typ in ("decimal"):
            return [
                "clamp",
                ["mload", MemoryPositions.MINDECIMAL],
                lll_node,
                ["mload", MemoryPositions.MAXDECIMAL],
            ]

        if t.typ in ("address",):
            return int_clamp(lll_node, 160)
        if t.typ in ("bool",):
            return int_clamp(lll_node, 1)
        if t.typ in ("int256", "uint256", "bytes32"):
            return ["pass"]  # special case, no clamp
    return  # raises


def int_clamp(lll_node, bits, signed=False):
    """Generalized clamper for integer types. Takes the number of bits,
       whether it's signed, and returns an LLL node which checks it is
       in bounds.
    """
    if bits >= 256:
        raise CompilerPanic("shouldn't clamp", lll_node)
    if signed:
        # example for bits==128:
        # if _val is in bounds,
        # _val >>> 127 == 0 for positive _val
        # _val >>> 127 == -1 for negative _val
        # -1 and 0 are the only numbers which are unchanged by sar,
        # so sar'ing (_val>>>127) one more bit should leave it unchanged.
        ret = ["with", "x", lll_node, ["assert", ["eq", _sar("x", bits - 1), _sar("x", bits)]]]
    else:
        ret = ["assert", ["iszero", _shr(lll_node, bits)]]

    return LLLnode.from_list(ret, annotation=f"int_clamp {lll_node.typ}")
