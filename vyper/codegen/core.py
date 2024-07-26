from vyper.codegen.ir_node import Encoding, IRnode
from vyper.compiler.settings import _opt_codesize, _opt_gas, _opt_none
from vyper.evm.address_space import (
    CALLDATA,
    DATA,
    IMMUTABLES,
    MEMORY,
    STORAGE,
    TRANSIENT,
    AddrSpace,
    legal_in_staticcall,
)
from vyper.evm.opcodes import version_check
from vyper.exceptions import CompilerPanic, TypeCheckFailure, TypeMismatch
from vyper.semantics.data_locations import DataLocation
from vyper.semantics.types import (
    AddressT,
    BoolT,
    BytesM_T,
    BytesT,
    DArrayT,
    DecimalT,
    HashMapT,
    IntegerT,
    InterfaceT,
    StructT,
    TupleT,
    _BytestringT,
)
from vyper.semantics.types.shortcuts import BYTES32_T, INT256_T, UINT256_T
from vyper.semantics.types.subscriptable import SArrayT
from vyper.semantics.types.user import FlagT
from vyper.utils import GAS_COPY_WORD, GAS_IDENTITY, GAS_IDENTITYWORD, ceil32

DYNAMIC_ARRAY_OVERHEAD = 1


def is_bytes_m_type(typ):
    return isinstance(typ, BytesM_T)


def is_numeric_type(typ):
    return isinstance(typ, (IntegerT, DecimalT))


def is_integer_type(typ):
    return isinstance(typ, IntegerT)


def is_decimal_type(typ):
    return isinstance(typ, DecimalT)


def is_flag_type(typ):
    return isinstance(typ, FlagT)


def is_tuple_like(typ):
    # A lot of code paths treat tuples and structs similarly
    # so we have a convenience function to detect it
    ret = isinstance(typ, (TupleT, StructT))
    assert ret == hasattr(typ, "tuple_items")
    return ret


def is_array_like(typ):
    # For convenience static and dynamic arrays share some code paths
    ret = isinstance(typ, (DArrayT, SArrayT))
    assert ret == typ._is_array_type
    return ret


def get_type_for_exact_size(n_bytes):
    """Create a type which will take up exactly n_bytes. Used for allocating internal buffers.

    Parameters:
      n_bytes: the number of bytes to allocate
    Returns:
      type: A type which can be passed to context.new_variable
    """
    return BytesT(n_bytes - 32 * DYNAMIC_ARRAY_OVERHEAD)


# propagate revert message when calls to external contracts fail
def check_external_call(call_ir):
    copy_revertdata = ["returndatacopy", 0, 0, "returndatasize"]
    revert = IRnode.from_list(["revert", 0, "returndatasize"], error_msg="external call failed")

    propagate_revert_ir = ["seq", copy_revertdata, revert]
    return ["if", ["iszero", call_ir], propagate_revert_ir]


