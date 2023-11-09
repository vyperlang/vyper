from vyper.exceptions import InvalidABIType
from vyper.utils import ceil32


# https://solidity.readthedocs.io/en/latest/abi-spec.html#types
class ABIType:
    # TODO should these methods be properties

    # aka has tail
    def is_dynamic(self):
        raise NotImplementedError("ABIType.is_dynamic")

    # size (in bytes) in the static section (aka 'head')
    # when embedded in a complex type.
    def embedded_static_size(self):
        if self.is_dynamic():
            return 32
        return self.static_size()

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
            raise InvalidABIType("Invalid M provided for GIntM")

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
            raise InvalidABIType("Invalid M for FixedMxN")
        if not (0 < n_places and n_places <= 80):
            raise InvalidABIType("Invalid N for FixedMxN")

        self.m_bits = m_bits
        self.n_places = n_places
        self.signed = signed

    def is_dynamic(self):
        return False

    def static_size(self):
        return 32

    def selector_name(self):
        return ("" if self.signed else "u") + f"fixed{self.m_bits}x{self.n_places}"

    def is_complex_type(self):
        return False


# bytes<M>: binary type of M bytes, 0 < M <= 32.
class ABI_BytesM(ABIType):
    def __init__(self, m_bytes):
        if not 0 < m_bytes <= 32:
            raise InvalidABIType("Invalid M for BytesM")

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
            raise InvalidABIType("Invalid M")

        self.subtyp = subtyp
        self.m_elems = m_elems

    def is_dynamic(self):
        return self.subtyp.is_dynamic()

    def static_size(self):
        return self.m_elems * self.subtyp.embedded_static_size()

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
            raise InvalidABIType("Negative bytes_bound provided to ABI_Bytes")

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
            raise InvalidABIType("Negative bound provided to DynamicArray")

        self.subtyp = subtyp
        self.elems_bound = elems_bound

    def is_dynamic(self):
        return True

    def static_size(self):
        return 0

    def dynamic_size_bound(self):
        subtyp_size = self.subtyp.embedded_static_size() + self.subtyp.embedded_dynamic_size_bound()

        # length + size of embedded children
        return 32 + subtyp_size * self.elems_bound

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

    def selector_name(self):
        return "(" + ",".join(t.selector_name() for t in self.subtyps) + ")"
