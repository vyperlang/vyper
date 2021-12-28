from decimal import Context, Decimal, setcontext

from vyper import ast as vy_ast
from vyper.evm.opcodes import version_check
from vyper.exceptions import (
    CompilerPanic,
    DecimalOverrideException,
    InvalidLiteral,
    StructureException,
    TypeCheckFailure,
    TypeMismatch,
)
from vyper.old_codegen.lll_node import Encoding, LLLnode
from vyper.old_codegen.types import (
    ArrayLike,
    BaseType,
    ByteArrayLike,
    DArrayType,
    MappingType,
    SArrayType,
    StructType,
    TupleLike,
    TupleType,
    ceil32,
    is_base_type,
    is_signed_num,
)
from vyper.utils import (
    GAS_CALLDATACOPY_WORD,
    GAS_CODECOPY_WORD,
    GAS_IDENTITY,
    GAS_IDENTITYWORD,
    MemoryPositions,
)


class DecimalContextOverride(Context):
    def __setattr__(self, name, value):
        if name == "prec":
            raise DecimalOverrideException("Overriding decimal precision disabled")
        super().__setattr__(name, value)


setcontext(DecimalContextOverride(prec=78))


# propagate revert message when calls to external contracts fail
def check_external_call(call_lll):
    copy_revertdata = ["returndatacopy", 0, 0, "returndatasize"]
    revert = ["revert", 0, "returndatasize"]

    propagate_revert_lll = ["seq", copy_revertdata, revert]
    return ["if", ["iszero", call_lll], propagate_revert_lll]


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
    assert isinstance(source.typ, ByteArrayLike)
    assert isinstance(destination.typ, ByteArrayLike)

    if source.typ.maxlen > destination.typ.maxlen:
        raise TypeMismatch(f"Cannot cast from {source.typ} to {destination.typ}")
    # stricter check for zeroing a byte array.
    if source.value is None and source.typ.maxlen != destination.typ.maxlen:
        raise TypeMismatch(
            f"Bad type for clearing bytes: expected {destination.typ} but got {source.typ}"
        )

    with source.cache_when_complex("_src") as (builder, src):
        if src.value is None:
            n_bytes = 32  # size in bytes of length word
            max_bytes = 32
        else:
            n_bytes = ["add", get_bytearray_length(src), 32]
            max_bytes = src.typ.memory_bytes_required

        return builder.resolve(copy_bytes(destination, src, n_bytes, max_bytes, pos=pos))


# Copy dynamic array word-for-word (including layout)
# TODO this code is very similar to make_byte_array_copier,
# try to refactor.
def make_dyn_array_copier(dst, src, pos=None):
    assert isinstance(src.typ, DArrayType)
    assert isinstance(dst.typ, DArrayType)

    if src.typ.count > dst.typ.count:
        raise TypeMismatch(f"Cannot cast from {src.typ} to {dst.typ}")

    # stricter check for zeroing
    if src.value is None and src.typ.count != dst.typ.count:
        raise CompilerPanic(f"Bad type for clearing bytes: expected {dst.typ} but got {src.typ}")

    with src.cache_when_complex("_src") as (builder, src):
        if src.value is None:
            n_bytes = 32  # size in bytes of length word
            max_bytes = 32
        else:
            element_size = src.typ.subtype.memory_bytes_required
            # 32 bytes + number of elements * size of element in bytes
            n_bytes = ["add", ["mul", get_dyn_array_count(src), element_size], 32]
            max_bytes = src.typ.memory_bytes_required

        return builder.resolve(copy_bytes(dst, src, n_bytes, max_bytes, pos=pos))