# cost per byte of the identity precompile
def _identity_gas_bound(num_bytes):
    return GAS_IDENTITY + GAS_IDENTITYWORD * (ceil32(num_bytes) // 32)


def _mcopy_gas_bound(num_bytes):
    return GAS_COPY_WORD * ceil32(num_bytes) // 32


def _calldatacopy_gas_bound(num_bytes):
    return GAS_COPY_WORD * ceil32(num_bytes) // 32


def _codecopy_gas_bound(num_bytes):
    return GAS_COPY_WORD * ceil32(num_bytes) // 32


def data_location_to_address_space(s: DataLocation, is_ctor_ctx: bool) -> AddrSpace:
    if s == DataLocation.MEMORY:
        return MEMORY
    if s == DataLocation.STORAGE:
        return STORAGE
    if s == DataLocation.TRANSIENT:
        return TRANSIENT
    if s == DataLocation.CODE:
        if is_ctor_ctx:
            return IMMUTABLES
        return DATA

    raise CompilerPanic("unreachable!")  # pragma: nocover


def address_space_to_data_location(s: AddrSpace) -> DataLocation:
    if s == MEMORY:
        return DataLocation.MEMORY
    if s == STORAGE:
        return DataLocation.STORAGE
    if s == TRANSIENT:
        return DataLocation.TRANSIENT
    if s in (IMMUTABLES, DATA):
        return DataLocation.CODE
    if s == CALLDATA:
        return DataLocation.CALLDATA

    raise CompilerPanic("unreachable!")  # pragma: nocover


def writeable(context, ir_node):
    assert ir_node.is_pointer  # sanity check

    if context.is_constant() and not legal_in_staticcall(ir_node.location):
        return False
    return ir_node.mutable


# Copy byte array word-for-word (including layout)
# TODO make this a private function
def make_byte_array_copier(dst, src):
    assert isinstance(src.typ, _BytestringT)
    assert isinstance(dst.typ, _BytestringT)

    _check_assign_bytes(dst, src)

    # TODO: remove this branch, copy_bytes and get_bytearray_length should handle
    if src.value == "~empty" or src.typ.maxlen == 0:
        # set length word to 0.
        return STORE(dst, 0)

    with src.cache_when_complex("src") as (b1, src):
        if src.typ.maxlen <= 32 and not copy_opcode_available(dst, src):
            # if there is no batch copy opcode available,
            # it's cheaper to run two load/stores instead of copy_bytes
            ret = ["seq"]
            # store length word
            len_ = get_bytearray_length(src)
            ret.append(STORE(dst, len_))

            # store the single data word.
            dst_data_ptr = bytes_data_ptr(dst)
            src_data_ptr = bytes_data_ptr(src)
            ret.append(STORE(dst_data_ptr, LOAD(src_data_ptr)))
            return b1.resolve(ret)

        # batch copy the bytearray (including length word) using copy_bytes
        len_ = add_ofst(get_bytearray_length(src), 32)
        max_bytes = src.typ.maxlen + 32
        ret = copy_bytes(dst, src, len_, max_bytes)
        return b1.resolve(ret)


def bytes_data_ptr(ptr):
    if ptr.location is None:  # pragma: nocover
        raise CompilerPanic("tried to modify non-pointer type")
    assert isinstance(ptr.typ, _BytestringT)
    return add_ofst(ptr, ptr.location.word_scale)


def dynarray_data_ptr(ptr):
    if ptr.location is None:  # pragma: nocover
        raise CompilerPanic("tried to modify non-pointer type")
    assert isinstance(ptr.typ, DArrayT)
    return add_ofst(ptr, ptr.location.word_scale)


def _dynarray_make_setter(dst, src, hi=None):
    assert isinstance(src.typ, DArrayT)
    assert isinstance(dst.typ, DArrayT)

    if src.value == "~empty":
        return IRnode.from_list(STORE(dst, 0))

    # copy contents of src dynarray to dst.
    # note that in case src and dst refer to the same dynarray,
    # in order for get_element_ptr oob checks on the src dynarray
    # to work, we need to wait until after the data is copied
    # before we clobber the length word.

    if src.value == "multi":
        # validation is only performed on unsafe data, but we are dealing with
        # a literal here.
        assert hi is None
        ret = ["seq"]
        # handle literals

        # copy each item
        n_items = len(src.args)

        for i in range(n_items):
            k = IRnode.from_list(i, typ=UINT256_T)
            dst_i = get_element_ptr(dst, k, array_bounds_check=False)
            src_i = get_element_ptr(src, k, array_bounds_check=False)
            ret.append(make_setter(dst_i, src_i))

        # write the length word after data is copied
        store_length = STORE(dst, n_items)
        ann = None
        if src.annotation is not None:
            ann = f"len({src.annotation})"
        store_length = IRnode.from_list(store_length, annotation=ann)

        ret.append(store_length)

        return ret

    with src.cache_when_complex("darray_src") as (b1, src):
        # for ABI-encoded dynamic data, we must loop to unpack, since
        # the layout does not match our memory layout
        should_loop = src.encoding == Encoding.ABI and src.typ.value_type.abi_type.is_dynamic()

        # if the data is not validated, we must loop to unpack
        should_loop |= needs_clamp(src.typ.value_type, src.encoding)

        # performance: if the subtype is dynamic, there might be a lot
        # of unused space inside of each element. for instance
        # DynArray[DynArray[uint256, 100], 5] where all the child
        # arrays are empty - for this case, we recursively call
        # into make_setter instead of straight bytes copy
        # TODO we can make this heuristic more precise, e.g.
        # loop when subtype.is_dynamic AND location == storage
        # OR array_size <= /bound where loop is cheaper than memcpy/
        should_loop |= src.typ.value_type.abi_type.is_dynamic()

        with get_dyn_array_count(src).cache_when_complex("darray_count") as (b2, count):
            ret = ["seq"]

            if should_loop:
                i = IRnode.from_list(_freshname("copy_darray_ix"), typ=UINT256_T)

                loop_body = make_setter(
                    get_element_ptr(dst, i, array_bounds_check=False),
                    get_element_ptr(src, i, array_bounds_check=False),
                    hi=hi,
                )
                loop_body.annotation = f"{dst}[i] = {src}[i]"

                ret.append(["repeat", i, 0, count, src.typ.count, loop_body])
                # write the length word after data is copied
                ret.append(STORE(dst, count))

            else:
                element_size = src.typ.value_type.memory_bytes_required
                # number of elements * size of element in bytes + length word
                n_bytes = add_ofst(_mul(count, element_size), 32)
                max_bytes = 32 + src.typ.count * element_size

                # batch copy the entire dynarray, including length word
                ret.append(copy_bytes(dst, src, n_bytes, max_bytes))

            return b1.resolve(b2.resolve(ret))


# Copy bytes
# Accepts 4 arguments:
# (i) an IR node for the start position of the source
# (ii) an IR node for the start position of the destination
# (iii) an IR node for the length (in bytes)
# (iv) a constant for the max length (in bytes)
# NOTE: may pad to ceil32 of `length`! If you ask to copy 1 byte, it may
# copy an entire (32-byte) word, depending on the copy routine chosen.
# TODO maybe always pad to ceil32, to reduce dirty bytes bugs
def copy_bytes(dst, src, length, length_bound):
    annotation = f"copy up to {length_bound} bytes from {src} to {dst}"

    src = IRnode.from_list(src)
    dst = IRnode.from_list(dst)
    length = IRnode.from_list(length)

    with src.cache_when_complex("src") as (b1, src), length.cache_when_complex(
        "copy_bytes_count"
    ) as (b2, length), dst.cache_when_complex("dst") as (b3, dst):
        assert isinstance(length_bound, int) and length_bound >= 0

        # correctness: do not clobber dst
        if length_bound == 0:
            return IRnode.from_list(["seq"], annotation=annotation)
        # performance: if we know that length is 0, do not copy anything
        if length.value == 0:
            return IRnode.from_list(["seq"], annotation=annotation)

        assert src.is_pointer and dst.is_pointer

        # fast code for common case where num bytes is small
        if length_bound <= 32:
            copy_op = STORE(dst, LOAD(src))
            ret = IRnode.from_list(copy_op, annotation=annotation)
            return b1.resolve(b2.resolve(b3.resolve(ret)))

        if dst.location == MEMORY and src.location in (MEMORY, CALLDATA, DATA):
            # special cases: batch copy to memory
            # TODO: iloadbytes
            if src.location == MEMORY:
                if version_check(begin="cancun"):
                    copy_op = ["mcopy", dst, src, length]
                    gas_bound = _mcopy_gas_bound(length_bound)
                else:
                    copy_op = ["staticcall", "gas", 4, src, length, dst, length]
                    gas_bound = _identity_gas_bound(length_bound)
            elif src.location == CALLDATA:
                copy_op = ["calldatacopy", dst, src, length]
                gas_bound = _calldatacopy_gas_bound(length_bound)
            elif src.location == DATA:
                copy_op = ["dloadbytes", dst, src, length]
                # note: dloadbytes compiles to CODECOPY
                gas_bound = _codecopy_gas_bound(length_bound)

            ret = IRnode.from_list(copy_op, annotation=annotation, add_gas_estimate=gas_bound)
            return b1.resolve(b2.resolve(b3.resolve(ret)))

        if dst.location == IMMUTABLES and src.location in (MEMORY, DATA):
            # TODO istorebytes-from-mem, istorebytes-from-calldata(?)
            # compile to identity, CODECOPY respectively.
            pass

        # general case, copy word-for-word
        # pseudocode for our approach (memory-storage as example):
        # for i in range(len, bound=MAX_LEN):
        #   sstore(_dst + i, mload(src + i * 32))
        i = IRnode.from_list(_freshname("copy_bytes_ix"), typ=UINT256_T)

        # optimized form of (div (ceil32 len) 32)
        n = ["div", ["add", 31, length], 32]
        n_bound = ceil32(length_bound) // 32

        dst_i = add_ofst(dst, _mul(i, dst.location.word_scale))
        src_i = add_ofst(src, _mul(i, src.location.word_scale))

        copy_one_word = STORE(dst_i, LOAD(src_i))

        main_loop = ["repeat", i, 0, n, n_bound, copy_one_word]

        return b1.resolve(
            b2.resolve(b3.resolve(IRnode.from_list(main_loop, annotation=annotation)))
        )


# get the number of bytes at runtime
def get_bytearray_length(arg):
    typ = UINT256_T

    # TODO: it would be nice to merge the implementations of get_bytearray_length and
    # get_dynarray_count
    if arg.value == "~empty":
        return IRnode.from_list(0, typ=typ)

    return IRnode.from_list(LOAD(arg), typ=typ)


# get the number of elements at runtime
def get_dyn_array_count(arg):
    assert isinstance(arg.typ, DArrayT)

    typ = UINT256_T

    if arg.value == "multi":
        return IRnode.from_list(len(arg.args), typ=typ)

    if arg.value == "~empty":
        # empty(DynArray[...])
        return IRnode.from_list(0, typ=typ)

    return IRnode.from_list(LOAD(arg), typ=typ)


def append_dyn_array(darray_node, elem_node):
    assert isinstance(darray_node.typ, DArrayT)

    assert darray_node.typ.count > 0, "jerk boy u r out"

    ret = ["seq"]
    with darray_node.cache_when_complex("darray") as (b1, darray_node):
        len_ = get_dyn_array_count(darray_node)
        with len_.cache_when_complex("old_darray_len") as (b2, len_):
            assertion = ["assert", ["lt", len_, darray_node.typ.count]]
            ret.append(IRnode.from_list(assertion, error_msg=f"{darray_node.typ} bounds check"))
            # NOTE: typechecks elem_node
            # NOTE skip array bounds check bc we already asserted len two lines up
            ret.append(
                make_setter(get_element_ptr(darray_node, len_, array_bounds_check=False), elem_node)
            )

            # store new length
            ret.append(ensure_eval_once("append_dynarray", STORE(darray_node, ["add", len_, 1])))

            return IRnode.from_list(b1.resolve(b2.resolve(ret)))


def pop_dyn_array(darray_node, return_popped_item):
    assert isinstance(darray_node.typ, DArrayT)
    assert darray_node.encoding == Encoding.VYPER
    ret = ["seq"]
    with darray_node.cache_when_complex("darray") as (b1, darray_node):
        old_len = clamp("gt", get_dyn_array_count(darray_node), 0)
        new_len = IRnode.from_list(["sub", old_len, 1], typ=UINT256_T)

        with new_len.cache_when_complex("new_len") as (b2, new_len):
            # store new length
            ret.append(ensure_eval_once("pop_dynarray", STORE(darray_node, new_len)))

            # NOTE skip array bounds check bc we already asserted len two lines up
            if return_popped_item:
                popped_item = get_element_ptr(darray_node, new_len, array_bounds_check=False)
                ret.append(popped_item)
                typ = popped_item.typ
                location = popped_item.location
            else:
                typ, location = None, None

            return IRnode.from_list(b1.resolve(b2.resolve(ret)), typ=typ, location=location)


# add an offset to a pointer, keeping location and encoding info
def add_ofst(ptr, ofst):
    ret = ["add", ptr, ofst]
    return IRnode.from_list(ret, location=ptr.location, encoding=ptr.encoding)


# shorthand util
def _mul(x, y):
    ret = ["mul", x, y]
    return IRnode.from_list(ret)


# Resolve pointer locations for ABI-encoded data
def _getelemptr_abi_helper(parent, member_t, ofst):
    member_abi_t = member_t.abi_type

    # ABI encoding has length word and then pretends length is not there
    # e.g. [[1,2]] is encoded as 0x01 <len> 0x20 <inner array ofst> <encode(inner array)>
    # note that inner array ofst is 0x20, not 0x40.
    if has_length_word(parent.typ):
        parent = add_ofst(parent, parent.location.word_scale * DYNAMIC_ARRAY_OVERHEAD)

    ofst_ir = add_ofst(parent, ofst)

    if member_abi_t.is_dynamic():
        # double dereference, according to ABI spec
        ofst_ir = add_ofst(parent, unwrap_location(ofst_ir))
        if _dirty_read_risk(ofst_ir):
            # check no arithmetic overflow
            ofst_ir = ["seq", ["assert", ["ge", ofst_ir, parent]], ofst_ir]

    return IRnode.from_list(
        ofst_ir,
        typ=member_t,
        location=parent.location,
        encoding=parent.encoding,
        annotation=f"{parent}{ofst}",
    )


# TODO simplify this code, especially the ABI decoding
def _get_element_ptr_tuplelike(parent, key, hi=None):
    typ = parent.typ
    assert is_tuple_like(typ)

    if isinstance(typ, StructT):
        assert isinstance(key, str)
        subtype = typ.member_types[key]
        attrs = list(typ.tuple_keys())
        index = attrs.index(key)
        annotation = key
    else:
        assert isinstance(typ, TupleT)
        assert isinstance(key, int)
        subtype = typ.member_types[key]
        attrs = list(typ.tuple_keys())
        index = key
        annotation = None

    # generated by empty() + make_setter
    if parent.value == "~empty":
        return IRnode.from_list("~empty", typ=subtype)

    if parent.value == "multi":
        assert parent.encoding != Encoding.ABI, "no abi-encoded literals"
        return parent.args[index]

    ofst = 0  # offset from parent start

    if parent.encoding == Encoding.ABI:
        if parent.location in (STORAGE, TRANSIENT):  # pragma: nocover
            raise CompilerPanic("storage variables should not be abi encoded")

        member_t = typ.member_types[attrs[index]]

        for i in range(index):
            member_abi_t = typ.member_types[attrs[i]].abi_type
            ofst += member_abi_t.embedded_static_size()

        return _getelemptr_abi_helper(parent, member_t, ofst)

    data_location = address_space_to_data_location(parent.location)
    for i in range(index):
        t = typ.member_types[attrs[i]]
        ofst += t.get_size_in(data_location)

    return IRnode.from_list(
        add_ofst(parent, ofst),
        typ=subtype,
        location=parent.location,
        encoding=parent.encoding,
        annotation=annotation,
    )


def has_length_word(typ):
    # Consider moving this to an attribute on typ
    return isinstance(typ, (DArrayT, _BytestringT))


# TODO simplify this code, especially the ABI decoding
def _get_element_ptr_array(parent, key, array_bounds_check):
    assert is_array_like(parent.typ)

    if not is_integer_type(key.typ):  # pragma: nocover
        raise TypeCheckFailure(f"{key.typ} used as array index")

    subtype = parent.typ.value_type

    if parent.value == "~empty":
        if array_bounds_check:
            # this case was previously missing a bounds check. codegen
            # is a bit complicated when bounds check is required, so
            # block it. there is no reason to index into a literal empty
            # array anyways!
            raise TypeCheckFailure("indexing into zero array not allowed")
        return IRnode.from_list("~empty", subtype)

    if parent.value == "multi":
        assert isinstance(key.value, int)
        return parent.args[key.value]

    ix = unwrap_location(key)

    if array_bounds_check:
        is_darray = isinstance(parent.typ, DArrayT)
        bound = get_dyn_array_count(parent) if is_darray else parent.typ.count
        # NOTE: there are optimization rules for the bounds check when
        # ix or bound is literal
        with ix.cache_when_complex("ix") as (b1, ix):
            LT = "slt" if ix.typ.is_signed else "lt"
            # note: this is optimized out for unsigned integers
            is_negative = [LT, ix, 0]
            # always use unsigned ge, since bound is always an unsigned quantity
            is_oob = ["ge", ix, bound]
            checked_ix = ["seq", ["assert", ["iszero", ["or", is_negative, is_oob]]], ix]
            ix = b1.resolve(IRnode.from_list(checked_ix))
        ix.set_error_msg(f"{parent.typ} bounds check")

    if parent.encoding == Encoding.ABI:
        if parent.location in (STORAGE, TRANSIENT):  # pragma: nocover
            raise CompilerPanic("storage variables should not be abi encoded")

        member_abi_t = subtype.abi_type

        ofst = _mul(ix, member_abi_t.embedded_static_size())

        return _getelemptr_abi_helper(parent, subtype, ofst)

    data_location = address_space_to_data_location(parent.location)
    element_size = subtype.get_size_in(data_location)

    ofst = _mul(ix, element_size)

    if has_length_word(parent.typ):
        data_ptr = add_ofst(parent, parent.location.word_scale * DYNAMIC_ARRAY_OVERHEAD)
    else:
        data_ptr = parent

    return IRnode.from_list(add_ofst(data_ptr, ofst), typ=subtype, location=parent.location)


def _get_element_ptr_mapping(parent, key):
    assert isinstance(parent.typ, HashMapT)
    subtype = parent.typ.value_type
    key = unwrap_location(key)

    if parent.location not in (STORAGE, TRANSIENT):  # pragma: nocover
        raise TypeCheckFailure(f"bad dereference on mapping {parent}[{key}]")

    return IRnode.from_list(["sha3_64", parent, key], typ=subtype, location=parent.location)


# Take a value representing a memory or storage location, and descend down to
# an element or member variable
# This is analogous (but not necessarily equivalent to) getelementptr in LLVM.
def get_element_ptr(parent, key, array_bounds_check=True):
    with parent.cache_when_complex("val") as (b, parent):
        typ = parent.typ

        if is_tuple_like(typ):
            ret = _get_element_ptr_tuplelike(parent, key)

        elif isinstance(typ, HashMapT):
            ret = _get_element_ptr_mapping(parent, key)

        elif is_array_like(typ):
            ret = _get_element_ptr_array(parent, key, array_bounds_check)

        else:  # pragma: nocover
            raise CompilerPanic(f"get_element_ptr cannot be called on {typ}")

        return b.resolve(ret)


def LOAD(ptr: IRnode) -> IRnode:
    if ptr.location is None:  # pragma: nocover
        raise CompilerPanic("cannot dereference non-pointer type")
    op = ptr.location.load_op
    if op is None:  # pragma: nocover
        raise CompilerPanic(f"unreachable {ptr.location}")
    return IRnode.from_list([op, ptr])


def eval_once_check(name):
    # an IRnode which enforces uniqueness. include with a side-effecting
    # operation to sanity check that the codegen pipeline only generates
    # the side-effecting operation once (otherwise, IR-to-assembly will
    # throw a duplicate label exception). there is no runtime overhead
    # since the jumpdest gets optimized out in the final stage of assembly.
    return IRnode.from_list(["unique_symbol", name])


def ensure_eval_once(name, irnode):
    return ["seq", eval_once_check(_freshname(name)), irnode]


def STORE(ptr: IRnode, val: IRnode) -> IRnode:
    if ptr.location is None:  # pragma: nocover
        raise CompilerPanic("cannot dereference non-pointer type")
    op = ptr.location.store_op
    if op is None:  # pragma: nocover
        raise CompilerPanic(f"unreachable {ptr.location}")

    store = [op, ptr, val]
    # don't use eval_once_check for memory, immutables because it interferes
    # with optimizer
    if ptr.location in (MEMORY, IMMUTABLES):
        return IRnode.from_list(store)

    return IRnode.from_list(ensure_eval_once(f"{op}_", store))


# Unwrap location
def unwrap_location(orig):
    if orig.location is not None:
        return IRnode.from_list(LOAD(orig), typ=orig.typ)
    else:
        # CMC 2022-03-24 TODO refactor so this branch can be removed
        if orig.value == "~empty":
            # must be word type
            return IRnode.from_list(0, typ=orig.typ)
        return orig


# utility function, constructs an IR tuple out of a list of IR nodes
def ir_tuple_from_args(args):
    typ = TupleT([x.typ for x in args])
    return IRnode.from_list(["multi"] + [x for x in args], typ=typ)


def needs_external_call_wrap(typ):
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

    return not (isinstance(typ, TupleT) and typ.length > 1)


def calculate_type_for_external_return(typ):
    if needs_external_call_wrap(typ):
        return TupleT([typ])
    return typ


def wrap_value_for_external_return(ir_val):
    # used for LHS promotion
    if needs_external_call_wrap(ir_val.typ):
        return ir_tuple_from_args([ir_val])
    else:
        return ir_val


def set_type_for_external_return(ir_val):
    # used for RHS promotion
    ir_val.typ = calculate_type_for_external_return(ir_val.typ)


# return a dummy IRnode with the given type
def dummy_node_for_type(typ):
    return IRnode("fake_node", typ=typ)


def _check_assign_bytes(left, right):
    if right.typ.maxlen > left.typ.maxlen:  # pragma: nocover
        raise TypeMismatch(f"Cannot cast from {right.typ} to {left.typ}")

    # stricter check for zeroing a byte array.
    # TODO: these should be TypeCheckFailure instead of TypeMismatch
    if right.value == "~empty" and right.typ.maxlen != left.typ.maxlen:  # pragma: nocover
        raise TypeMismatch(f"Cannot cast from empty({right.typ}) to {left.typ}")


def _check_assign_list(left, right):
    def FAIL():  # pragma: no cover
        raise TypeCheckFailure(f"assigning {right.typ} to {left.typ}")

    if left.value == "multi":  # pragma: nocover
        # Cannot do something like [a, b, c] = [1, 2, 3]
        FAIL()

    if isinstance(left.typ, SArrayT):
        if not is_array_like(right.typ):  # pragma: nocover
            FAIL()
        if left.typ.count != right.typ.count:  # pragma: nocover
            FAIL()

        # TODO recurse into left, right if literals?
        check_assign(
            dummy_node_for_type(left.typ.value_type), dummy_node_for_type(right.typ.value_type)
        )

    if isinstance(left.typ, DArrayT):
        if not isinstance(right.typ, DArrayT):  # pragma: nocover
            FAIL()

        if left.typ.count < right.typ.count:  # pragma: nocover
            FAIL()

        # stricter check for zeroing
        if right.value == "~empty" and right.typ.count != left.typ.count:  # pragma: nocover
            raise TypeCheckFailure(
                f"Bad type for clearing bytes: expected {left.typ} but got {right.typ}"
            )

        # TODO recurse into left, right if literals?
        check_assign(
            dummy_node_for_type(left.typ.value_type), dummy_node_for_type(right.typ.value_type)
        )


def _check_assign_tuple(left, right):
    def FAIL():  # pragma: no cover
        raise TypeCheckFailure(f"assigning {right.typ} to {left.typ}")

    if not isinstance(right.typ, left.typ.__class__):  # pragma: nocover
        FAIL()

    if isinstance(left.typ, StructT):
        for k in left.typ.member_types:
            if k not in right.typ.member_types:  # pragma: nocover
                FAIL()
            # TODO recurse into left, right if literals?
            check_assign(
                dummy_node_for_type(left.typ.member_types[k]),
                dummy_node_for_type(right.typ.member_types[k]),
            )

        for k in right.typ.member_types:
            if k not in left.typ.member_types:  # pragma: nocover
                FAIL()

        if left.typ.name != right.typ.name:  # pragma: nocover
            FAIL()

    else:
        if len(left.typ.member_types) != len(right.typ.member_types):  # pragma: nocover
            FAIL()
        for left_, right_ in zip(left.typ.member_types, right.typ.member_types):
            # TODO recurse into left, right if literals?
            check_assign(dummy_node_for_type(left_), dummy_node_for_type(right_))


# sanity check an assignment
# typechecking source code is done at an earlier phase
# this function is more of a sanity check for typechecking internally
# generated assignments
# TODO: do we still need this?
def check_assign(left, right):
    def FAIL():  # pragma: no cover
        raise TypeCheckFailure(f"assigning {right.typ} to {left.typ} {left} {right}")

    if isinstance(left.typ, _BytestringT):
        _check_assign_bytes(left, right)
    elif is_array_like(left.typ):
        _check_assign_list(left, right)
    elif is_tuple_like(left.typ):
        _check_assign_tuple(left, right)

    elif left.typ._is_prim_word:
        # TODO once we propagate types from typechecker, introduce this check:
        # if left.typ != right.typ:  # pragma: nocover
        #    FAIL()
        pass

    else:  # pragma: no cover
        FAIL()


_label = 0


# TODO might want to coalesce with Context.fresh_varname and compile_ir.mksymbol
def _freshname(name):
    global _label
    _label += 1
    return f"{name}{_label}"


def reset_names():
    global _label
    _label = 0


# returns True if t is ABI encoded and is a type that needs any kind of
# validation
def needs_clamp(t, encoding):
    if encoding == Encoding.VYPER:
        return False
    if encoding != Encoding.ABI:  # pragma: nocover
        raise CompilerPanic("unreachable")
    if isinstance(t, (_BytestringT, DArrayT)):
        return True
    if isinstance(t, FlagT):
        return len(t._flag_members) < 256
    if isinstance(t, SArrayT):
        return needs_clamp(t.value_type, encoding)
    if is_tuple_like(t):
        return any(needs_clamp(m, encoding) for m in t.tuple_members())
    if t._is_prim_word:
        return t not in (INT256_T, UINT256_T, BYTES32_T)

    raise CompilerPanic("unreachable")  # pragma: nocover


# when abi encoded data is user provided and lives in memory,
# we risk either reading oob of the buffer or oob of the payload data.
# in these cases, we need additional validation.
def _dirty_read_risk(ir_node):
    return ir_node.encoding == Encoding.ABI and ir_node.location == MEMORY


# child elements which have dynamic length, and could overflow the buffer
# even if the start of the item is in-bounds.
def _abi_payload_size(ir_node):
    SCALE = ir_node.location.word_scale
    assert SCALE == 32  # we must be in some byte-addressable region, like memory
    OFFSET = DYNAMIC_ARRAY_OVERHEAD * SCALE

    if isinstance(ir_node.typ, DArrayT):
        # the amount of size each value occupies in static section
        # (the amount of size it occupies in the dynamic section is handled in
        # make_setter recursion)
        item_size = ir_node.typ.value_type.abi_type.embedded_static_size()
        return ["add", OFFSET, ["mul", get_dyn_array_count(ir_node), item_size]]

    if isinstance(ir_node.typ, _BytestringT):
        return ["add", OFFSET, get_bytearray_length(ir_node)]

    raise CompilerPanic("unreachable")  # pragma: nocover


def potential_overlap(left, right):
    """
    Return true if make_setter(left, right) could potentially trample
    src or dst during evaluation.
    """
    if left.typ._is_prim_word and right.typ._is_prim_word:
        return False

    if len(left.referenced_variables & right.referenced_variables) > 0:
        return True

    if len(left.referenced_variables) > 0 and right.contains_risky_call:
        return True

    if left.contains_risky_call and len(right.referenced_variables) > 0:
        return True

    return False


# similar to `potential_overlap()`, but compares left's _reads_ vs
# right's _writes_.
# TODO: `potential_overlap()` can probably be replaced by this function,
# but all the cases need to be checked.
def read_write_overlap(left, right):
    if not isinstance(left, IRnode) or not isinstance(right, IRnode):
        return False

    if left.typ._is_prim_word and right.typ._is_prim_word:
        return False

    if len(left.referenced_variables & right.variable_writes) > 0:
        return True

    if len(left.referenced_variables) > 0 and right.contains_risky_call:
        return True

    return False


# Create an x=y statement, where the types may be compound
def make_setter(left, right, hi=None):
    check_assign(left, right)

    if potential_overlap(left, right):
        raise CompilerPanic("overlap between src and dst!")

    # we need bounds checks when decoding from memory, otherwise we can
    # get oob reads.
    #
    # the caller is responsible for calculating the bound;
    # sanity check that there is a bound if there is dirty read risk
    assert (hi is not None) == _dirty_read_risk(right)

    # For types which occupy just one word we can use single load/store
    if left.typ._is_prim_word:
        enc = right.encoding  # unwrap_location butchers encoding
        right = unwrap_location(right)
        # TODO rethink/streamline the clamp_basetype logic
        if needs_clamp(right.typ, enc):
            right = clamp_basetype(right)

        return STORE(left, right)

    # Byte arrays
    elif isinstance(left.typ, _BytestringT):
        # TODO rethink/streamline the clamp_basetype logic
        if needs_clamp(right.typ, right.encoding):
            with right.cache_when_complex("bs_ptr") as (b, right):
                copier = make_byte_array_copier(left, right)
                ret = b.resolve(["seq", clamp_bytestring(right, hi=hi), copier])
        else:
            ret = make_byte_array_copier(left, right)

        return IRnode.from_list(ret)

    elif isinstance(left.typ, DArrayT):
        # TODO should we enable this?
        # implicit conversion from sarray to darray
        # if isinstance(right.typ, SArrayType):
        #    return _complex_make_setter(left, right)

        # TODO rethink/streamline the clamp_basetype logic
        if needs_clamp(right.typ, right.encoding):
            with right.cache_when_complex("arr_ptr") as (b, right):
                copier = _dynarray_make_setter(left, right, hi=hi)
                ret = b.resolve(["seq", clamp_dyn_array(right, hi=hi), copier])
        else:
            ret = _dynarray_make_setter(left, right)

        return IRnode.from_list(ret)

    # Complex Types
    assert isinstance(left.typ, (SArrayT, TupleT, StructT))

    with right.cache_when_complex("c_right") as (b1, right):
        ret = ["seq"]
        if hi is not None:
            item_end = add_ofst(right, right.typ.abi_type.static_size())
            len_check = ["assert", ["le", item_end, hi]]
            ret.append(len_check)

        ret.append(_complex_make_setter(left, right, hi=hi))
        return b1.resolve(IRnode.from_list(ret))


# locations with no dedicated copy opcode
# (i.e. storage and transient storage)
def copy_opcode_available(left, right):
    if left.location == MEMORY and right.location == MEMORY:
        return version_check(begin="cancun")

    return left.location == MEMORY and right.location.has_copy_opcode


def _complex_make_setter(left, right, hi=None):
    if right.value == "~empty" and left.location == MEMORY:
        # optimized memzero
        return mzero(left, left.typ.memory_bytes_required)

    ret = ["seq"]

    if isinstance(left.typ, SArrayT):
        n_items = right.typ.count
        keys = [IRnode.from_list(i, typ=UINT256_T) for i in range(n_items)]

    else:
        assert is_tuple_like(left.typ)
        keys = left.typ.tuple_keys()

    if left.is_pointer and right.is_pointer and right.encoding == Encoding.VYPER:
        # both left and right are pointers, see if we want to batch copy
        # instead of unrolling the loop.
        assert left.encoding == Encoding.VYPER
        len_ = left.typ.memory_bytes_required

        # special logic for identity precompile (pre-cancun) in the else branch
        mem2mem = left.location == right.location == MEMORY

        if not copy_opcode_available(left, right) and not mem2mem:
            if _opt_codesize():
                # assuming PUSH2, a single sstore(dst (sload src)) is 8 bytes,
                # sstore(add (dst ofst), (sload (add (src ofst)))) is 16 bytes,
                # whereas loop overhead is 16-17 bytes.
                base_cost = 3
                if left._optimized.is_literal:
                    # code size is smaller since add is performed at compile-time
                    base_cost += 1
                if right._optimized.is_literal:
                    base_cost += 1
                # the formula is a heuristic, but it works.
                # (CMC 2023-07-14 could get more detailed for PUSH1 vs
                # PUSH2 etc but not worried about that too much now,
                # it's probably better to add a proper unroll rule in the
                # optimizer.)
                should_batch_copy = len_ >= 32 * base_cost
            elif _opt_gas():
                # kind of arbitrary, but cut off when code used > ~160 bytes
                should_batch_copy = len_ >= 32 * 10
            else:
                assert _opt_none()
                # don't care, just generate the most readable version
                should_batch_copy = True
        else:
            # find a cutoff for memory copy where identity is cheaper
            # than unrolled mloads/mstores
            # if MCOPY is available, mcopy is *always* better (except in
            # the 1 word case, but that is already handled by copy_bytes).
            if right.location == MEMORY and _opt_gas() and not version_check(begin="cancun"):
                # cost for 0th word - (mstore dst (mload src))
                base_unroll_cost = 12
                nth_word_cost = base_unroll_cost
                if not left._optimized.is_literal:
                    # (mstore (add N dst) (mload src))
                    nth_word_cost += 6
                if not right._optimized.is_literal:
                    # (mstore dst (mload (add N src)))
                    nth_word_cost += 6

                identity_base_cost = 115  # staticcall 4 gas dst len src len

                n_words = ceil32(len_) // 32
                should_batch_copy = (
                    base_unroll_cost + (nth_word_cost * (n_words - 1)) >= identity_base_cost
                )

            # calldata to memory, code to memory, cancun, or opt-codesize -
            # batch copy is always better.
            else:
                should_batch_copy = True

        if should_batch_copy:
            return copy_bytes(left, right, len_, len_)

    # general case, unroll
    with left.cache_when_complex("_L") as (b1, left), right.cache_when_complex("_R") as (b2, right):
        for k in keys:
            l_i = get_element_ptr(left, k, array_bounds_check=False)
            r_i = get_element_ptr(right, k, array_bounds_check=False)
            ret.append(make_setter(l_i, r_i, hi=hi))

        return b1.resolve(b2.resolve(IRnode.from_list(ret)))


def ensure_in_memory(ir_var, context):
    """
    Ensure a variable is in memory. This is useful for functions
    which expect to operate on memory variables.
    """
    if ir_var.location == MEMORY:
        return ir_var

    typ = ir_var.typ
    buf = IRnode.from_list(context.new_internal_variable(typ), typ=typ, location=MEMORY)
    do_copy = make_setter(buf, ir_var)

    return IRnode.from_list(["seq", do_copy, buf], typ=typ, location=MEMORY)


def eval_seq(ir_node):
    """Tries to find the "return" value of a `seq` statement, in order so
    that the value can be known without possibly evaluating side effects
    """
    if ir_node.value in ("seq", "with") and len(ir_node.args) > 0:
        return eval_seq(ir_node.args[-1])
    if isinstance(ir_node.value, int):
        return IRnode.from_list(ir_node)
    return None


def mzero(dst, nbytes):
    # calldatacopy from past-the-end gives zero bytes.
    # cf. YP H.2 (ops section) with CALLDATACOPY spec.
    return IRnode.from_list(
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
    # optimized form of ceil32(len) - len:
    num_zero_bytes = ["mod", ["sub", 0, "len"], 32]
    return IRnode.from_list(
        ["with", "len", len_, ["with", "dst", dst, mzero("dst", num_zero_bytes)]],
        annotation="Zero pad",
    )


# convenience rewrites for shr/sar/shl
def shr(bits, x):
    return ["shr", bits, x]


# convenience rewrites for shr/sar/shl
def shl(bits, x):
    return ["shl", bits, x]


def sar(bits, x):
    return ["sar", bits, x]


def clamp_bytestring(ir_node, hi=None):
    t = ir_node.typ
    if not isinstance(t, _BytestringT):  # pragma: nocover
        raise CompilerPanic(f"{t} passed to clamp_bytestring")

    # check if byte array length is within type max
    with get_bytearray_length(ir_node).cache_when_complex("length") as (b1, length):
        len_check = ["assert", ["le", length, t.maxlen]]

        assert (hi is not None) == _dirty_read_risk(ir_node)
        if hi is not None:
            assert t.maxlen < 2**64  # sanity check

            # NOTE: this add does not risk arithmetic overflow because
            # length is bounded by maxlen.
            # however(!) _abi_payload_size can OOG, since it loads the word
            # at `ir_node` to find the length of the bytearray, which could
            # be out-of-bounds.
            # if we didn't get OOG, we could overflow in `add`.
            item_end = add_ofst(ir_node, _abi_payload_size(ir_node))

            len_check = ["seq", ["assert", ["le", item_end, hi]], len_check]

        return IRnode.from_list(b1.resolve(len_check), error_msg=f"{ir_node.typ} bounds check")


def clamp_dyn_array(ir_node, hi=None):
    t = ir_node.typ
    assert isinstance(t, DArrayT)

    len_check = ["assert", ["le", get_dyn_array_count(ir_node), t.count]]

    assert (hi is not None) == _dirty_read_risk(ir_node)

    if hi is not None:
        assert t.count < 2**64  # sanity check

        # NOTE: this add does not risk arithmetic overflow because
        # length is bounded by count * elemsize.
        # however(!) _abi_payload_size can OOG, since it loads the word
        # at `ir_node` to find the length of the bytearray, which could
        # be out-of-bounds.
        # if we didn't get OOG, we could overflow in `add`.
        item_end = add_ofst(ir_node, _abi_payload_size(ir_node))

        # if the subtype is dynamic, the length check is performed in
        # the recursion, UNLESS the count is zero. here we perform the
        # check all the time, but it could maybe be optimized out in the
        # make_setter loop (in the common case that runtime count > 0).
        len_check = ["seq", ["assert", ["le", item_end, hi]], len_check]

    return IRnode.from_list(len_check, error_msg=f"{ir_node.typ} bounds check")


# clampers for basetype
def clamp_basetype(ir_node):
    t = ir_node.typ
    if not t._is_prim_word:  # pragma: nocover
        raise CompilerPanic(f"{t} passed to clamp_basetype")

    # copy of the input
    ir_node = unwrap_location(ir_node)

    if isinstance(t, FlagT):
        bits = len(t._flag_members)
        # assert x >> bits == 0
        ret = int_clamp(ir_node, bits, signed=False)

    elif isinstance(t, (IntegerT, DecimalT)):
        if t.bits == 256:
            ret = ir_node
        else:
            ret = int_clamp(ir_node, t.bits, signed=t.is_signed)

    elif isinstance(t, BytesM_T):
        if t.m == 32:
            ret = ir_node  # special case, no clamp.
        else:
            ret = bytes_clamp(ir_node, t.m)

    elif isinstance(t, (AddressT, InterfaceT)):
        ret = int_clamp(ir_node, 160)
    elif t in (BoolT(),):
        ret = int_clamp(ir_node, 1)
    else:  # pragma: no cover
        raise CompilerPanic(f"{t} passed to clamp_basetype")

    return IRnode.from_list(ret, typ=ir_node.typ, error_msg=f"validate {t}")


def int_clamp(ir_node, bits, signed=False):
    """Generalized clamper for integer types. Takes the number of bits,
    whether it's signed, and returns an IR node which checks it is
    in bounds. (Consumers should use clamp_basetype instead which uses
    type-based dispatch and is a little safer.)
    """
    if bits >= 256:  # pragma: nocover
        raise CompilerPanic(f"invalid clamp: {bits}>=256 ({ir_node})")

    u = "u" if not signed else ""
    msg = f"{u}int{bits} bounds check"
    with ir_node.cache_when_complex("val") as (b, val):
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

        assertion = IRnode.from_list(assertion, error_msg=msg)

        ret = b.resolve(["seq", assertion, val])

    return IRnode.from_list(ret, annotation=msg)


def bytes_clamp(ir_node: IRnode, n_bytes: int) -> IRnode:
    if not (0 < n_bytes <= 32):  # pragma: nocover
        raise CompilerPanic(f"bad type: bytes{n_bytes}")
    msg = f"bytes{n_bytes} bounds check"
    with ir_node.cache_when_complex("val") as (b, val):
        assertion = IRnode.from_list(["assert", ["iszero", shl(n_bytes * 8, val)]], error_msg=msg)
        ret = b.resolve(["seq", assertion, val])

    return IRnode.from_list(ret, annotation=msg)


# e.g. for int8, promote 255 to -1
def promote_signed_int(x, bits):
    assert bits % 8 == 0
    ret = ["signextend", bits // 8 - 1, x]
    return IRnode.from_list(ret, annotation=f"promote int{bits}")


# general clamp function for all ops and numbers
def clamp(op, arg, bound):
    with IRnode.from_list(arg).cache_when_complex("clamp_arg") as (b1, arg):
        check = IRnode.from_list(["assert", [op, arg, bound]], error_msg=f"clamp {op} {bound}")
        ret = ["seq", check, arg]
        return IRnode.from_list(b1.resolve(ret), typ=arg.typ)


def clamp_nonzero(arg):
    # TODO: use clamp("ne", arg, 0) once optimizer rules can handle it
    with IRnode.from_list(arg).cache_when_complex("should_nonzero") as (b1, arg):
        check = IRnode.from_list(["assert", arg], error_msg="check nonzero")
        ret = ["seq", check, arg]
        return IRnode.from_list(b1.resolve(ret), typ=arg.typ)


def clamp_le(arg, hi, signed):
    LE = "sle" if signed else "le"
    return clamp(LE, arg, hi)


def clamp2(lo, arg, hi, signed):
    with IRnode.from_list(arg).cache_when_complex("clamp2_arg") as (b1, arg):
        GE = "sge" if signed else "ge"
        LE = "sle" if signed else "le"
        ret = ["seq", ["assert", ["and", [GE, arg, lo], [LE, arg, hi]]], arg]
        return IRnode.from_list(b1.resolve(ret), typ=arg.typ)


# make sure we don't overrun the source buffer, checking for overflow:
# valid inputs satisfy:
#   `assert !(start+length > src_len || start+length < start)`
def check_buffer_overflow_ir(start, length, src_len):
    with start.cache_when_complex("start") as (b1, start):
        with add_ofst(start, length).cache_when_complex("end") as (b2, end):
            arithmetic_overflow = ["lt", end, start]
            buffer_oob = ["gt", end, src_len]
            ok = ["iszero", ["or", arithmetic_overflow, buffer_oob]]
            return b1.resolve(b2.resolve(["assert", ok]))
