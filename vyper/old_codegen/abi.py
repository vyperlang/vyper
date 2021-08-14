import vyper.semantics.types as vy
from vyper.exceptions import CompilerPanic
from vyper.old_codegen.lll_node import LLLnode
from vyper.old_codegen.parser_utils import (
    add_variable_offset,
    make_setter,
    unwrap_location,
    zero_pad,
)
from vyper.old_codegen.types import (
    BaseType,
    ByteArrayLike,
    ByteArrayType,
    ListType,
    StringType,
    TupleLike,
    TupleType,
)
from vyper.utils import ceil32


# https://solidity.readthedocs.io/en/latest/abi-spec.html#types
class ABIType:
    # aka has tail
    def is_dynamic(self):
        raise NotImplementedError("ABIType.is_dynamic")

    # size (in bytes) in the static section (aka 'head')
    # when embedded in a tuple.
    def embedded_static_size(self):
        return 32 if self.is_dynamic() else self.static_size()

    # size (in bytes) of the static section
    def static_size(self):
        raise NotImplementedError("ABIType.static_size")

    # max size (in bytes) in the dynamic section (aka 'tail')
    def dynamic_size_bound(self):
        return 0

    def size_bound(self):
        return self.static_size() + self.dynamic_size_bound()

    # The canonical name of the type for calculating the function selector
    def selector_name(self):
        raise NotImplementedError("ABIType.selector_name")

    # Whether the type is a tuple at the ABI level.
    # (This is important because if it does, it needs an offset.
    #   Compare the difference in encoding between `bytes` and `(bytes,)`.)
    def is_tuple(self):
        raise NotImplementedError("ABIType.is_tuple")


# uint<M>: unsigned integer type of M bits, 0 < M <= 256, M % 8 == 0. e.g. uint32, uint8, uint256.
# int<M>: two’s complement signed integer type of M bits, 0 < M <= 256, M % 8 == 0.
class ABI_GIntM(ABIType):
    def __init__(self, m_bits, signed):
        if not (0 < m_bits <= 256 and 0 == m_bits % 8):
            raise CompilerPanic("Invalid M provided for GIntM")

        self.m_bits = m_bits
        self.signed = signed

    def is_dynamic(self):
        return False

    def static_size(self):
        return 32

    def selector_name(self):
        return ("" if self.signed else "u") + f"int{self.m_bits}"

    def is_tuple(self):
        return False


# address: equivalent to uint160, except for the assumed interpretation
#   and language typing. For computing the function selector, address is used.
class ABI_Address(ABI_GIntM):
    def __init__(self):
        return super().__init__(160, False)

    def selector_name(self):
        return "address"


# bool: equivalent to uint8 restricted to the values 0 and 1.
#  For computing the function selector, bool is used.
#  (thought: is vyper required to check that the value is restricted to 0 and
#  1, i.e. that 248 bits or 255 bits are zeroed? - CC 20191119)
class ABI_Bool(ABI_GIntM):
    def __init__(self):
        return super().__init__(8, False)

    def selector_name(self):
        return "bool"


# fixed<M>x<N>: signed fixed-point decimal number of M bits, 8 <= M <= 256,
#   M % 8 ==0, and 0 < N <= 80, which denotes the value v as v / (10 ** N).
# ufixed<M>x<N>: unsigned variant of fixed<M>x<N>.
# fixed, ufixed: synonyms for fixed128x18, ufixed128x18 respectively.
#   For computing the function selector, fixed128x18 and ufixed128x18 have to be used.
class ABI_FixedMxN(ABIType):
    def __init__(self, m_bits, n_places, signed):
        if not (0 < m_bits <= 256 and 0 == m_bits % 8):
            raise CompilerPanic("Invalid M for FixedMxN")
        if not (0 < n_places and n_places <= 80):
            raise CompilerPanic("Invalid N for FixedMxN")

        self.m_bits = m_bits
        self.n_places = n_places
        self.signed = signed

    def is_dynamic(self):
        return False

    def static_size(self):
        return 32

    def selector_name(self):
        return ("" if self.signed else "u") + "fixed{self.m_bits}x{self.n_places}"

    def is_tuple(self):
        return False


# bytes<M>: binary type of M bytes, 0 < M <= 32.
class ABI_BytesM(ABIType):
    def __init__(self, m_bytes):
        if not 0 < m_bytes <= 32:
            raise CompilerPanic("Invalid M for BytesM")

        self.m_bytes = m_bytes

    def is_dynamic(self):
        return False

    def static_size(self):
        return 32

    def selector_name(self):
        return f"bytes{self.m_bytes}"

    def is_tuple(self):
        return False


