from collections import defaultdict
from typing import Generic, TypeVar

from vyper import ast as vy_ast
from vyper.evm.opcodes import version_check
from vyper.exceptions import CompilerPanic, StorageLayoutException
from vyper.semantics.analysis.base import VarOffset
from vyper.semantics.data_locations import DataLocation
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
    if storage_layout_overrides is not None:
        # extract code layout with no overrides
        code_offsets = _allocate_layout_r(vyper_module, immutables_only=True)["code_layout"]
        storage_slots = set_storage_slots_with_overrides(vyper_module, storage_layout_overrides)
        return {"storage_layout": storage_slots, "code_layout": code_offsets}

    ret = _allocate_layout_r(vyper_module)
    assert isinstance(ret, defaultdict)
    return dict(ret)  # convert back to dict


_T = TypeVar("_T")
_K = TypeVar("_K")


class InsertableOnceDict(Generic[_T, _K], dict[_T, _K]):
    def __setitem__(self, k, v):
        if k in self:
            raise ValueError(f"{k} is already in dict!")
        super().__setitem__(k, v)


# some name that the user cannot assign to a variable
GLOBAL_NONREENTRANT_KEY = "$.nonreentrant_key"


class SimpleAllocator:
    def __init__(self, max_slot: int = 2**256, starting_slot: int = 0):
        # Allocate storage slots from 0
        # note storage is word-addressable, not byte-addressable
        self._starting_slot = starting_slot
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

    def allocate_global_nonreentrancy_slot(self):
        slot = self.allocate_slot(1, GLOBAL_NONREENTRANT_KEY)
        assert slot == self._starting_slot
        return slot


class Allocators:
    storage_allocator: SimpleAllocator
    transient_storage_allocator: SimpleAllocator
    immutables_allocator: SimpleAllocator

    _global_nonreentrancy_key_slot: int

    def __init__(self):
        self.storage_allocator = SimpleAllocator(max_slot=2**256)
        self.transient_storage_allocator = SimpleAllocator(max_slot=2**256)
        self.immutables_allocator = SimpleAllocator(max_slot=0x6000)

    def get_allocator(self, location: DataLocation):
        if location == DataLocation.STORAGE:
            return self.storage_allocator
        if location == DataLocation.TRANSIENT:
            return self.transient_storage_allocator
        if location == DataLocation.CODE:
            return self.immutables_allocator

        raise CompilerPanic("unreachable")  # pragma: nocover

    def allocate_global_nonreentrancy_slot(self):
        location = get_reentrancy_key_location()

        allocator = self.get_allocator(location)
        slot = allocator.allocate_global_nonreentrancy_slot()
        self._global_nonreentrancy_key_slot = slot

    def get_global_nonreentrant_key_slot(self):
        return self._global_nonreentrancy_key_slot


class OverridingStorageAllocator:
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
    Set storage layout given a layout override file.
    Returns the layout as a dict of variable name -> variable info
    (Doesn't handle modules, or transient storage)
    """
    ret: InsertableOnceDict[str, dict] = InsertableOnceDict()
    reserved_slots = OverridingStorageAllocator()

    # Search through function definitions to find non-reentrant functions
    for node in vyper_module.get_children(vy_ast.FunctionDef):
        type_ = node._metadata["func_type"]

        # Ignore functions without non-reentrant
        if not type_.nonreentrant:
            continue

        variable_name = GLOBAL_NONREENTRANT_KEY

        # re-entrant key was already identified
        if variable_name in ret:
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


def _get_allocatable(vyper_module: vy_ast.Module) -> list[vy_ast.VyperNode]:
    allocable = (vy_ast.InitializesDecl, vy_ast.VariableDecl)
    return [node for node in vyper_module.body if isinstance(node, allocable)]


def get_reentrancy_key_location() -> DataLocation:
    if version_check(begin="cancun"):
        return DataLocation.TRANSIENT
    return DataLocation.STORAGE


_LAYOUT_KEYS = {
    DataLocation.CODE: "code_layout",
    DataLocation.TRANSIENT: "transient_storage_layout",
    DataLocation.STORAGE: "storage_layout",
}


def _allocate_nonreentrant_keys(vyper_module, allocators):
    SLOT = allocators.get_global_nonreentrant_key_slot()

    for node in vyper_module.get_children(vy_ast.FunctionDef):
        type_ = node._metadata["func_type"]
        if not type_.nonreentrant:
            continue

        # a nonreentrant key can appear many times in a module but it
        # only takes one slot. after the first time we see it, do not
        # increment the storage slot.
        type_.set_reentrancy_key_position(VarOffset(SLOT))


def _allocate_layout_r(
    vyper_module: vy_ast.Module, allocators: Allocators = None, immutables_only=False
) -> StorageLayout:
    """
    Parse module-level Vyper AST to calculate the layout of storage variables.
    Returns the layout as a dict of variable name -> variable info
    """
    global_ = False
    if allocators is None:
        global_ = True
        allocators = Allocators()
        # always allocate nonreentrancy slot, so that adding or removing
        # reentrancy protection from a contract does not change its layout
        allocators.allocate_global_nonreentrancy_slot()

    ret: defaultdict[str, InsertableOnceDict[str, dict]] = defaultdict(InsertableOnceDict)

    # tag functions with the global nonreentrant key
    if not immutables_only:
        _allocate_nonreentrant_keys(vyper_module, allocators)

        layout_key = _LAYOUT_KEYS[get_reentrancy_key_location()]
        # TODO this could have better typing but leave it untyped until
        # we nail down the format better
        if global_ and GLOBAL_NONREENTRANT_KEY not in ret[layout_key]:
            slot = allocators.get_global_nonreentrant_key_slot()
            ret[layout_key][GLOBAL_NONREENTRANT_KEY] = {"type": "nonreentrant lock", "slot": slot}

    for node in _get_allocatable(vyper_module):
        if isinstance(node, vy_ast.InitializesDecl):
            module_info = node._metadata["initializes_info"].module_info
            module_layout = _allocate_layout_r(module_info.module_node, allocators)
            module_alias = module_info.alias
            for layout_key in module_layout.keys():
                assert layout_key in _LAYOUT_KEYS.values()
                ret[layout_key][module_alias] = module_layout[layout_key]
            continue

        assert isinstance(node, vy_ast.VariableDecl)
        # skip non-storage variables
        varinfo = node.target._metadata["varinfo"]
        if not varinfo.is_module_variable():
            continue
        location = varinfo.location

        if immutables_only and location != DataLocation.CODE:
            continue

        allocator = allocators.get_allocator(location)
        size = varinfo.get_size()

        # CMC 2021-07-23 note that HashMaps get assigned a slot here
        # using the same allocator (even though there is not really
        # any risk of physical overlap)
        offset = allocator.allocate_slot(size, node.target.id, node)

        varinfo.set_position(VarOffset(offset))

        layout_key = _LAYOUT_KEYS[location]
        type_ = varinfo.typ
        # this could have better typing but leave it untyped until
        # we understand the use case better
        if location == DataLocation.CODE:
            item = {"type": str(type_), "length": size, "offset": offset}
        elif location in (DataLocation.STORAGE, DataLocation.TRANSIENT):
            item = {"type": str(type_), "slot": offset}
        else:  # pragma: nocover
            raise CompilerPanic("unreachable")
        ret[layout_key][node.target.id] = item

    return ret
