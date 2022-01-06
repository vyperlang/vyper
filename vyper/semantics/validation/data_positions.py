# TODO this doesn't really belong in "validation"
import math
from typing import Dict, List

from vyper import ast as vy_ast
from vyper.semantics.types.bases import CodeOffset, StorageSlot
from vyper.typing import StorageLayout


def set_data_positions(
    vyper_module: vy_ast.Module, storage_layout_overrides: StorageLayout = {}
) -> StorageLayout:
    """
    Parse the annotated Vyper AST, determine data positions for all variables,
    and annotate the AST nodes with the position data.

    Arguments
    ---------
    vyper_module : vy_ast.Module
        Top-level Vyper AST node that has already been annotated with type data.
    """
    set_code_offsets(vyper_module)
    return (
        set_storage_slots_with_overrides(vyper_module, storage_layout_overrides)
        if storage_layout_overrides
        else set_storage_slots(vyper_module)
    )


class StorageCollision:
    occupied_slots: Dict[int, bool] = {}

    def is_slot_free(self, slot_number: int) -> bool:
        return not self.occupied_slots.get(slot_number)

    def are_all_slots_free(self, slots_to_check: List[int]) -> bool:
        return not any(self.occupied_slots.get(slot) for slot in slots_to_check)

    def reserve_slot(self, slot_number: int):
        self.occupied_slots[slot_number] = True

    def reserve_slots(self, slots_to_reserve: List[int]):
        for slot in slots_to_reserve:
            self.occupied_slots[slot] = True

    def check_and_reserve_slot(self, slot_number: int) -> bool:
        if self.occupied_slots.get(slot_number):
            raise ValueError(f"Storage collision! Slot {slot_number} has already been reserved")
        self.occupied_slots[slot_number] = True

    def check_and_reserve_slots(self, slots: List[int]) -> bool:
        for slot in slots:
            if self.occupied_slots.get(slot):
                raise ValueError(f"Storage collision! Slot {slot} has already been reserved")
            self.occupied_slots[slot] = True

    def check_and_reserve_slot_and_length(self, first_slot: int, length_of_slots: int) -> bool:
        list_to_check = [x + first_slot for x in range(length_of_slots)]
        return self.check_and_reserve_slots(list_to_check)


def set_storage_slots_with_overrides(
    vyper_module: vy_ast.Module, storage_layout_overrides: StorageLayout
) -> StorageLayout:
    """
    Parse module-level Vyper AST to calculate the layout of storage variables.
    Returns the layout as a dict of variable name -> variable info
    """
    # Allocate storage slots from 0
    # note storage is word-addressable, not byte-addressable

    ret: Dict[str, Dict] = {}
    reserved_slots = StorageCollision()

    reserved_slots.check_and_reserve_slot_and_length(0, 3)

    for node in vyper_module.get_children(vy_ast.FunctionDef):
        type_ = node._metadata["type"]
        if type_.nonreentrant is None:
            continue

        variable_name = f"nonreentrant.{type_.nonreentrant}"

        if variable_name in storage_layout_overrides:
            reentrant_slot = storage_layout_overrides[variable_name]["slot"]
            type_.set_reentrancy_key_position(StorageSlot(reentrant_slot))

            reserved_slots.check_and_reserve_slot(reentrant_slot)

            ret[variable_name] = {
                "type": "nonreentrant lock",
                "location": "storage",
                "slot": reentrant_slot,
            }
        else:
            raise KeyError(
                f"Could not find storage_slot for {variable_name}. Have you used the correct storage layout file?"
            )

    for node in vyper_module.get_children(vy_ast.AnnAssign):

        if node.get("annotation.func.id") == "immutable":
            continue

        type_ = node.target._metadata["type"]

        if node.target.id in storage_layout_overrides:
            var_slot = storage_layout_overrides[node.target.id]["slot"]
            type_.set_position(StorageSlot(var_slot))

            storage_length = math.ceil(type_.size_in_bytes / 32)
            reserved_slots.check_and_reserve_slot_and_length(var_slot, storage_length)

            # this could have better typing but leave it untyped until
            # we understand the use case better
            ret[node.target.id] = {"type": str(type_), "location": "storage", "slot": var_slot}
        else:
            raise KeyError(
                f"Could not find storage_slot for {node.target.id}. Have you used the correct storage layout file?"
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
        ret[variable_name] = {
            "type": "nonreentrant lock",
            "location": "storage",
            "slot": storage_slot,
        }

        # TODO use one byte - or bit - per reentrancy key
        # requires either an extra SLOAD or caching the value of the
        # location in memory at entrance
        storage_slot += 1

    for node in vyper_module.get_children(vy_ast.AnnAssign):

        if node.get("annotation.func.id") == "immutable":
            continue

        type_ = node.target._metadata["type"]
        type_.set_position(StorageSlot(storage_slot))

        # this could have better typing but leave it untyped until
        # we understand the use case better
        ret[node.target.id] = {"type": str(type_), "location": "storage", "slot": storage_slot}

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


def set_code_offsets(vyper_module: vy_ast.Module) -> None:

    offset = 0
    for node in vyper_module.get_children(
        vy_ast.AnnAssign, filters={"annotation.func.id": "immutable"}
    ):
        type_ = node._metadata["type"]
        type_.set_position(CodeOffset(offset))

        offset += math.ceil(type_.size_in_bytes / 32) * 32
