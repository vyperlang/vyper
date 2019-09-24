
# https://solidity.readthedocs.io/en/latest/abi-spec.html#types
class ABIType:
    # aka has tail
    def is_dynamic(self):
        raise NotImplementedError('ABIType.is_dynamic')

    # size in the static section, (aka 'head')
    def static_size(self):
        raise NotImplementedError('ABIType.static_size')

    # max size in the dynamic section (aka 'tail')
    # undefined if self.is_dynamic() evaluates to False.
    def dynamic_size_bound(self):
        raise NotImplementedError('ABIType.dynamic_size_bound')

    # The canonical name of the type for calculating the function selector
    def selector_name():
        raise NotImplementedError('ABIType.selector_name')

# uint<M>: unsigned integer type of M bits, 0 < M <= 256, M % 8 == 0. e.g. uint32, uint8, uint256.
# int<M>: two’s complement signed integer type of M bits, 0 < M <= 256, M % 8 == 0.
class ABI_GIntM(ABIType):
    def __init__(m_bits, signed):
        if not (0 < m_bits and m_bits <= 256) or not (0 == m_bits % 8) :
            raise CompilerPanic('Invalid M provided for GIntM')

        self.m_bits = m_bits
        self.signed = signed

    def is_dynamic(self):
        return False

    def static_size(self):
        return 1

    def selector_name(self):
        return ('' if self.signed else 'u') + f'int{self.m_bits}'

# address: equivalent to uint160, except for the assumed interpretation and language typing. For computing the function selector, address is used.
class ABI_Address(ABI_GIntM):
    def __init__(self):
        return super(160, False) # ABI is the same

# bool: equivalent to uint8 restricted to the values 0 and 1. For computing the function selector, bool is used.
class ABI_Bool(ABI_GIntM):
    # "equivalent to uint8 restricted to the values 0 and 1. For computing the function selector, bool is used."
    # ^ is vyper required to check that the value is restricted to 0 and 1,
    # i.e. that 248 bits or 255 bits are zeroed?
    def __init__(self):
        return super(8, False)

# fixed<M>x<N>: signed fixed-point decimal number of M bits, 8 <= M <= 256, M % 8 ==0, and 0 < N <= 80, which denotes the value v as v / (10 ** N).
# ufixed<M>x<N>: unsigned variant of fixed<M>x<N>.
# fixed, ufixed: synonyms for fixed128x18, ufixed128x18 respectively. For computing the function selector, fixed128x18 and ufixed128x18 have to be used.
class ABI_FixedMxN(ABIType):
    def __init__(self, m_bits, n_places, signed):
        if not (0 < m_bits and m_bits <= 256 and 0==m%8):
            raise CompilerPanic('Invalid M for FixedMxN')
        if not (0 < n_places and n_places <= 80):
            raise CompilerPanic('Invalid N for FixedMxN')

        self.m_bits = m_bits
        self.n_places = n_places
        self.signed = signed

    def is_dynamic(self):
        return False

    def static_size(self):
        return 1

    def selector_name(self):
        return ('' if self.signed else 'u') + \
                'fixed{self.m_bits}x{self.n_places}'

# bytes<M>: binary type of M bytes, 0 < M <= 32.
class ABI_BytesM(ABIType):
    def __init__(self, m_bytes):
        if not m_bytes <= 32:
            raise CompilerPanic('Invalid M for BytesM')

        self.m_bytes = m_bytes

    def is_dynamic(self):
        return False

    def static_size(self):
        return 1

    def selector_name(self):
        return f'bytes{self.m_bytes}'

# function: an address (20 bytes) followed by a function selector (4 bytes). Encoded identical to bytes24.
class ABI_Function(ABI_BytesM):
    def __init__(self):
        return super(24)

    def selector_name(self):
        return 'function'

# <type>[M]: a fixed-length array of M elements, M >= 0, of the given type.
class ABI_StaticArray(ABIType):
    def __init__(self, subtyp, m_elems):
        if not m_elems >= 0:
            raise CompilerPanic('Invalid M')

        self.subtyp = subtyp
        self.m_elems = m_elems

    def is_dynamic(self):
        return self.subtyp.is_dynamic()

    def static_size(self):
        return self.m_elems * self.subtyp.static_size()

    def dynamic_size_bound(self):
        return self.m_elems * self.subtyp.dynamic_size_bound()

    def selector_name(self):
        return f'{self.subtyp.selector_name()}[{self.m_elems}]'

def ABI_Bytes(ABIType):
    def __init__(self, bytes_bound):
        if not bytes_bound >= 0:
            raise CompilerPanic('Negative bytes_bound provided to ABI_Bytes')

        self.bytes_bound = bytes_bound

    def is_dynamic(self):
        return True

    def static_size(self):
        return 1

    def dynamic_size_bound(self):
        # length word + data
        return 1 + ceil32(self.bytes_bound) // 32

    def selector_name(self):
        return 'bytes'

def ABI_String(ABI_Bytes):
    def selector_name(self):
        return 'string'

