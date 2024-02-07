from typing import Optional

from vyper import ast as vy_ast
from vyper.exceptions import StorageLayoutException
from vyper.semantics.analysis.base import VarOffset
from vyper.typing import StorageLayout
from vyper.utils import ceil32


def set_data_positions(
    vyper_module: vy_ast.Module, storage_layout_overrides: StorageLayout = None
) -> StorageLayout:
    """
    Parse the annotated Vyper AST, determine data positions for all variables,
    and annotate the AST nodes with the position data.

    Arguments
    ---------
    vyper_module : vy_ast.Module
        Top-level Vyper AST node that has already been annotated with type data.
    """
    code_offsets = set_code_offsets_r(vyper_module)

    if storage_layout_overrides is None:
        storage_slots = set_storage_slots_r(vyper_module)
    else:
        storage_slots = set_storage_slots_with_overrides(vyper_module, storage_layout_overrides)

    return {"storage_layout": storage_slots, "code_layout": code_offsets}


class StorageAllocator:
    """
    Keep track of which storage slots have been used. If there is a collision of
    storage slots, this will raise an error and fail to compile
    """

    def __init__(self):
        self.occupied_slots: dict[int, str] = {}

    def reserve_slot_range(self, first_slot: int, n_slots: int, var_name: str) -> None:
        """
        Reserves `n_slots` storage slots, starting at slot `first_slot`
        This will raise an error if a storage slot has already been allocated.
        It is responsibility of calling function to ensure first_slot is an int
        """
        list_to_check = [x + first_slot for x in range(n_slots)]
        self._reserve_slots(list_to_check, var_name)

    def _reserve_slots(self, slots: list[int], var_name: str) -> None:
        for slot in slots:
            self._reserve_slot(slot, var_name)

    def _reserve_slot(self, slot: int, var_name: str) -> None:
        if slot < 0 or slot >= 2**256:
            raise StorageLayoutException(
                f"Invalid storage slot for var {var_name}, out of bounds: {slot}"
            )
        if slot in self.occupied_slots:
            collided_var = self.occupied_slots[slot]
            raise StorageLayoutException(
                f"Storage collision! Tried to assign '{var_name}' to slot {slot} but it has "
                f"already been reserved by '{collided_var}'"
            )
        self.occupied_slots[slot] = var_name


def set_storage_slots_with_overrides(
    vyper_module: vy_ast.Module, storage_layout_overrides: StorageLayout
) -> StorageLayout:
    """
    Parse module-level Vyper AST to calculate the layout of storage variables.
    Returns the layout as a dict of variable name -> variable info
    """

    ret: dict[str, dict] = {}
    reserved_slots = StorageAllocator()

    # Search through function definitions to find non-reentrant functions
    for node in vyper_module.get_children(vy_ast.FunctionDef):
        type_ = node._metadata["func_type"]

        # Ignore functions without non-reentrant
        if type_.nonreentrant is None:
            continue

        variable_name = f"nonreentrant.{type_.nonreentrant}"

        # re-entrant key was already identified
        if variable_name in ret:
            _slot = ret[variable_name]["slot"]
            type_.set_reentrancy_key_position(VarOffset(_slot))
            continue

        # Expect to find this variable within the storage layout override
        if variable_name in storage_layout_overrides:
            reentrant_slot = storage_layout_overrides[variable_name]["slot"]
            # Ensure that this slot has not been used, and prevents other storage variables
            # from using the same slot
            reserved_slots.reserve_slot_range(reentrant_slot, 1, variable_name)

            type_.set_reentrancy_key_position(VarOffset(reentrant_slot))

            ret[variable_name] = {"type": "nonreentrant lock", "slot": reentrant_slot}
        else:
            raise StorageLayoutException(
                f"Could not find storage_slot for {variable_name}. "
                "Have you used the correct storage layout file?",
                node,
            )

    # Iterate through variables
    for node in vyper_module.get_children(vy_ast.VariableDecl):
        # Ignore immutable parameters
        if node.get("annotation.func.id") == "immutable":
            continue

        varinfo = node.target._metadata["varinfo"]

        # Expect to find this variable within the storage layout overrides
        if node.target.id in storage_layout_overrides:
            var_slot = storage_layout_overrides[node.target.id]["slot"]
            storage_length = varinfo.typ.storage_size_in_words
            # Ensure that all required storage slots are reserved, and prevents other variables
            # from using these slots
            reserved_slots.reserve_slot_range(var_slot, storage_length, node.target.id)
            varinfo.set_position(VarOffset(var_slot))

            ret[node.target.id] = {"type": str(varinfo.typ), "slot": var_slot}
        else:
            raise StorageLayoutException(
                f"Could not find storage_slot for {node.target.id}. "
                "Have you used the correct storage layout file?",
                node,
            )

    return ret