# function: an address (20 bytes) followed by a function selector (4 bytes).
# Encoded identical to bytes24.
class ABI_Function(ABI_BytesM):
    def __init__(self):
        return super().__init__(24)

    def selector_name(self):
        return "function"


# <type>[M]: a fixed-length array of M elements, M >= 0, of the given type.
class ABI_StaticArray(ABIType):
    def __init__(self, subtyp, m_elems):
        if not m_elems >= 0:
            raise CompilerPanic("Invalid M")

        self.subtyp = subtyp
        self.m_elems = m_elems

    def is_dynamic(self):
        return self.subtyp.is_dynamic()

    def static_size(self):
        return self.m_elems * self.subtyp.static_size()

    def dynamic_size_bound(self):
        return self.m_elems * self.subtyp.dynamic_size_bound()

    def selector_name(self):
        return f"{self.subtyp.selector_name()}[{self.m_elems}]"

    def is_tuple(self):
        return True


class ABI_Bytes(ABIType):
    def __init__(self, bytes_bound):
        if not bytes_bound >= 0:
            raise CompilerPanic("Negative bytes_bound provided to ABI_Bytes")

        self.bytes_bound = bytes_bound

    def is_dynamic(self):
        return True

    # note that static_size for dynamic types is always 0
    # (and embedded_static_size is always 32)
    def static_size(self):
        return 0

    def dynamic_size_bound(self):
        # length word + data
        return 32 + ceil32(self.bytes_bound)

    def selector_name(self):
        return "bytes"

    def is_tuple(self):
        return False


class ABI_String(ABI_Bytes):
    def selector_name(self):
        return "string"


class ABI_DynamicArray(ABIType):
    def __init__(self, subtyp, elems_bound):
        if not elems_bound >= 0:
            raise CompilerPanic("Negative bound provided to DynamicArray")

        self.subtyp = subtyp
        self.elems_bound = elems_bound

    def is_dynamic(self):
        return True

    def static_size(self):
        return 32

    def dynamic_size_bound(self):
        return self.subtyp.dynamic_size_bound() * self.elems_bound

    def selector_name(self):
        return f"{self.subtyp.selector_name()}[]"

    def is_tuple(self):
        return False


class ABI_Tuple(ABIType):
    def __init__(self, subtyps):
        self.subtyps = subtyps

    def is_dynamic(self):
        return any([t.is_dynamic() for t in self.subtyps])

    def static_size(self):
        return sum([t.embedded_static_size() for t in self.subtyps])

    def dynamic_size_bound(self):
        return sum([t.dynamic_size_bound() for t in self.subtyps])

    def is_tuple(self):
        return True


def abi_type_of(lll_typ):
    if isinstance(lll_typ, BaseType):
        t = lll_typ.typ
        if "uint256" == t:
            return ABI_GIntM(256, False)
        elif "int128" == t:
            return ABI_GIntM(128, True)
        elif "int256" == t:
            return ABI_GIntM(256, True)
        elif "address" == t:
            return ABI_Address()
        elif "bytes32" == t:
            return ABI_BytesM(32)
        elif "bool" == t:
            return ABI_Bool()
        elif "decimal" == t:
            return ABI_FixedMxN(168, 10, True)
        else:
            raise CompilerPanic(f"Unrecognized type {t}")
    elif isinstance(lll_typ, TupleLike):
        return ABI_Tuple([abi_type_of(t) for t in lll_typ.tuple_members()])
    elif isinstance(lll_typ, ListType):
        return ABI_StaticArray(abi_type_of(lll_typ.subtype), lll_typ.count)
    elif isinstance(lll_typ, ByteArrayType):
        return ABI_Bytes(lll_typ.maxlen)
    elif isinstance(lll_typ, StringType):
        return ABI_String(lll_typ.maxlen)
    else:
        raise CompilerPanic(f"Unrecognized type {lll_typ}")


# utility function, constructs an LLL tuple out of a list of LLL nodes
def lll_tuple_from_args(args):
    typ = TupleType([x.typ for x in args])
    return LLLnode.from_list(["multi"] + [x for x in args], typ=typ)


# the new type system
# TODO consider moving these into properties of the type itself
def abi_type_of2(t: vy.BasePrimitive) -> ABIType:
    if isinstance(t, vy.AbstractNumericDefinition):
        return ABI_GIntM(t._bits, t._is_signed)
    if isinstance(t, vy.AddressDefinition):
        return ABI_Address()
    if isinstance(t, vy.Bytes32Definition):
        return ABI_BytesM(t.length)
    if isinstance(t, vy.BoolDefinition):
        return ABI_Bool()
    if isinstance(t, vy.DecimalDefinition):
        return ABI_FixedMxN(t._bits, t._decimal_places, True)
    if isinstance(t, vy.BytesArrayDefinition):
        return ABI_Bytes(t._length)
    if isinstance(t, vy.StringDefinition):
        return ABI_String(t._length)
    if isinstance(t, vy.TupleDefinition):
        return ABI_Tuple([abi_type_of2(t) for t in t.value_type])
    if isinstance(t, vy.StructDefinition):
        return ABI_Tuple([abi_type_of2(t) for t in t.members.values()])
    if isinstance(t, vy.ArrayDefinition):
        return ABI_StaticArray(abi_type_of2(t.value_type), t.length)
    raise CompilerPanic(f"Unrecognized type {t}")


