import vyper.semantics.types as vy
from vyper.exceptions import CompilerPanic
from vyper.old_codegen.lll_node import LLLnode
from vyper.old_codegen.parser_utils import (
    add_ofst,
    get_dyn_array_count,
    get_element_ptr,
    make_setter,
    store_op,
    unwrap_location,
    zero_pad,
)
from vyper.old_codegen.types import (
    BaseType,
    ByteArrayLike,
    ByteArrayType,
    DYNAMIC_ARRAY_OVERHEAD,
    DArrayType,
    SArrayType,
    StringType,
    TupleLike,
)
from vyper.utils import ceil32


# https://solidity.readthedocs.io/en/latest/abi-spec.html#types
class ABIType:
    # aka has tail
    def is_dynamic(self):
        raise NotImplementedError("ABIType.is_dynamic")

    # size (in bytes) in the static section (aka 'head')
    # when embedded in a complex type.
    def embedded_static_size(self):
        return 32 if self.is_dynamic() else self.static_size()

    # size bound in the dynamic section (aka 'tail')
    # when embedded in a complex type.
    def embedded_dynamic_size_bound(self):
        if not self.is_dynamic():
            return 0
        return self.size_bound()

    def embedded_min_dynamic_size(self):
        if not self.is_dynamic():
            return 0
        return self.min_size()

    # size (in bytes) of the static section
    def static_size(self):
        raise NotImplementedError("ABIType.static_size")

    # max size (in bytes) in the dynamic section (aka 'tail')
    def dynamic_size_bound(self):
        if not self.is_dynamic():
            return 0
        raise NotImplementedError("ABIType.dynamic_size_bound")

    def size_bound(self):
        return self.static_size() + self.dynamic_size_bound()

    def min_size(self):
        return self.static_size() + self.min_dynamic_size()

    def min_dynamic_size(self):
        if not self.is_dynamic():
            return 0
        raise NotImplementedError("ABIType.min_dynamic_size")

    # The canonical name of the type for calculating the function selector
    def selector_name(self):
        raise NotImplementedError("ABIType.selector_name")

    # Whether the type is a tuple at the ABI level.
    # (This is important because if it does, it needs an offset.
    #   Compare the difference in encoding between `bytes` and `(bytes,)`.)
    def is_complex_type(self):
        raise NotImplementedError("ABIType.is_complex_type")

    def __repr__(self):
        return str({type(self).__name__: vars(self)})


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

    def is_complex_type(self):
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

    def is_complex_type(self):
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

    def is_complex_type(self):
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
        return self.m_elems * self.subtyp.embedded_dynamic_size_bound()

    def min_dynamic_size(self):
        return self.m_elems * self.subtyp.embedded_min_dynamic_size()

    def selector_name(self):
        return f"{self.subtyp.selector_name()}[{self.m_elems}]"

    def is_complex_type(self):
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

    def min_dynamic_size(self):
        return 32

    def selector_name(self):
        return "bytes"

    def is_complex_type(self):
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
        return 32 + self.subtyp.size_bound() * self.elems_bound

    def min_dynamic_size(self):
        return 32

    def selector_name(self):
        return f"{self.subtyp.selector_name()}[]"

    def is_complex_type(self):
        return True


class ABI_Tuple(ABIType):
    def __init__(self, subtyps):
        self.subtyps = subtyps

    def is_dynamic(self):
        return any([t.is_dynamic() for t in self.subtyps])

    def static_size(self):
        return sum([t.embedded_static_size() for t in self.subtyps])

    def dynamic_size_bound(self):
        return sum([t.embedded_dynamic_size_bound() for t in self.subtyps])

    def min_dynamic_size(self):
        return sum([t.embedded_min_dynamic_size() for t in self.subtyps])

    def is_complex_type(self):
        return True


def abi_type_of(lll_typ):
    if isinstance(lll_typ, BaseType):
        t = lll_typ.typ
        if "uint8" == t:
            return ABI_GIntM(8, False)
        elif "uint256" == t:
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
    elif isinstance(lll_typ, SArrayType):
        return ABI_StaticArray(abi_type_of(lll_typ.subtype), lll_typ.count)
    elif isinstance(lll_typ, DArrayType):
        return ABI_DynamicArray(abi_type_of(lll_typ.subtype), lll_typ.count)
    elif isinstance(lll_typ, ByteArrayType):
        return ABI_Bytes(lll_typ.maxlen)
    elif isinstance(lll_typ, StringType):
        return ABI_String(lll_typ.maxlen)
    else:
        raise CompilerPanic(f"Unrecognized type {lll_typ}")


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


# turn an lll node into a list, based on its type.
def _deconstruct_complex_type(lll_node, pos=None):
    lll_t = lll_node.typ
    assert isinstance(lll_t, (TupleLike, SArrayType))

    if lll_node.value == "multi":  # is literal
        return lll_node.args

    if isinstance(lll_t, TupleLike):
        ks = lll_t.tuple_keys()
    else:
        ks = [LLLnode.from_list(i, "uint256") for i in range(lll_t.count)]

    ret = []
    for k in ks:
        ret.append(get_element_ptr(lll_node, k, pos, array_bounds_check=False))
    return ret