def ABI_DynamicArray(ABIType):
    def __init__(self, subtyp, elems_bound):
        if not elems_bound >= 0:
            raise CompilerPanic('Negative bound provided to DynamicArray')

        self.subtyp = subtyp
        self.elems_bound = elems_bound

    def is_dynamic(self):
        return True

    def static_size(self):
        return 1

    def dynamic_size_bound(self):
        return self.subtyp.dynamic_size_bound() * self.elems_bound

    def selector_name(self):
        return f'{self.subtyp.selector_name()}[]'

class ABI_Tuple(ABIType):
    def __init__(self, subtyps):
        self.subtyps = subtyps

    def is_dynamic(self):
        return any([t.is_dynamic() for t in self.subtyps])

    def static_size(self):
        return 1 if self.is_dynamic() else \
                sum([t.static_size() for t in self.subtyps])

    def dynamic_size_bound(self):
        if not self.is_dynamic():
            raise CompilerPanic('denied')

        return sum([0 if not t.is_dynamic() else t.dynamic_size_bound()
            for t in self.subtyps])

def abi_type_of(lll_typ):
    if isinstance(lll_typ, BaseType):
        t = lll_typ.typ
        if 'uint256' == t:
            return ABI_IntM(256, False)
        elif 'int128' == t:
            return ABI_IntM(128, False)
        elif 'address' == t:
            return ABI_Address()
        elif 'bytes32' == t:
            return ABI_Bytes(32)
        elif 'bool' == t:
            return ABI_Bool
        elif 'decimal' == t:
            return ABI_FixedMxN(168, 10)
        else:
            raise CompilerPanic(f'Unrecognized type {t}')
    elif isinstance(lll_typ, TupleLike):
        return ABI_Tuple([abi_type_of(t) for t in lll_type.tuple_members()])
    elif isinstance(lll_typ, ListType):
        return ABI_StaticArray(abi_type_of(lll_typ.subtype), lll_typ.count)
    elif isinstance(lll_typ, ByteArrayType):
        return ABI_Bytes(lll_typ.maxlen)
    elif isinstance(lll_typ, StringType):
        return ABI_String(lll_typ.maxlen)
    else:
        raise CompilerPanic(f'Unrecognized type {t}')

# turn an lll node into a list, based on its type.
def o_list(lll_node, pos=None):
    lll_t = lll_node.typ
    if isinstance(lll_t, (TupleLike, ListType)):
        if lll_node.value == 'multi': # is literal
            return lll_node.args
        else:
            ks = lll_t.tuple_keys() if isinstance(lll_t, TupleLike) else \
                    [LLLnode.from_list(i) for i in range(lll_t.count)]

            return [add_variable_offset(lll_node, k, pos, array_bounds_check=False)
                    for k in ks]
    else:
        return [lll_node]


# assume dst is a buffer in memory which has at least
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
#   stack variable.  So, 2-3 stack variables for each level of nesting
#   (as defined in the spec).
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
def abi_encode(lll_node, dst, pos=None, bufsz=None, returns=False):
    if not isinstance(dst, int):
        raise CompilerPanic('abi_encode requires a statically known destination')
    parent_abi_t = abi_type_of(lll_node.typ)
    if bufsz < parent_abi_t.static_size() + parent_abi_t.dynamic_size_bound():
        raise CompilerPanic('buffer provided to abi_encode not large enough')

    lll_ret  = []
    dyn_ofst = 'dyn_ofst' # current offset in the dynamic section
    dst      = 'dst'      # pointer to beginning of buffer
    dst_loc  = 'dst_loc'  # pointer to write location in static section
    for o in o_list(lll_node, pos):
        abi_t = abi_type_of(o)

        if abi_t.is_dynamic():
            lll_ret.append(['mstore', 'dst_loc', 'dyn_ofst'])
            calc_dyn_loc = ['add', 'dst', 'dyn_ofset']
            if isinstance(o.typ, ByteArrayLike):
                d = LLLnode.from_list(['dyn_loc'], typ=o.typ)
                child = ['with', 'dyn_loc', calc_dyn_loc,
                            ['seq',
                                make_byte_array_copier(d, o, pos=pos),
                                zero_pad(d, maxlen=d.typ.maxlen),
                                ['mload', d]]])
            else:
                child = abi_encode(o, calc_dyn_loc, pos, returns=True) # recurse
            lll_ret.append(
                    ['set', 'dyn_ofst',
                        ['add', 'dyn_ofst', child]])
        else:
            # could be O(n^2) where n is depth of data type.
            if isinstance(o.typ, BaseType):
                lll_ret.append(['mstore', 'dst', o])
            else:
                # children guaranteed to be static.
                lll_ret.append(abi_encode(o, dst_loc, pos))

        sz = abi_t.static_size()
        lll_ret.append(['set', dst_loc, ['add', dst_loc, sz]])

    if returns:
        lll_ret = ['seq', lll_ret, 'dyn_ofst']
    else:
        lll_ret = ['seq', lll_ret]
    if parent_abi_t.is_dynamic():
        lll_ret = ['with', 'dyn_ofst', parent_abi_t.static_size(), lll_ret]
    return LLLnode.from_list(lll_ret)
