# TODO this doesn't really belong in "validation"
import math
from typing import Dict, List

from vyper import ast as vy_ast
from vyper.exceptions import StorageLayoutException
from vyper.semantics.types.bases import CodeOffset, StorageSlot
from vyper.typing import StorageLayout


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
    code_offsets = set_code_offsets(vyper_module)
    storage_slots = (
        set_storage_slots_with_overrides(vyper_module, storage_layout_overrides)
        if storage_layout_overrides is not None
        else set_storage_slots(vyper_module)
    )

    return {"storage_layout": storage_slots, "code_layout": code_offsets}


class StorageAllocator:
    """
    Keep track of which storage slots have been used. If there is a collision of
    storage slots, this will raise an error and fail to compile
    """

    def __init__(self):
        self.occupied_slots: Dict[int, str] = {}

    def reserve_slot_range(self, first_slot: int, n_slots: int, var_name: str) -> None:
        """
        Reserves `n_slots` storage slots, starting at slot `first_slot`
        This will raise an error if a storage slot has already been allocated.
        It is responsibility of calling function to ensure first_slot is an int
        """
        list_to_check = [x + first_slot for x in range(n_slots)]
        self._reserve_slots(list_to_check, var_name)

    def _reserve_slots(self, slots: List[int], var_name: str) -> None:
        for slot in slots:
            self._reserve_slot(slot, var_name)

    def _reserve_slot(self, slot: int, var_name: str) -> None:
        if slot < 0 or slot >= 2 ** 256:
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

    ret: Dict[str, Dict] = {}
    reserved_slots = StorageAllocator()

    # Search through function definitions to find non-reentrant functions
    for node in vyper_module.get_children(vy_ast.FunctionDef):
        type_ = node._metadata["type"]

        # Ignore functions without non-reentrant
        if type_.nonreentrant is None:
            continue

        variable_name = f"nonreentrant.{type_.nonreentrant}"

        # re-entrant key was already identified
        if variable_name in ret:
            _slot = ret[variable_name]["slot"]
            type_.set_reentrancy_key_position(StorageSlot(_slot))
            continue

        # Expect to find this variable within the storage layout override
        if variable_name in storage_layout_overrides:
            reentrant_slot = storage_layout_overrides[variable_name]["slot"]
            # Ensure that this slot has not been used, and prevents other storage variables
            # from using the same slot
            reserved_slots.reserve_slot_range(reentrant_slot, 1, variable_name)

            type_.set_reentrancy_key_position(StorageSlot(reentrant_slot))

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

        type_ = node.target._metadata["type"]

        # Expect to find this variable within the storage layout overrides
        if node.target.id in storage_layout_overrides:
            var_slot = storage_layout_overrides[node.target.id]["slot"]
            # Calculate how many storage slots are required
            storage_length = math.ceil(type_.size_in_bytes / 32)
            # Ensure that all required storage slots are reserved, and prevents other variables
            # from using these slots
            reserved_slots.reserve_slot_range(var_slot, storage_length, node.target.id)
            type_.set_position(StorageSlot(var_slot))

            ret[node.target.id] = {"type": str(type_), "slot": var_slot}
        else:
            raise StorageLayoutException(
                f"Could not find storage_slot for {node.target.id}. "
                "Have you used the correct storage layout file?",
                node,
            )

    return ret


def set_storage_slots(vyper_module: vy_ast.Module) -> StorageLayout:
    """
    Parse module-level Vyper AST to calculate the layout of storage variables.
    Returns the layout as a dict of variable name -> variable info
    """
    # Allocate storage slots from 0
    # note storage is word-addressable, not byte-addressable
    storage_slot = 0

    ret: Dict[str, Dict] = {}

    for node in vyper_module.get_children(vy_ast.FunctionDef):
        type_ = node._metadata["type"]
        if type_.nonreentrant is None:
            continue

        variable_name = f"nonreentrant.{type_.nonreentrant}"

        # a nonreentrant key can appear many times in a module but it
        # only takes one slot. after the first time we see it, do not
        # increment the storage slot.
        if variable_name in ret:
            _slot = ret[variable_name]["slot"]
            type_.set_reentrancy_key_position(StorageSlot(_slot))
            continue

        type_.set_reentrancy_key_position(StorageSlot(storage_slot))

        # TODO this could have better typing but leave it untyped until
        # we nail down the format better
        ret[variable_name] = {"type": "nonreentrant lock", "slot": storage_slot}

        # TODO use one byte - or bit - per reentrancy key
        # requires either an extra SLOAD or caching the value of the
        # location in memory at entrance
        storage_slot += 1

    for node in vyper_module.get_children(vy_ast.VariableDecl):

        # skip non-storage variables
        if node.is_constant or node.is_immutable:
            continue

        type_ = node.target._metadata["type"]
        type_.set_position(StorageSlot(storage_slot))

        # this could have better typing but leave it untyped until
        # we understand the use case better
        ret[node.target.id] = {"type": str(type_), "slot": storage_slot}

        # CMC 2021-07-23 note that HashMaps get assigned a slot here.
        # I'm not sure if it's safe to avoid allocating that slot
        # for HashMaps because downstream code might use the slot
        # ID as a salt.
        storage_slot += math.ceil(type_.size_in_bytes / 32)

    return ret


def set_calldata_offsets(fn_node: vy_ast.FunctionDef) -> None:
    pass


def set_memory_offsets(fn_node: vy_ast.FunctionDef) -> None:
    pass


def set_code_offsets(vyper_module: vy_ast.Module) -> Dict:

    ret = {}
    offset = 0
    for node in vyper_module.get_children(vy_ast.VariableDecl, filters={"is_immutable": True}):
        type_ = node._metadata["type"]
        type_.set_position(CodeOffset(offset))

        len_ = math.ceil(type_.size_in_bytes / 32) * 32

        # this could have better typing but leave it untyped until
        # we understand the use case better
        ret[node.target.id] = {"type": str(type_), "offset": offset, "length": len_}

        offset += len_

    return ret