# encode a child element of a complex type
def _encode_child_helper(buf, child, static_ofst, dyn_ofst, context, pos=None):
    abi_t = abi_type_of(child.typ)

    static_loc = add_ofst(LLLnode.from_list(buf), static_ofst)

    ret = ["seq"]

    if not abi_t.is_dynamic():
        # easy
        ret.append(abi_encode(static_loc, child, context, pos=pos, returns_len=False))
    else:
        # hard
        ret.append(["mstore", static_loc, dyn_ofst])

        # TODO optimize: special case where there is only one dynamic
        # member, the location is statically known.
        child_dst = ["add", buf, dyn_ofst]

        child_len = abi_encode(child_dst, child, context, pos=pos, returns_len=True)

        # increment dyn ofst for return_len
        # (optimization note:
        #   if non-returning and this is the last dyn member in
        #   the tuple, this set can be elided.)
        ret.append(["set", dyn_ofst, ["add", dyn_ofst, child_len]])

    return ret


def _encode_dyn_array_helper(dst, lll_node, context, pos):
    subtyp = lll_node.typ.subtype
    child_abi_t = abi_type_of(subtyp)

    ret = []

    with get_dyn_array_count.cache_when_complex("len") as (b, len_):
        # set the length word
        ret.append([store_op(dst.location), dst, len_])

        # prepare the loop
        # TODO rework `repeat` to use stack variable so we don't
        # have to allocate a memory variable
        t = BaseType("uint256")
        iptr = LLLnode.from_list(context.new_internal_variable(t), typ=t, location="memory")

        # offset of the i'th element in lll_node
        child_location = get_element_ptr(
            lll_node, unwrap_location(iptr), array_bounds_check=False, pos=pos
        )

        # offset of the i'th element in dst
        dst = add_ofst(dst, 32)  # jump past length word
        static_elem_size = child_abi_t.embedded_static_size()
        static_ofst = ["mul", unwrap_location(iptr), static_elem_size]
        loop_body = _encode_child_helper(
            dst, child_location, static_ofst, "dyn_child_ofst", context, pos=pos
        )
        loop = ["repeat", iptr, 0, len_, lll_node.typ.count, loop_body]

        x = ["seq", loop, "dyn_child_ofst"]
        start_dyn_ofst = ["mul", len_, static_elem_size]
        run_children = ["with", "dyn_child_ofst", start_dyn_ofst, x]

        ret.append(["set", "dyn_ofst", ["add", "dyn_ofst", run_children]])

        return b.resolve(ret)


# assume dst is a pointer to a buffer located in memory which has at
# least static_size + dynamic_size_bound allocated.
# The basic strategy is this:
#   First, it is helpful to keep track of what variables are location
#   dependent and which are location independent (offsets). Independent
#   locations will be denoted with variables named `_ofst`.
#   We keep at least one stack variable to keep track of our location
#   in the dynamic section. We keep a compiler variable `static_ofst`
#   keeping track of our current offset from the beginning of the static
#   section. (And if the destination is not known at compile time, we
#   allocate a stack item `dst` to keep track of it). So, 1-2 stack
#   variables for each level of "nesting" (as defined in the spec).
#   For each element `elem` of the lll_node:
#   - If `elem` is static, write its value to `dst + static_ofst` and
#     increment `static_ofst` by the size of `elem`.
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
def abi_encode(dst, lll_node, context, pos=None, bufsz=None, returns_len=False):
    abi_t = abi_type_of(lll_node.typ)
    size_bound = abi_t.size_bound()
    if bufsz is not None and bufsz < 32 * size_bound:
        raise CompilerPanic("buffer provided to abi_encode not large enough")

    dst = LLLnode.from_list(dst, typ=lll_node.typ, location="memory")

    lll_ret = ["seq"]

    # contains some computation, we need to only do it once.
    with lll_node.cache_when_complex("to_encode") as (b1, lll_node), dst.cache_when_complex(
        "dst"
    ) as (b2, dst):

        dyn_ofst = "dyn_ofst"  # current offset in the dynamic section

        if isinstance(lll_node.typ, BaseType):
            lll_ret.append(make_setter(dst, lll_node, context, pos=pos))
        elif isinstance(lll_node.typ, ByteArrayLike):
            # TODO optimize out repeated ceil32 calculation
            lll_ret.append(make_setter(dst, lll_node, context, pos=pos))
            lll_ret.append(zero_pad(dst))
        elif isinstance(lll_node.typ, DArrayType):
            lll_ret.append(_abi_encode_dyn_array(dst, lll_node, context, pos))

        elif isinstance(lll_node.typ, (TupleLike, SArrayType)):
            static_ofst = 0
            elems = _deconstruct_complex_type(lll_node)
            for e in elems:
                encode_lll = _encode_child_helper(dst, e, static_ofst, dyn_ofst, context, pos=pos)
                lll_ret.extend(encode_lll)
                static_ofst += abi_type_of(e.typ).embedded_static_size()

        else:
            raise CompilerPanic(f"unencodable type: {lll_node.typ}")

        # declare LLL variables.
        if returns_len:
            if not abi_t.is_dynamic():
                lll_ret.append(abi_t.embedded_static_size())
            elif isinstance(lll_node.typ, ByteArrayLike):
                # for abi purposes, return zero-padded length
                calc_len = ["ceil32", ["add", 32, ["mload", dst]]]
                lll_ret.append(calc_len)
            elif abi_t.is_complex_type():
                lll_ret.append("dyn_ofst")
            else:
                raise CompilerPanic("unknown type {lll_node.typ}")

        if abi_t.is_dynamic() and abi_t.is_complex_type():
            dyn_section_start = abi_t.static_size()
            lll_ret = ["with", dyn_ofst, dyn_section_start, lll_ret]
        else:
            pass  # skip dyn_ofst allocation if we don't need it

        annotation = f"abi_encode {lll_node.typ}"
        return b1.resolve(b2.resolve(LLLnode.from_list(lll_ret, pos=pos, annotation=annotation)))