# Copy bytes
# Accepts 4 arguments:
# (i) an LLL node for the start position of the source
# (ii) an LLL node for the start position of the destination
# (iii) an LLL node for the length (in bytes)
# (iv) a constant for the max length (in bytes)
# NOTE: may pad to ceil32 of `length`! If you ask to copy 1 byte, it may
# copy an entire (32-byte) word, depending on the copy routine chosen.
def copy_bytes(dst, src, length, length_bound, pos=None):
    annotation = f"copy_bytes from {src} to {dst}"

    src = LLLnode.from_list(src)
    dst = LLLnode.from_list(dst)
    length = LLLnode.from_list(length)

    with src.cache_when_complex("_src") as (b1, src), length.cache_when_complex("len") as (
        b2,
        length,
    ), dst.cache_when_complex("dst") as (b3, dst):
        if dst.location == "memory" and src.location in ("memory", "calldata", "code"):
            # special cases: batch copy to memory
            if src.location == "memory":
                copy_op = ["staticcall", "gas", 4, src, length, dst, length]
                gas_bound = _identity_gas_bound(length_bound)
            elif src.location == "calldata":
                copy_op = ["calldatacopy", dst, src, length]
                gas_bound = _calldatacopy_gas_bound(length_bound)
            elif src.location == "code":
                copy_op = ["codecopy", dst, src, length]
                gas_bound = _codecopy_gas_bound(length_bound)

            ret = LLLnode.from_list(copy_op, annotation=annotation, add_gas_estimate=gas_bound)
            return b1.resolve(b2.resolve(b3.resolve(ret)))

        # general case, copy word-for-word
        # pseudocode for our approach (memory-storage as example):
        # for i in range(len, bound=MAX_LEN):
        #   sstore(_dst + i, mload(_src + i * 32))
        # TODO should use something like
        # for i in range(len, bound=MAX_LEN):
        #   _dst += 1
        #   _src += 32
        #   sstore(_dst, mload(_src))

        iptr = MemoryPositions.FREE_LOOP_INDEX
        # TODO change `repeat` so `i` is saved on stack
        i = ["mload", iptr]

        # special case: rhs is zero
        # CMC 20211211 this branch seems like dead code.
        if src.value is None:

            if dst.location == "memory":
                # CMC 20210917 shouldn't this just be length
                return mzero(dst, length_bound)

            else:
                loader = 0

        elif src.location in ("memory", "calldata", "code"):
            loader = [load_op(src.location), ["add", src, ["mul", 32, i]]]
        elif src.location == "storage":
            loader = [load_op(src.location), ["add", src, i]]
        else:
            raise CompilerPanic(f"Unsupported location: {src.location}")

        if dst.location == "memory":
            setter = ["mstore", ["add", dst, ["mul", 32, i]], loader]
        elif dst.location == "storage":
            setter = ["sstore", ["add", dst, i], loader]
        else:
            raise CompilerPanic(f"Unsupported location: {dst.location}")

        n = ["div", ["ceil32", length], 32]
        n_bound = ceil32(length_bound) // 32
        # TODO change `repeat` opcode so that `i` is on stack instead
        # of in memory
        main_loop = ["repeat", iptr, 0, n, n_bound, setter]

        return b1.resolve(
            b2.resolve(b3.resolve(LLLnode.from_list(main_loop, annotation=annotation, pos=pos)))
        )


# get the number of bytes at runtime
def get_bytearray_length(arg):
    typ = BaseType("uint256")
    return LLLnode.from_list([load_op(arg.location), arg], typ=typ)


# get the number of elements at runtime
def get_dyn_array_count(arg):
    typ = BaseType("uint256")
    return LLLnode.from_list([load_op(arg.location), arg], typ=typ)


def getpos(node):
    return (
        node.lineno,
        node.col_offset,
        getattr(node, "end_lineno", None),
        getattr(node, "end_col_offset", None),
    )


def add_ofst(loc, ofst):
    if isinstance(loc.value, int) and isinstance(ofst, int):
        ret = loc.value + ofst
    else:
        ret = ["add", loc, ofst]
    return LLLnode.from_list(ret, location=loc.location, encoding=loc.encoding)


# Resolve pointer locations for ABI-encoded data
def _getelemptr_abi_helper(parent, member_t, ofst, pos=None, clamp=True):
    # TODO circular import!
    from vyper.old_codegen.abi import abi_type_of

    member_abi_t = abi_type_of(member_t)
    ofst_lll = add_ofst(parent, ofst)

    if member_abi_t.is_dynamic():
        # double dereference, according to ABI spec
        # TODO optimize special case: first dynamic item
        # offset is statically known.
        ofst_lll = add_ofst(parent, unwrap_location(ofst_lll))

    return LLLnode.from_list(
        ofst_lll,
        typ=member_t,
        location=parent.location,
        encoding=parent.encoding,
        pos=pos,
        # annotation=f"({parent.typ})[{key.typ}]",
    )