# there are a lot of places in the calling convention where a tuple
# must be passed, so here's a convenience function for that.
def ensure_tuple(abi_typ):
    if not abi_typ.is_tuple():
        return ABI_Tuple([abi_typ])
    return abi_typ


# turn an lll node into a list, based on its type.
def o_list(lll_node, pos=None):
    lll_t = lll_node.typ
    if isinstance(lll_t, (TupleLike, ListType)):
        if lll_node.value == "multi":  # is literal
            ret = lll_node.args
        else:
            ks = (
                lll_t.tuple_keys()
                if isinstance(lll_t, TupleLike)
                else [LLLnode.from_list(i, "uint256") for i in range(lll_t.count)]
            )

            ret = [add_variable_offset(lll_node, k, pos, array_bounds_check=False) for k in ks]
        return ret
    else:
        return [lll_node]


# assume dst is a buffer located in memory which has at least
# static_size + dynamic_size_bound allocated.
# The basic strategy is this:
#   First, it is helpful to keep track of what variables are location
#   dependent and which are location independent (offsets). Independent
#   locations will be denoted with variables named `_ofst`.
#   Since we cannot know beforehand where `dst` is (it could be
#   a dynamically calculated value), we assign a stack variable
#   to its value, `dst_loc`. In addition we need at most one more stack
#   variable to keep track of our location in the dynamic section.
#   It will also be convenient to keep the original `dst` around as a
#   stack variable `dst_ptr`. So, 2-3 stack variables for each level of
#   nesting (as defined in the spec).
#   For each element `elem` of the lll_node:
#   - If `elem` is static, write its value to `dst_loc` and
#     increment `dst_loc` by the size of `elem`.
#   - If it is dynamic, ensure we have initialized a pointer (a stack
#     variable named `dyn_ofst` set to the start of the dynamic section
#     (i.e. static_size of lll_node). Write the 'tail' of `elem` to the
#     dynamic section, then write current `dyn_ofst` to `dst_loc`, and
#     then increment `dyn_ofst` by the number of bytes written. Note
#     that in this step we may recurse, and the child call should return
#     a stack item representing how many bytes were written.
#     WARNING: abi_encode(bytes) != abi_encode((bytes,)) (a tuple
#     with a single bytes member). The former is encoded as <len> <data>,
#     the latter is encoded as <ofst> <len> <data>.
# performance note: takes O(n^2) compilation time
# where n is depth of data type, could be optimized but unlikely
# that users will provide deeply nested data.
# returns_len is a calling convention parameter; if set to true,
# the abi_encode routine will push the output len onto the stack,
# otherwise it will return 0 items to the stack.
def abi_encode(dst, lll_node, pos=None, bufsz=None, returns_len=False):
    parent_abi_t = abi_type_of(lll_node.typ)
    size_bound = parent_abi_t.size_bound()
    if bufsz is not None and bufsz < 32 * size_bound:
        raise CompilerPanic("buffer provided to abi_encode not large enough")

    lll_ret = ["seq"]
    dyn_ofst = "dyn_ofst"  # current offset in the dynamic section
    dst_begin = "dst"  # pointer to beginning of buffer
    dst_loc = "dst_loc"  # pointer to write location in static section
    os = o_list(lll_node, pos=pos)

    for i, o in enumerate(os):
        abi_t = abi_type_of(o.typ)

        if parent_abi_t.is_tuple():
            if abi_t.is_dynamic():
                lll_ret.append(["mstore", dst_loc, dyn_ofst])
                # recurse
                child_dst = ["add", dst_begin, dyn_ofst]
                child = abi_encode(child_dst, o, pos=pos, returns_len=True)
                # increment dyn ofst for the return
                # (optimization note:
                #   if non-returning and this is the last dyn member in
                #   the tuple, this set can be elided.)
                lll_ret.append(["set", dyn_ofst, ["add", dyn_ofst, child]])
            else:
                # recurse
                lll_ret.append(abi_encode(dst_loc, o, pos=pos, returns_len=False))

        elif isinstance(o.typ, BaseType):
            d = LLLnode(dst_loc, typ=o.typ, location="memory")
            lll_ret.append(make_setter(d, o, location=d.location, pos=pos))
        elif isinstance(o.typ, ByteArrayLike):
            d = LLLnode.from_list(dst_loc, typ=o.typ, location="memory")
            lll_ret.append(["seq", make_setter(d, o, location=d.location, pos=pos), zero_pad(d)])
        else:
            raise CompilerPanic(f"unreachable type: {o.typ}")

        if i + 1 == len(os):
            pass  # optimize out the last increment to dst_loc
        else:  # note: always false for non-tuple types
            sz = abi_t.embedded_static_size()
            lll_ret.append(["set", dst_loc, ["add", dst_loc, sz]])

    # declare LLL variables.
    if returns_len:
        if not parent_abi_t.is_dynamic():
            lll_ret.append(parent_abi_t.embedded_static_size())
        elif parent_abi_t.is_tuple():
            lll_ret.append("dyn_ofst")
        elif isinstance(lll_node.typ, ByteArrayLike):
            # for abi purposes, return zero-padded length
            calc_len = ["ceil32", ["add", 32, ["mload", dst_loc]]]
            lll_ret.append(calc_len)
        else:
            raise CompilerPanic("unknown type {lll_node.typ}")

    if not (parent_abi_t.is_dynamic() and parent_abi_t.is_tuple()):
        pass  # optimize out dyn_ofst allocation if we don't need it
    else:
        dyn_section_start = parent_abi_t.static_size()
        lll_ret = ["with", "dyn_ofst", dyn_section_start, lll_ret]

    lll_ret = ["with", dst_begin, dst, ["with", dst_loc, dst_begin, lll_ret]]

    return LLLnode.from_list(lll_ret, pos=pos)


