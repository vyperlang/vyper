
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

# assume dst is a buffer in memory which 
#def abi_encode(lll_node, dst, lll_dyn_loc):
#    # lll_dyn_loc is an LLL expression which points to the current
#    # location in the dynamic section.
#    if has_dynamic_data
