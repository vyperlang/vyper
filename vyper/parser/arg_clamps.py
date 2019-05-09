import functools

from vyper.parser.lll_node import (
    LLLnode,
)
from vyper.types.types import (
    ByteArrayLike,
    ListType,
    get_size_of_type,
    is_base_type,
)
from vyper.utils import (
    MemoryPositions,
)


def _mk_calldatacopy_copier(pos, sz, mempos):
    return ['calldatacopy', mempos, ['add', 4, pos], sz]


def _mk_codecopy_copier(pos, sz, mempos):
    return ['codecopy', mempos, ['add', '~codelen', pos], sz]


def make_arg_clamper(datapos, mempos, typ, is_init=False):
    """
    Clamps argument to type limits.
    """

    if not is_init:
        data_decl = ['calldataload', ['add', 4, datapos]]
        copier = functools.partial(_mk_calldatacopy_copier, mempos=mempos)
    else:
        data_decl = ['codeload', ['add', '~codelen', datapos]]
        copier = functools.partial(_mk_codecopy_copier, mempos=mempos)
    # Numbers: make sure they're in range
    if is_base_type(typ, 'int128'):
        return LLLnode.from_list([
            'clamp',
            ['mload', MemoryPositions.MINNUM],
            data_decl,
            ['mload', MemoryPositions.MAXNUM]
        ], typ=typ, annotation='checking int128 input')
    # Booleans: make sure they're zero or one
    elif is_base_type(typ, 'bool'):
        return LLLnode.from_list(
            ['uclamplt', data_decl, 2],
            typ=typ,
            annotation='checking bool input',
        )
    # Addresses: make sure they're in range
    elif is_base_type(typ, 'address'):
        return LLLnode.from_list(
            ['uclamplt', data_decl, ['mload', MemoryPositions.ADDRSIZE]],
            typ=typ,
            annotation='checking address input',
        )
    # Bytes: make sure they have the right size
    elif isinstance(typ, ByteArrayLike):
        return LLLnode.from_list([
            'seq',
            copier(data_decl, 32 + typ.maxlen),
            ['assert', ['le', ['calldataload', ['add', 4, data_decl]], typ.maxlen]]
        ], typ=None, annotation='checking bytearray input')
    # Lists: recurse
    elif isinstance(typ, ListType):
        o = []
        for i in range(typ.count):
            offset = get_size_of_type(typ.subtype) * 32 * i
            o.append(make_arg_clamper(datapos + offset, mempos + offset, typ.subtype, is_init))
        return LLLnode.from_list(['seq'] + o, typ=None, annotation='checking list input')
    # Otherwise don't make any checks
    else:
        return LLLnode.from_list('pass')