# lll_node is the destination LLL item, src is the input buffer.
# recursively copy the buffer items into lll_node, based on its type.
# src: pointer to beginning of buffer
# src_loc: pointer to read location in static section
def abi_decode(lll_node, src, pos=None):
    os = o_list(lll_node, pos=pos)
    lll_ret = ["seq"]
    parent_abi_t = abi_type_of(lll_node.typ)
    for i, o in enumerate(os):
        abi_t = abi_type_of(o.typ)
        src_loc = LLLnode("src_loc", typ=o.typ, location=src.location)
        if parent_abi_t.is_tuple():
            if abi_t.is_dynamic():
                child_loc = ["add", "src", unwrap_location(src_loc)]
                child_loc = LLLnode.from_list(child_loc, typ=o.typ, location=src.location)
            else:
                child_loc = src_loc
            # descend into the child tuple
            lll_ret.append(abi_decode(o, child_loc, pos=pos))
        else:
            lll_ret.append(make_setter(o, src_loc, location=o.location, pos=pos))

        if i + 1 == len(os):
            pass  # optimize out the last pointer increment
        else:
            sz = abi_t.embedded_static_size()
            lll_ret.append(["set", "src_loc", ["add", "src_loc", sz]])

    lll_ret = ["with", "src", src, ["with", "src_loc", "src", lll_ret]]

    return lll_ret


def _add_ofst(loc, ofst):
    if isinstance(loc.value, int):
        return LLLnode(loc.value + ofst)
    return ["add", loc, ofst]


# decode a buffer containing abi-encoded data structure in place
# for dynamical data, a layer of indirection will be
# added for every level of nesting. for instance,
# `lazy_abi_decode(<int128>, <320>)`
# might return (mload 320),
# whereas
# `lazy_abi_decode(<(int128,bytes)>, <320>)`
# might return
# (multi
#   (mload 320/*int128*/)
#   (mload (add 320/*buf start*/ (mload 352/*ofst loc*/))))
# thought of the day: it might be nice to have an argument like `sanitize`
# which will add well-formedness checks (clamps) for all inputs.
def lazy_abi_decode(typ, src, pos=None):
    if isinstance(typ, (ListType, TupleLike)):
        if isinstance(typ, TupleLike):
            ts = typ.tuple_members()
        else:
            ts = [typ.subtyp for _ in range(typ.count)]
        ofst = 0
        os = []
        for t in ts:
            child_abi_t = abi_type_of(t)
            loc = _add_ofst(src, ofst)
            if child_abi_t.is_dynamic():
                # load the offset word, which is the
                # (location-independent) offset from the start of the
                # src buffer.
                dyn_ofst = unwrap_location(ofst)
                loc = _add_ofst(src, dyn_ofst)
            os.append(lazy_abi_decode(t, loc, pos))
            ofst += child_abi_t.embedded_static_size()

        return LLLnode.from_list(["multi"] + os, typ=typ, pos=pos)

    elif isinstance(typ, (BaseType, ByteArrayLike)):
        return unwrap_location(src)
    else:
        raise CompilerPanic(f"unknown type for lazy_abi_decode {typ}")
