import math

from vyper import ast as vy_ast
from vyper.context.types.bases import StorageSlot


def set_data_positions(vyper_module: vy_ast.Module) -> None:
    """
    Parse the annotated Vyper AST, determine data positions for all variables,
    and annotate the AST nodes with the position data.

    Arguments
    ---------
    vyper_module : vy_ast.Module
        Top-level Vyper AST node that has already been annotated with type data.
    """
    set_storage_slots(vyper_module)


def set_storage_slots(vyper_module: vy_ast.Module) -> None:
    """
    Parse module-level Vyper AST to calculate the layout of storage variables.
    """
    available_slot = 0
    for node in vyper_module.get_children(vy_ast.AnnAssign):
        type_ = node.target._metadata["type"]
        type_.set_position(StorageSlot(available_slot))
        available_slot += math.ceil(type_.size_in_bytes / 32)


def set_calldata_offsets(fn_node: vy_ast.FunctionDef) -> None:
    pass


def set_memory_offsets(fn_node: vy_ast.FunctionDef) -> None:
    pass