# TODO simplify this code, especially the ABI decoding
def _get_element_ptr_tuplelike(parent, key, pos):
    # TODO circular import!
    from vyper.old_codegen.abi import abi_type_of

    typ = parent.typ
    assert isinstance(typ, TupleLike)

    if isinstance(typ, StructType):
        assert isinstance(key, str)
        subtype = typ.members[key]
        attrs = list(typ.tuple_keys())
        index = attrs.index(key)
        annotation = key
    else:
        assert isinstance(key, int)
        subtype = typ.members[key]
        attrs = list(range(len(typ.members)))
        index = key
        annotation = None

    # generated by empty()
    if parent.value is None:
        return LLLnode.from_list(None, typ=subtype)

    if parent.value == "multi":
        assert parent.encoding != Encoding.ABI, "no abi-encoded literals"
        return parent.args[index]

    ofst = 0  # offset from parent start

    if parent.encoding in (Encoding.ABI, Encoding.JSON_ABI):
        if parent.location == "storage":
            raise CompilerPanic("storage variables should not be abi encoded")

        # parent_abi_t = abi_type_of(parent.typ)
        member_t = typ.members[attrs[index]]

        for i in range(index):
            member_abi_t = abi_type_of(typ.members[attrs[i]])
            ofst += member_abi_t.embedded_static_size()

        return _getelemptr_abi_helper(parent, member_t, ofst, pos)

    if parent.location == "storage":
        for i in range(index):
            ofst += typ.members[attrs[i]].storage_size_in_words
    elif parent.location in ("calldata", "memory", "code"):
        for i in range(index):
            ofst += typ.members[attrs[i]].memory_bytes_required
    else:
        raise CompilerPanic("bad location {parent.location}")

    return LLLnode.from_list(
        add_ofst(parent, ofst),
        typ=subtype,
        location=parent.location,
        encoding=parent.encoding,
        annotation=annotation,
        pos=pos,
    )


# TODO simplify this code, especially the ABI decoding
def _get_element_ptr_array(parent, key, pos, array_bounds_check):
    # TODO circular import!
    from vyper.old_codegen.abi import abi_type_of

    assert isinstance(parent.typ, ArrayLike)

    # TODO allow other integer types
    if not is_base_type(key.typ, ("int128", "int256", "uint256")):
        return

    subtype = parent.typ.subtype

    if parent.value is None:
        return LLLnode.from_list(None, typ=subtype)

    if parent.value == "multi":
        assert isinstance(key.value, int)
        assert isinstance(parent.typ, SArrayType), "list literals should be SArrayType"
        return parent.args[key.value]

    ix = unwrap_location(key)

    if key.typ.is_literal and isinstance(parent.typ, SArrayType):
        # perform the check at compile time and elide the runtime check.
        # TODO make this an optimization on clamp ops
        if key.value < 0 or key.value >= parent.typ.count:
            return  # TypeMismatch

    elif array_bounds_check:
        clamp = "clamplt" if is_signed_num(key.typ) else "uclamplt"
        is_darray = isinstance(parent.typ, DArrayType)
        bound = get_dyn_array_count(parent) if is_darray else parent.typ.count
        ix = LLLnode.from_list([clamp, ix, bound], typ=ix.typ)

    if parent.encoding in (Encoding.ABI, Encoding.JSON_ABI):
        if parent.location == "storage":
            raise CompilerPanic("storage variables should not be abi encoded")

        member_t = parent.typ.subtype
        member_abi_t = abi_type_of(member_t)

        if isinstance(ix.value, int):
            # TODO this constant folding in LLL optimizer
            ofst = ix.value * member_abi_t.embedded_static_size()
        else:
            ofst = ["mul", ix, member_abi_t.embedded_static_size()]

        return _getelemptr_abi_helper(parent, member_t, ofst, pos)

    if parent.location == "storage":
        element_size = subtype.storage_size_in_words
    elif parent.location in ("calldata", "memory", "code"):
        element_size = subtype.memory_bytes_required

    if isinstance(ix.value, int):
        ofst = ix.value * element_size
    else:
        ofst = ["mul", ix, element_size]

    return LLLnode.from_list(add_ofst(parent, ofst), typ=subtype, location=parent.location, pos=pos)


