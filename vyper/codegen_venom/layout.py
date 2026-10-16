"""Memory layout of struct members and their unbounded payload cells."""

from vyper.semantics.types import StructT, VyperType, is_unbounded_sequence_type
from vyper.semantics.types.utils import member_slot_size


def struct_member_offsets(struct_t: StructT) -> list[tuple[str, int, VyperType]]:
    """Return `(name, byte offset, member type)` for every member of a struct
    in memory, where an unbounded member takes a pointer cell."""
    ret = []
    offset = 0
    for name, member_t in struct_t.member_types.items():
        ret.append((name, offset, member_t))
        offset += member_slot_size(member_t)
    return ret


def unbounded_member_cells(struct_t: StructT) -> list[tuple[int, VyperType]]:
    """Return `(byte offset, member type)` for every pointer cell at a static
    offset in a struct.

    Cells of nested structs are included at their offset in the outer struct;
    cells inside the elements of an array member are not.
    """
    cells: list[tuple[int, VyperType]] = []
    for _, offset, member_t in struct_member_offsets(struct_t):
        if is_unbounded_sequence_type(member_t):
            cells.append((offset, member_t))
        elif isinstance(member_t, StructT):
            cells.extend((offset + off, t) for off, t in unbounded_member_cells(member_t))
    return cells
