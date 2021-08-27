# TODO this doesn't really belong in "validation"
import math

from vyper import ast as vy_ast
from vyper.semantics.types.bases import StorageSlot
from vyper.typing import StorageLayout


def set_data_positions(vyper_module: vy_ast.Module) -> StorageLayout:
    """
    Parse the annotated Vyper AST, determine data positions for all variables,
    and annotate the AST nodes with the position data.

    Arguments
    ---------
    vyper_module : vy_ast.Module
        Top-level Vyper AST node that has already been annotated with type data.
    """
    return set_storage_slots(vyper_module)


def set_storage_slots(vyper_module: vy_ast.Module) -> StorageLayout:
    """
    Parse module-level Vyper AST to calculate the layout of storage variables.
    Returns the layout as a dict of variable name -> variable info
    """
    # Allocate storage slots from 0
    # note storage is word-addressable, not byte-addressable
    storage_slot = 0

    ret = {}

    for node in vyper_module.get_children(vy_ast.FunctionDef):
        type_ = node._metadata["type"]
        if type_.nonreentrant is not None:
            type_.set_reentrancy_key_position(StorageSlot(storage_slot))

            # TODO this could have better typing but leave it untyped until
            # we nail down the format better
            variable_name = f"nonreentrant.{type_.nonreentrant}"
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