def _get_element_ptr_mapping(parent, key, pos):
    assert isinstance(parent.typ, MappingType)
    subtype = parent.typ.valuetype
    key = unwrap_location(key)

    if key is None or parent.location != "storage":
        raise CompilerPanic("bad dereference on mapping {parent}[{sub}]")

    return LLLnode.from_list(["sha3_64", parent, key], typ=subtype, location="storage")


# Take a value representing a memory or storage location, and descend down to
# an element or member variable
# This is analogous (but not necessarily equivalent to) getelementptr in LLVM.
@type_check_wrapper
def get_element_ptr(parent, key, pos, array_bounds_check=True):
    typ = parent.typ

    if isinstance(typ, TupleLike):
        return _get_element_ptr_tuplelike(parent, key, pos)

    if isinstance(typ, MappingType):
        return _get_element_ptr_mapping(parent, key, pos)

    if isinstance(typ, ArrayLike):
        return _get_element_ptr_array(parent, key, pos, array_bounds_check)

    raise CompilerPanic("get_element_ptr cannot be called on {typ}")


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
        enc = right.encoding  # unwrap_location butchers encoding
        right = unwrap_location(right)
        # TODO rethink/streamline the clamp_basetype logic
        if _needs_clamp(right.typ, enc):
            right = clamp_basetype(right)

        if left.location == "storage":
            return LLLnode.from_list(["sstore", left, right], typ=None)
        elif left.location == "memory":
            return LLLnode.from_list(["mstore", left, right], typ=None)

    # Byte arrays
    elif isinstance(left.typ, ByteArrayLike):
        # TODO rethink/streamline the clamp_basetype logic
        if _needs_clamp(right.typ, right.encoding):
            _val = LLLnode("val", location=right.location, typ=right.typ)
            copier = make_byte_array_copier(left, _val, pos)
            ret = ["with", _val, right, ["seq", clamp_bytestring(_val), copier]]
        else:
            ret = make_byte_array_copier(left, right, pos)

        return LLLnode.from_list(ret)

    elif isinstance(left.typ, DArrayType):
        if not _typecheck_list_make_setter(left, right):
            return
        if isinstance(right.typ, SArrayType):
            # e.g. x: DynArray[uint256, 1] = [1]
            return _complex_make_setter(left, right, pos)
        # TODO rethink/streamline the clamp_basetype logic
        if _needs_clamp(right.typ, right.encoding):
            _val = LLLnode("val", location=right.location, typ=right.typ)
            copier = make_dyn_array_copier(left, _val, pos)
            ret = ["with", _val, right, ["seq", clamp_dyn_array(_val), copier]]
        else:
            ret = make_dyn_array_copier(left, right, pos)

        return LLLnode.from_list(ret)

    # Arrays
    elif isinstance(left.typ, (SArrayType, TupleLike)):
        return _complex_make_setter(left, right, pos)


def _typecheck_list_make_setter(left, right):
    if left.value == "multi":
        # Cannot do something like [a, b, c] = [1, 2, 3]
        return False
    if isinstance(left, SArrayType):
        if not (left.typ == right.typ and left.typ.count == right.typ.count):
            return False
    if isinstance(left, DArrayType):
        if not (
            isinstance(right, (DArrayType, SArrayType))
            and left.typ.count >= right.typ.count
            and left.typ.subtyp == right.typ.subtyp
        ):
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
    if isinstance(left.typ, ArrayLike):
        # CMC 20211002 this might not be necessary
        if not _typecheck_list_make_setter(left, right):
            return
        # right.typ.count is not a typo, handles dyn array -> static array
        ixs = range(right.typ.count)
        keys = [LLLnode.from_list(i, typ="uint256") for i in ixs]

    if isinstance(left.typ, TupleLike):
        if not _typecheck_tuple_make_setter(left, right):
            return
        keys = left.typ.tuple_keys()

    # if len(keyz) == 0:
    #    return LLLnode.from_list(["pass"])

    if right.value is None and left.location == "memory":
        # optimize memzero
        return mzero(left, left.typ.memory_bytes_required)

    # general case
    # TODO use copy_bytes when the generated code is above a certain size
    with left.cache_when_complex("_L") as (b1, left), right.cache_when_complex("_R") as (b2, right):

        ret = ["seq"]
        for k in keys:
            _l = get_element_ptr(left, k, pos=pos, array_bounds_check=False)
            _r = get_element_ptr(right, k, pos=pos, array_bounds_check=False)
            ret.append(make_setter(_l, _r, pos))

        return b1.resolve(b2.resolve(LLLnode.from_list(ret)))