class SimpleAllocator:
    def __init__(self, max_slot: int = 2**256, starting_slot: int = 0):
        # Allocate storage slots from 0
        # note storage is word-addressable, not byte-addressable
        self._slot = starting_slot
        self._max_slot = max_slot

    def allocate_slot(self, n, var_name, node=None):
        ret = self._slot
        if self._slot + n >= self._max_slot:
            raise StorageLayoutException(
                f"Invalid storage slot, tried to allocate"
                f" slots {self._slot} through {self._slot + n}",
                node,
            )
        self._slot += n
        return ret


def _get_allocatable(vyper_module: vy_ast.Module) -> list[vy_ast.VyperNode]:
    allocable = (vy_ast.InitializesDecl, vy_ast.VariableDecl)
    return [node for node in vyper_module.body if isinstance(node, allocable)]


def set_storage_slots_r(
    vyper_module: vy_ast.Module, allocator: Optional[SimpleAllocator] = None
) -> StorageLayout:
    """
    Parse module-level Vyper AST to calculate the layout of storage variables.
    Returns the layout as a dict of variable name -> variable info
    """
    if allocator is None:
        allocator = SimpleAllocator(max_slot=2**256)

    ret: dict[str, dict] = {}

    for node in vyper_module.get_children(vy_ast.FunctionDef):
        type_ = node._metadata["func_type"]
        if type_.nonreentrant is None:
            continue

        variable_name = f"nonreentrant.{type_.nonreentrant}"

        # a nonreentrant key can appear many times in a module but it
        # only takes one slot. after the first time we see it, do not
        # increment the storage slot.
        if variable_name in ret:
            _slot = ret[variable_name]["slot"]
            type_.set_reentrancy_key_position(VarOffset(_slot))
            continue

        # TODO use one byte - or bit - per reentrancy key
        # requires either an extra SLOAD or caching the value of the
        # location in memory at entrance
        slot = allocator.allocate_slot(1, variable_name, node)

        type_.set_reentrancy_key_position(VarOffset(slot))

        # TODO this could have better typing but leave it untyped until
        # we nail down the format better
        ret[variable_name] = {"type": "nonreentrant lock", "slot": slot}

    for node in _get_allocatable(vyper_module):
        if isinstance(node, vy_ast.InitializesDecl):
            module_t = node._metadata["initializes_info"].module_info.module_t
            set_storage_slots_r(module_t._module, allocator)
            continue

        assert isinstance(node, vy_ast.VariableDecl)

        # skip non-storage variables
        if node.is_constant or node.is_immutable:
            continue

        varinfo = node.target._metadata["varinfo"]
        type_ = varinfo.typ

        # CMC 2021-07-23 note that HashMaps get assigned a slot here.
        # I'm not sure if it's safe to avoid allocating that slot
        # for HashMaps because downstream code might use the slot
        # ID as a salt.
        n_slots = type_.storage_size_in_words
        # CMC 2024-02-07 note we use the same allocator for transient
        # storage and regular storage. this is slightly inefficient
        # in terms of code size (since we don't get to reuse the same
        # small integer slots)
        slot = allocator.allocate_slot(n_slots, node.target.id, node)

        varinfo.set_position(VarOffset(slot))

        # this could have better typing but leave it untyped until
        # we understand the use case better
        ret[node.target.id] = {"type": str(type_), "slot": slot}

    return ret


def set_code_offsets_r(vyper_module: vy_ast.Module, allocator: SimpleAllocator = None) -> dict:
    if allocator is None:
        allocator = SimpleAllocator(max_slot=0x6000)

    ret = {}

    for node in _get_allocatable(vyper_module):
        if isinstance(node, vy_ast.InitializesDecl):
            module_t = node._metadata["initializes_info"].module_info.module_t
            set_code_offsets_r(module_t._module, allocator)
            continue

        assert isinstance(node, vy_ast.VariableDecl)
        if not node.is_immutable:
            continue

        varinfo = node.target._metadata["varinfo"]
        type_ = varinfo.typ
        len_ = ceil32(type_.size_in_bytes)
        offset = allocator.allocate_slot(len_, node.target.id, node)
        varinfo.set_position(VarOffset(offset))

        # this could have better typing but leave it untyped until
        # we understand the use case better
        ret[node.target.id] = {"type": str(type_), "offset": offset, "length": len_}

    return ret
