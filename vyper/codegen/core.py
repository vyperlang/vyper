from decimal import Context, setcontext

from vyper import ast as vy_ast
from vyper.codegen.lll_node import Encoding, LLLnode
from vyper.codegen.types import (
    DYNAMIC_ARRAY_OVERHEAD,
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
    is_bytes_m_type,
    is_integer_type,
)
from vyper.evm.opcodes import version_check
from vyper.exceptions import (
    CompilerPanic,
    DecimalOverrideException,
    StructureException,
    TypeCheckFailure,
    TypeMismatch,
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


# cost per byte of the identity precompile
def _identity_gas_bound(num_bytes):
    return GAS_IDENTITY + GAS_IDENTITYWORD * (ceil32(num_bytes) // 32)


def _calldatacopy_gas_bound(num_bytes):
    return GAS_CALLDATACOPY_WORD * ceil32(num_bytes) // 32


def _codecopy_gas_bound(num_bytes):
    return GAS_CODECOPY_WORD * ceil32(num_bytes) // 32


# Copy byte array word-for-word (including layout)
def make_byte_array_copier(dst, src, pos=None):
    assert isinstance(src.typ, ByteArrayLike)
    assert isinstance(dst.typ, ByteArrayLike)

    if src.typ.maxlen > dst.typ.maxlen:
        raise TypeMismatch(f"Cannot cast from {src.typ} to {dst.typ}")
    # stricter check for zeroing a byte array.
    if src.value == "~empty" and src.typ.maxlen != dst.typ.maxlen:
        raise TypeMismatch(
            f"Bad type for clearing bytes: expected {dst.typ} but got {src.typ}"
        )  # pragma: notest

    if src.value == "~empty":
        # set length word to 0.
        return LLLnode.from_list([store_op(dst.location), dst, 0], pos=pos)

    with src.cache_when_complex("src") as (builder, src):
        n_bytes = ["add", get_bytearray_length(src), 32]
        max_bytes = src.typ.memory_bytes_required

        return builder.resolve(copy_bytes(dst, src, n_bytes, max_bytes, pos=pos))


# TODO maybe move me to types.py
def wordsize(location):
    if location in ("memory", "calldata", "data", "immutables"):
        return 32
    if location == "storage":
        return 1
    raise CompilerPanic(f"invalid location {location}")  # pragma: notest


# TODO refactor: add similar fn for dyn_arrays
def bytes_data_ptr(ptr):
    if ptr.location is None:
        raise CompilerPanic("tried to modify non-pointer type")
    assert isinstance(ptr.typ, ByteArrayLike)
    return add_ofst(ptr, wordsize(ptr.location))


def _dynarray_make_setter(dst, src, pos=None):
    assert isinstance(src.typ, DArrayType)
    assert isinstance(dst.typ, DArrayType)

    if src.value == "~empty":
        return LLLnode.from_list([store_op(dst.location), dst, 0], pos=pos)

    if src.value == "multi":
        ret = ["seq"]
        # handle literals

        # write the length word
        store_length = [store_op(dst.location), dst, len(src.args)]
        ann = None
        if src.annotation is not None:
            ann = f"len({src.annotation})"
        store_length = LLLnode.from_list(store_length, annotation=ann)
        ret.append(store_length)

        n_items = len(src.args)
        for i in range(n_items):
            k = LLLnode.from_list(i, typ="uint256")
            dst_i = get_element_ptr(dst, k, pos=pos, array_bounds_check=False)
            src_i = get_element_ptr(src, k, pos=pos, array_bounds_check=False)
            ret.append(make_setter(dst_i, src_i, pos))

        return ret

    with src.cache_when_complex("darray_src") as (b1, src):

        # for ABI-encoded dynamic data, we must loop to unpack, since
        # the layout does not match our memory layout
        should_loop = (
            src.encoding in (Encoding.ABI, Encoding.JSON_ABI)
            and src.typ.subtype.abi_type.is_dynamic()
        )

        # if the subtype is dynamic, there might be a lot of
        # unused space inside of each element. for instance
        # DynArray[DynArray[uint256, 100], 5] where all the child
        # arrays are empty - for this case, we recursively call
        # into make_setter instead of straight bytes copy
        # TODO we can make this heuristic more precise, e.g.
        # loop when subtype.is_dynamic AND location == storage
        # OR array_size <= /bound where loop is cheaper than memcpy/
        should_loop |= src.typ.subtype.abi_type.is_dynamic()
        should_loop |= _needs_clamp(src.typ.subtype, src.encoding)

        if should_loop:
            uint = BaseType("uint256")

            # note: name clobbering for the ix is OK because
            # we never reach outside our level of nesting
            i = LLLnode.from_list(_freshname("copy_darray_ix"), typ=uint)

            loop_body = make_setter(
                get_element_ptr(dst, i, array_bounds_check=False, pos=pos),
                get_element_ptr(src, i, array_bounds_check=False, pos=pos),
                pos=pos,
            )
            loop_body.annotation = f"{dst}[i] = {src}[i]"

            with get_dyn_array_count(src).cache_when_complex("darray_count") as (b2, len_):
                store_len = [store_op(dst.location), dst, len_]
                loop = ["repeat", i, 0, len_, src.typ.count, loop_body]

                return b1.resolve(b2.resolve(["seq", store_len, loop]))

        element_size = src.typ.subtype.memory_bytes_required
        # 32 bytes + number of elements * size of element in bytes
        n_bytes = ["add", _mul(get_dyn_array_count(src), element_size), 32]
        max_bytes = src.typ.memory_bytes_required

        return b1.resolve(copy_bytes(dst, src, n_bytes, max_bytes, pos=pos))


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

    with src.cache_when_complex("src") as (b1, src), length.cache_when_complex(
        "copy_word_count"
    ) as (b2, length,), dst.cache_when_complex("dst") as (b3, dst):

        # fast code for common case where num bytes is small
        # TODO expand this for more cases where num words is less than ~8
        if length_bound <= 32:
            copy_op = [store_op(dst.location), dst, [load_op(src.location), src]]
            ret = LLLnode.from_list(copy_op, annotation=annotation)
            return b1.resolve(b2.resolve(b3.resolve(ret)))

        if dst.location == "memory" and src.location in ("memory", "calldata", "data"):
            # special cases: batch copy to memory
            # TODO: iloadbytes
            if src.location == "memory":
                copy_op = ["staticcall", "gas", 4, src, length, dst, length]
                gas_bound = _identity_gas_bound(length_bound)
            elif src.location == "calldata":
                copy_op = ["calldatacopy", dst, src, length]
                gas_bound = _calldatacopy_gas_bound(length_bound)
            elif src.location == "data":
                copy_op = ["dloadbytes", dst, src, length]
                # note: dloadbytes compiles to CODECOPY
                gas_bound = _codecopy_gas_bound(length_bound)

            ret = LLLnode.from_list(copy_op, annotation=annotation, add_gas_estimate=gas_bound)
            return b1.resolve(b2.resolve(b3.resolve(ret)))

        if dst.location == "immutables" and src.location in ("memory", "data"):
            # TODO istorebytes-from-mem, istorebytes-from-calldata(?)
            # compile to identity, CODECOPY respectively.
            pass

        # general case, copy word-for-word
        # pseudocode for our approach (memory-storage as example):
        # for i in range(len, bound=MAX_LEN):
        #   sstore(_dst + i, mload(src + i * 32))
        # TODO should use something like
        # for i in range(len, bound=MAX_LEN):
        #   _dst += 1
        #   src += 32
        #   sstore(_dst, mload(src))

        i = LLLnode.from_list(_freshname("copy_bytes_ix"), typ="uint256")

        if src.location in ("memory", "calldata", "data", "immutables"):
            loader = [load_op(src.location), ["add", src, _mul(32, i)]]
        elif src.location == "storage":
            loader = [load_op(src.location), ["add", src, i]]
        else:
            raise CompilerPanic(f"Unsupported location: {src.location}")  # pragma: notest

        if dst.location in ("memory", "immutables"):
            setter = [store_op(dst.location), ["add", dst, _mul(32, i)], loader]
        elif dst.location == "storage":
            setter = ["sstore", ["add", dst, i], loader]
        else:
            raise CompilerPanic(f"Unsupported location: {dst.location}")  # pragma: notest

        n = ["div", ["ceil32", length], 32]
        n_bound = ceil32(length_bound) // 32

        main_loop = ["repeat", i, 0, n, n_bound, setter]

        return b1.resolve(
            b2.resolve(b3.resolve(LLLnode.from_list(main_loop, annotation=annotation, pos=pos)))
        )


# get the number of bytes at runtime
def get_bytearray_length(arg):
    typ = BaseType("uint256")
    return LLLnode.from_list([load_op(arg.location), arg], typ=typ)


# get the number of elements at runtime
def get_dyn_array_count(arg):
    assert isinstance(arg.typ, DArrayType)

    typ = BaseType("uint256")

    if arg.value == "multi":
        return LLLnode.from_list(len(arg.args), typ=typ)

    if arg.value == "~empty":
        # empty(DynArray[])
        return LLLnode.from_list(0, typ=typ)

    return LLLnode.from_list([load_op(arg.location), arg], typ=typ)


def append_dyn_array(darray_node, elem_node, pos=None):
    assert isinstance(darray_node.typ, DArrayType)

    assert darray_node.typ.count > 0, "jerk boy u r out"

    ret = ["seq"]
    with darray_node.cache_when_complex("darray") as (b1, darray_node):
        len_ = get_dyn_array_count(darray_node)
        with len_.cache_when_complex("old_darray_len") as (b2, len_):
            ret.append(["assert", ["le", len_, darray_node.typ.count - 1]])
            ret.append([store_op(darray_node.location), darray_node, ["add", len_, 1]])
            # NOTE: typechecks elem_node
            # NOTE skip array bounds check bc we already asserted len two lines up
            ret.append(
                make_setter(
                    get_element_ptr(darray_node, len_, array_bounds_check=False, pos=pos),
                    elem_node,
                    pos=pos,
                )
            )
            return LLLnode.from_list(b1.resolve(b2.resolve(ret)), pos=pos)


def pop_dyn_array(darray_node, return_popped_item, pos=None):
    assert isinstance(darray_node.typ, DArrayType)
    ret = ["seq"]
    with darray_node.cache_when_complex("darray") as (b1, darray_node):
        old_len = ["clamp_nonzero", get_dyn_array_count(darray_node)]
        new_len = LLLnode.from_list(["sub", old_len, 1], typ="uint256")

        with new_len.cache_when_complex("new_len") as (b2, new_len):
            ret.append([store_op(darray_node.location), darray_node, new_len])

            # NOTE skip array bounds check bc we already asserted len two lines up
            if return_popped_item:
                popped_item = get_element_ptr(
                    darray_node, new_len, array_bounds_check=False, pos=pos
                )
                ret.append(popped_item)
                typ = popped_item.typ
                location = popped_item.location
                encoding = popped_item.encoding
            else:
                typ, location, encoding = None, None, None
            return LLLnode.from_list(
                b1.resolve(b2.resolve(ret)), typ=typ, location=location, encoding=encoding, pos=pos
            )


def getpos(node):
    return (
        node.lineno,
        node.col_offset,
        getattr(node, "end_lineno", None),
        getattr(node, "end_col_offset", None),
    )


def add_ofst(loc, ofst):
    ofst = LLLnode.from_list(ofst)
    if isinstance(loc.value, int) and isinstance(ofst.value, int):
        ret = loc.value + ofst.value
    else:
        ret = ["add", loc, ofst]
    return LLLnode.from_list(ret, location=loc.location, encoding=loc.encoding)


# TODO should really be handled in the optimizer.
def _mul(x, y):
    x = LLLnode.from_list(x)
    y = LLLnode.from_list(y)
    if isinstance(x.value, int) and isinstance(y.value, int):
        ret = x.value * y.value
    else:
        ret = ["mul", x, y]
    return LLLnode.from_list(ret)


# Resolve pointer locations for ABI-encoded data
def _getelemptr_abi_helper(parent, member_t, ofst, pos=None, clamp=True):
    member_abi_t = member_t.abi_type

    # ABI encoding has length word and then pretends length is not there
    # e.g. [[1,2]] is encoded as 0x01 <len> 0x20 <inner array ofst> <encode(inner array)>
    # note that inner array ofst is 0x20, not 0x40.
    if has_length_word(parent.typ):
        parent = add_ofst(parent, wordsize(parent.location) * DYNAMIC_ARRAY_OVERHEAD)

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
        annotation=f"{parent}{ofst}",
    )


# TODO simplify this code, especially the ABI decoding
def _get_element_ptr_tuplelike(parent, key, pos):
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

    # generated by empty() + make_setter
    if parent.value == "~empty":
        return LLLnode.from_list("~empty", typ=subtype)

    if parent.value == "multi":
        assert parent.encoding != Encoding.ABI, "no abi-encoded literals"
        return parent.args[index]

    ofst = 0  # offset from parent start

    if parent.encoding in (Encoding.ABI, Encoding.JSON_ABI):
        if parent.location == "storage":
            raise CompilerPanic("storage variables should not be abi encoded")  # pragma: notest

        member_t = typ.members[attrs[index]]

        for i in range(index):
            member_abi_t = typ.members[attrs[i]].abi_type
            ofst += member_abi_t.embedded_static_size()

        return _getelemptr_abi_helper(parent, member_t, ofst, pos)

    if parent.location == "storage":
        for i in range(index):
            ofst += typ.members[attrs[i]].storage_size_in_words
    elif parent.location in ("calldata", "memory", "data", "immutables"):
        for i in range(index):
            ofst += typ.members[attrs[i]].memory_bytes_required
    else:
        raise CompilerPanic(f"bad location {parent.location}")  # pragma: notest

    return LLLnode.from_list(
        add_ofst(parent, ofst),
        typ=subtype,
        location=parent.location,
        encoding=parent.encoding,
        annotation=annotation,
        pos=pos,
    )


def has_length_word(typ):
    return isinstance(typ, (DArrayType, ByteArrayLike))


# TODO simplify this code, especially the ABI decoding
def _get_element_ptr_array(parent, key, pos, array_bounds_check):

    assert isinstance(parent.typ, ArrayLike)

    if not is_integer_type(key.typ):
        raise TypeCheckFailure(f"{key.typ} used as array index")

    subtype = parent.typ.subtype

    if parent.value == "~empty":
        if array_bounds_check:
            # this case was previously missing a bounds check. codegen
            # is a bit complicated when bounds check is required, so
            # block it. there is no reason to index into a literal empty
            # array anyways!
            raise TypeCheckFailure("indexing into zero array not allowed")
        return LLLnode.from_list("~empty", subtype)

    if parent.value == "multi":
        assert isinstance(key.value, int)
        return parent.args[key.value]

    ix = unwrap_location(key)

    if array_bounds_check:
        # clamplt works, even for signed ints. since two's-complement
        # is used, if the index is negative, (unsigned) LT will interpret
        # it as a very large number, larger than any practical value for
        # an array index, and the clamp will throw an error.
        clamp_op = "uclamplt"
        is_darray = isinstance(parent.typ, DArrayType)
        bound = get_dyn_array_count(parent) if is_darray else parent.typ.count
        # NOTE: there are optimization rules for this when ix or bound is literal
        ix = LLLnode.from_list([clamp_op, ix, bound], typ=ix.typ)

    if parent.encoding in (Encoding.ABI, Encoding.JSON_ABI):
        if parent.location == "storage":
            raise CompilerPanic("storage variables should not be abi encoded")  # pragma: notest

        member_abi_t = subtype.abi_type

        ofst = _mul(ix, member_abi_t.embedded_static_size())

        return _getelemptr_abi_helper(parent, subtype, ofst, pos)

    if parent.location == "storage":
        element_size = subtype.storage_size_in_words
    elif parent.location in ("calldata", "memory", "data", "immutables"):
        element_size = subtype.memory_bytes_required

    ofst = _mul(ix, element_size)

    if has_length_word(parent.typ):
        data_ptr = add_ofst(parent, wordsize(parent.location) * DYNAMIC_ARRAY_OVERHEAD)
    else:
        data_ptr = parent

    return LLLnode.from_list(
        add_ofst(data_ptr, ofst), typ=subtype, location=parent.location, pos=pos
    )


def _get_element_ptr_mapping(parent, key, pos):
    assert isinstance(parent.typ, MappingType)
    subtype = parent.typ.valuetype
    key = unwrap_location(key)

    # TODO when is key None?
    if key is None or parent.location != "storage":
        raise TypeCheckFailure("bad dereference on mapping {parent}[{sub}]")

    return LLLnode.from_list(["sha3_64", parent, key], typ=subtype, location="storage")


# Take a value representing a memory or storage location, and descend down to
# an element or member variable
# This is analogous (but not necessarily equivalent to) getelementptr in LLVM.
def get_element_ptr(parent, key, pos, array_bounds_check=True):
    with parent.cache_when_complex("val") as (b, parent):
        typ = parent.typ

        if isinstance(typ, TupleLike):
            ret = _get_element_ptr_tuplelike(parent, key, pos)

        elif isinstance(typ, MappingType):
            ret = _get_element_ptr_mapping(parent, key, pos)

        elif isinstance(typ, ArrayLike):
            ret = _get_element_ptr_array(parent, key, pos, array_bounds_check)

        else:
            raise CompilerPanic(f"get_element_ptr cannot be called on {typ}")  # pragma: notest

        return b.resolve(ret)


# TODO phase this out - make private and use load_word instead
def load_op(location):
    if location == "memory":
        return "mload"
    if location == "storage":
        return "sload"
    if location == "calldata":
        return "calldataload"
    if location == "data":
        # refers to data section of currently executing code
        return "dload"
    if location == "immutables":
        # special address space for manipulating immutables before deploy
        # only makes sense in a constructor
        return "iload"
    raise CompilerPanic(f"unreachable {location}")  # pragma: notest


# TODO phase this out - make private and use store_word instead
def store_op(location):
    if location == "memory":
        return "mstore"
    if location == "storage":
        return "sstore"
    if location == "immutables":
        return "istore"
    raise CompilerPanic(f"unreachable {location}")  # pragma: notest


def load_word(ptr: LLLnode) -> LLLnode:
    return LLLnode.from_list([load_op(ptr.location), ptr])


def store_word(ptr: LLLnode, val: LLLnode) -> LLLnode:
    return LLLnode.from_list([store_op(ptr.location), ptr, val])


# Unwrap location
def unwrap_location(orig):
    if orig.location in ("memory", "storage", "calldata", "data", "immutables"):
        return LLLnode.from_list(load_word(orig), typ=orig.typ)
    else:
        # CMC 20210909 TODO double check if this branch can be removed
        if orig.value == "~empty":
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


# return a dummy LLLnode with the given type
def dummy_node_for_type(typ):
    return LLLnode("fake_node", typ=typ)


def _check_assign_bytes(left, right):
    if right.typ.maxlen > left.typ.maxlen:
        raise TypeMismatch(f"Cannot cast from {right.typ} to {left.typ}")  # pragma: notest
    # stricter check for zeroing a byte array.
    if right.value == "~empty" and right.typ.maxlen != left.typ.maxlen:
        raise TypeMismatch(
            f"Bad type for clearing bytes: expected {left.typ} but got {right.typ}"
        )  # pragma: notest


def _check_assign_list(left, right):
    def FAIL():  # pragma: nocover
        raise TypeCheckFailure(f"assigning {right.typ} to {left.typ}")

    if left.value == "multi":
        # Cannot do something like [a, b, c] = [1, 2, 3]
        FAIL()  # pragma: notest

    if isinstance(left, SArrayType):
        if not isinstance(right, SArrayType):
            FAIL()  # pragma: notest
        if left.typ.count != right.typ.count:
            FAIL()  # pragma: notest
        check_assign(dummy_node_for_type(left.typ.subtyp), dummy_node_for_type(right.typ.subtyp))

    if isinstance(left, DArrayType):
        if not isinstance(right, DArrayType):
            FAIL()  # pragma: notest

        if left.typ.count < right.typ.count:
            FAIL()  # pragma: notest

        # stricter check for zeroing
        if right.value == "~empty" and right.typ.count != left.typ.count:
            raise TypeCheckFailure(
                f"Bad type for clearing bytes: expected {left.typ} but got {right.typ}"
            )  # pragma: notest

        check_assign(dummy_node_for_type(left.typ.subtyp), dummy_node_for_type(right.typ.subtyp))


def _check_assign_tuple(left, right):
    def FAIL():  # pragma: nocover
        raise TypeCheckFailure(f"assigning {right.typ} to {left.typ}")

    if not isinstance(right.typ, left.typ.__class__):
        FAIL()  # pragma: notest

    if isinstance(left.typ, StructType):
        for k in left.typ.members:
            if k not in right.typ.members:
                FAIL()  # pragma: notest
            check_assign(
                dummy_node_for_type(left.typ.members[k]),
                dummy_node_for_type(right.typ.members[k]),
            )

        for k in right.typ.members:
            if k not in left.typ.members:
                FAIL()  # pragma: notest

        if left.typ.name != right.typ.name:
            FAIL()  # pragma: notest

    else:
        if len(left.typ.members) != len(right.typ.members):
            FAIL()  # pragma: notest
        for (l, r) in zip(left.typ.members, right.typ.members):
            check_assign(dummy_node_for_type(l), dummy_node_for_type(r))


# sanity check an assignment
# typechecking source code is done at an earlier phase
# this function is more of a sanity check for typechecking internally
# generated assignments
def check_assign(left, right):
    def FAIL():  # pragma: nocover
        raise TypeCheckFailure(f"assigning {right.typ} to {left.typ} {left} {right}")

    if isinstance(left.typ, ByteArrayLike):
        _check_assign_bytes(left, right)
    elif isinstance(left.typ, ArrayLike):
        _check_assign_list(left, right)
    elif isinstance(left.typ, TupleLike):
        _check_assign_tuple(left, right)

    elif isinstance(left.typ, BaseType):
        # TODO once we propagate types from typechecker, introduce this check:
        # if left.typ != right.typ:
        #    FAIL()  # pragma: notest
        pass

    else:  # pragma: nocover
        FAIL()


_label = 0


# TODO might want to coalesce with Context.fresh_varname and compile_lll.mksymbol
def _freshname(name):
    global _label
    _label += 1
    return f"{name}{_label}"


# Create an x=y statement, where the types may be compound
def make_setter(left, right, pos):
    check_assign(left, right)

    # Basic types
    if isinstance(left.typ, BaseType):
        enc = right.encoding  # unwrap_location butchers encoding
        right = unwrap_location(right)
        # TODO rethink/streamline the clamp_basetype logic
        if _needs_clamp(right.typ, enc):
            right = clamp_basetype(right)

        op = store_op(left.location)
        return LLLnode.from_list([op, left, right], pos=pos)

    # Byte arrays
    elif isinstance(left.typ, ByteArrayLike):
        # TODO rethink/streamline the clamp_basetype logic
        if _needs_clamp(right.typ, right.encoding):
            with right.cache_when_complex("bs_ptr") as (b, right):
                copier = make_byte_array_copier(left, right, pos)
                ret = b.resolve(["seq", clamp_bytestring(right), copier])
        else:
            ret = make_byte_array_copier(left, right, pos)

        return LLLnode.from_list(ret)

    elif isinstance(left.typ, DArrayType):
        # TODO should we enable this?
        # implicit conversion from sarray to darray
        # if isinstance(right.typ, SArrayType):
        #    return _complex_make_setter(left, right, pos)

        # TODO rethink/streamline the clamp_basetype logic
        if _needs_clamp(right.typ, right.encoding):
            with right.cache_when_complex("arr_ptr") as (b, right):
                copier = _dynarray_make_setter(left, right, pos)
                ret = b.resolve(["seq", clamp_dyn_array(right), copier])
        else:
            ret = _dynarray_make_setter(left, right, pos)

        return LLLnode.from_list(ret)

    # Arrays
    elif isinstance(left.typ, (SArrayType, TupleLike)):
        return _complex_make_setter(left, right, pos)


def _complex_make_setter(left, right, pos):
    if right.value == "~empty" and left.location == "memory":
        # optimized memzero
        return mzero(left, left.typ.memory_bytes_required)

    ret = ["seq"]

    if isinstance(left.typ, SArrayType):
        n_items = right.typ.count
        keys = [LLLnode.from_list(i, typ="uint256") for i in range(n_items)]

    if isinstance(left.typ, TupleLike):
        keys = left.typ.tuple_keys()

    # if len(keyz) == 0:
    #    return LLLnode.from_list(["pass"])

    # general case
    # TODO use copy_bytes when the generated code is above a certain size
    with left.cache_when_complex("_L") as (b1, left), right.cache_when_complex("_R") as (b2, right):

        for k in keys:
            l_i = get_element_ptr(left, k, pos=pos, array_bounds_check=False)
            r_i = get_element_ptr(right, k, pos=pos, array_bounds_check=False)
            ret.append(make_setter(l_i, r_i, pos))

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
def shr(bits, x):
    if version_check(begin="constantinople"):
        return ["shr", bits, x]
    return ["div", x, ["exp", 2, bits]]


# convenience rewrites for shr/sar/shl
def shl(bits, x):
    if version_check(begin="constantinople"):
        return ["shl", bits, x]
    return ["mul", x, ["exp", 2, bits]]


def sar(bits, x):
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


def clamp_bytestring(lll_node):
    t = lll_node.typ
    if not isinstance(t, ByteArrayLike):
        raise CompilerPanic(f"{t} passed to clamp_bytestring")  # pragma: notest
    return ["assert", ["le", get_bytearray_length(lll_node), t.maxlen]]


def clamp_dyn_array(lll_node):
    t = lll_node.typ
    assert isinstance(t, DArrayType)
    return ["assert", ["le", get_dyn_array_count(lll_node), t.count]]


# clampers for basetype
def clamp_basetype(lll_node):
    t = lll_node.typ
    if not isinstance(t, BaseType):
        raise CompilerPanic(f"{t} passed to clamp_basetype")  # pragma: notest

    # copy of the input
    lll_node = unwrap_location(lll_node)

    if is_integer_type(t):
        if t._int_info.bits == 256:
            return lll_node
        else:
            return int_clamp(lll_node, t._int_info.bits, signed=t._int_info.is_signed)

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
    if t.typ in ("bytes32",):
        return lll_node  # special case, no clamp.
    if is_bytes_m_type(t):
        return bytes_clamp(lll_node, t._bytes_info.m)

    raise CompilerPanic(f"{t} passed to clamp_basetype")  # pragma: notest


def int_clamp(lll_node, bits, signed=False):
    """Generalized clamper for integer types. Takes the number of bits,
    whether it's signed, and returns an LLL node which checks it is
    in bounds. (Consumers should use clamp_basetype instead which uses
    type-based dispatch and is a little safer.)
    """
    if bits >= 256:
        raise CompilerPanic(f"invalid clamp: {bits}>=256 ({lll_node})")  # pragma: notest
    with lll_node.cache_when_complex("val") as (b, val):
        if signed:
            # example for bits==128:
            # promote_signed_int(val, bits) is the "canonical" version of val
            # if val is in bounds, the bits above bit 128 should be equal.
            # (this works for both val >= 0 and val < 0. in the first case,
            # all upper bits should be 0 if val is a valid int128,
            # in the latter case, all upper bits should be 1.)
            assertion = ["assert", ["eq", val, promote_signed_int(val, bits)]]
        else:
            assertion = ["assert", ["iszero", shr(bits, val)]]

        ret = b.resolve(["seq", assertion, val])

    # TODO fix this annotation
    return LLLnode.from_list(ret, annotation=f"int_clamp {lll_node.typ}")


def bytes_clamp(lll_node: LLLnode, n_bytes: int) -> LLLnode:
    if not (0 < n_bytes <= 32):
        raise CompilerPanic(f"bad type: bytes{n_bytes}")
    with lll_node.cache_when_complex("val") as (b, val):
        assertion = ["assert", ["iszero", shl(n_bytes * 8, val)]]
        ret = b.resolve(["seq", assertion, val])
    return LLLnode.from_list(ret, annotation=f"bytes{n_bytes}_clamp")


# e.g. for int8, promote 255 to -1
def promote_signed_int(x, bits):
    assert bits % 8 == 0
    ret = ["signextend", bits // 8 - 1, x]
    return LLLnode.from_list(ret, annotation=f"promote int{bits}")