def ensure_in_memory(lll_var, context, pos=None):
    """Ensure a variable is in memory. This is useful for functions
    which expect to operate on memory variables.
    """
    if lll_var.location == "memory":
        return lll_var

    typ = lll_var.typ
    buf = LLLnode.from_list(context.new_internal_variable(typ), typ=typ, location="memory")
    do_copy = make_setter(buf, lll_var, pos=pos)

    return LLLnode.from_list(["seq", do_copy, buf], typ=typ, location="memory")


def eval_seq(lll_node):
    """Tries to find the "return" value of a `seq` statement, in order so
    that the value can be known without possibly evaluating side effects
    """
    if lll_node.value in ("seq", "with") and len(lll_node.args) > 0:
        return eval_seq(lll_node.args[-1])
    if isinstance(lll_node.value, int):
        return LLLnode.from_list(lll_node)
    return None


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
def shr(x, bits):
    if version_check(begin="constantinople"):
        return ["shr", bits, x]
    return ["div", x, ["exp", 2, bits]]


def sar(x, bits):
    if version_check(begin="constantinople"):
        return ["sar", bits, x]

    # emulate for older arches. keep in mind note from EIP 145:
    # "This is not equivalent to PUSH1 2 EXP SDIV, since it rounds
    # differently. See SDIV(-1, 2) == 0, while SAR(-1, 1) == -1."
    return ["sdiv", ["add", ["slt", x, 0], x], ["exp", 2, bits]]


def _needs_clamp(t, encoding):
    if encoding not in (Encoding.ABI, Encoding.JSON_ABI):
        return False
    if isinstance(t, (ByteArrayLike, DArrayType)):
        if encoding == Encoding.JSON_ABI:
            # don't have bytestring size bound from json, don't clamp
            return False
        return True
    if isinstance(t, BaseType) and t.typ not in ("int256", "uint256", "bytes32"):
        return True
    return False


@type_check_wrapper
def clamp_bytestring(lll_node):
    t = lll_node.typ
    if not isinstance(t, ByteArrayLike):
        return  # raises
    return ["assert", ["le", get_bytearray_length(lll_node), t.maxlen]]


def clamp_dyn_array(lll_node):
    t = lll_node.typ
    assert isinstance(t, DArrayType)
    return ["assert", ["le", get_dyn_array_count(lll_node), t.count]]


# clampers for basetype
@type_check_wrapper
def clamp_basetype(lll_node):
    t = lll_node.typ
    if not isinstance(t, BaseType):
        return  # raises

    # copy of the input
    lll_node = unwrap_location(lll_node)

    if t.typ in ("int128"):
        return int_clamp(lll_node, 128, signed=True)
    if t.typ == "uint8":
        return int_clamp(lll_node, 8)
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
        return lll_node  # special case, no clamp.

    return  # raises


def int_clamp(lll_node, bits, signed=False):
    """Generalized clamper for integer types. Takes the number of bits,
    whether it's signed, and returns an LLL node which checks it is
    in bounds. (Consumers should use clamp_basetype instead which uses
    type-based dispatch and is a little safer.)
    """
    if bits >= 256:
        raise CompilerPanic(f"invalid clamp: {bits}>=256 ({lll_node})")
    if signed:
        # example for bits==128:
        # if _val is in bounds,
        # _val >>> 127 == 0 for positive _val
        # _val >>> 127 == -1 for negative _val
        # -1 and 0 are the only numbers which are unchanged by sar,
        # so sar'ing (_val>>>127) one more bit should leave it unchanged.
        assertion = ["assert", ["eq", sar("val", bits - 1), sar("val", bits)]]
    else:
        assertion = ["assert", ["iszero", shr("val", bits)]]

    ret = ["with", "val", lll_node, ["seq", assertion, "val"]]

    return LLLnode.from_list(ret, annotation=f"int_clamp {lll_node.typ}")
