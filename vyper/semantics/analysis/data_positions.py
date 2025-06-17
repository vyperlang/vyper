import json
from collections import defaultdict
from typing import Generic, Optional, TypeVar

from vyper import ast as vy_ast
from vyper.evm.opcodes import version_check
from vyper.exceptions import CompilerPanic, StorageLayoutException
from vyper.semantics.analysis.base import VarOffset
from vyper.semantics.data_locations import DataLocation
from vyper.typing import StorageLayout


def set_data_positions(
    vyper_module: vy_ast.Module, storage_layout_overrides: StorageLayout = None
) -> None:
    """
    Parse the annotated Vyper AST, determine data positions for all variables,
    and annotate the AST nodes with the position data.

    Arguments
    ---------
    vyper_module : vy_ast.Module
        Top-level Vyper AST node that has already been annotated with type data.
    """
    if storage_layout_overrides is not None:
        # allocate code layout with no overrides
        _allocate_layout_r(vyper_module, no_storage=True)
        _allocate_with_overrides(vyper_module, storage_layout_overrides)

        # sanity check that generated layout file is the same as the input.
        roundtrip = generate_layout_export(vyper_module).get(_LAYOUT_KEYS[DataLocation.STORAGE], {})
        if roundtrip != storage_layout_overrides:
            msg = "Computed storage layout does not match override file!\n"
            msg += f"expected: {json.dumps(storage_layout_overrides)}\n\n"
            msg += f"got:\n{json.dumps(roundtrip)}"
            raise CompilerPanic(msg)
    else:
        _allocate_layout_r(vyper_module)


_T = TypeVar("_T")
_K = TypeVar("_K")


class InsertableOnceDict(Generic[_T, _K], dict[_T, _K]):
    def __setitem__(self, k, v):
        if k in self:
            raise ValueError(f"{k} is already in dict!")
        super().__setitem__(k, v)


# some name that the user cannot assign to a variable
GLOBAL_NONREENTRANT_KEY = "$.nonreentrant_key"
NONREENTRANT_KEY_SIZE = 1


class SimpleAllocator:
    def __init__(self, max_slot: int = 2**256, starting_slot: int = 0):
        # Allocate storage slots from 0
        # note storage is word-addressable, not byte-addressable
        self._starting_slot = starting_slot
        self._slot = starting_slot
        self._max_slot = max_slot

    def allocate_slot(self, n, node=None):
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
        slot = self.allocate_slot(NONREENTRANT_KEY_SIZE)
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


def _fetch_path(path: list[str], layout: StorageLayout, node: vy_ast.VyperNode):
    tmp = layout
    qualified_path = ".".join(path)

    for segment in path:
        if segment not in tmp:
            raise StorageLayoutException(
                f"Could not find storage slot for {qualified_path}. "
                "Have you used the correct storage layout file?",
                node,
            )
        tmp = tmp[segment]

    try:
        ret = tmp["slot"]
    except KeyError as e:
        raise StorageLayoutException(f"no storage slot for {qualified_path}", node) from e

    return ret


def _allocate_with_overrides(vyper_module: vy_ast.Module, layout: StorageLayout):
    """
    Set storage layout given a layout override file.
    """
    allocator = OverridingStorageAllocator()

    nonreentrant_slot = None
    if GLOBAL_NONREENTRANT_KEY in layout:
        nonreentrant_slot = layout[GLOBAL_NONREENTRANT_KEY]["slot"]

    _allocate_with_overrides_r(vyper_module, layout, allocator, nonreentrant_slot, [])


def _get_func_defs(vyper_module: vy_ast.Module):
    funcdefs = vyper_module.get_children(vy_ast.FunctionDef)
    for vardecl in vyper_module.get_children(vy_ast.VariableDecl):
        if not vardecl.is_public:
            # no getter
            continue
        funcdefs.append(vardecl._expanded_getter)

    return funcdefs


def _allocate_with_overrides_r(
    vyper_module: vy_ast.Module,
    layout: StorageLayout,
    allocator: OverridingStorageAllocator,
    global_nonreentrant_slot: Optional[int],
    path: list[str],
):
    # Search through function definitions to find non-reentrant functions
    funcdefs = _get_func_defs(vyper_module)

    for node in funcdefs:
        fn_t = node._metadata["func_type"]

        # Ignore functions without non-reentrant
        if not fn_t.nonreentrant:
            continue

        # if reentrancy keys get allocated in transient storage, we don't
        # override them
        if get_reentrancy_key_location() == DataLocation.TRANSIENT:
            continue

        # Expect to find this variable within the storage layout override
        if global_nonreentrant_slot is None:
            raise StorageLayoutException(
                f"Could not find storage slot for {GLOBAL_NONREENTRANT_KEY}. "
                "Have you used the correct storage layout file?",
                node,
            )

        # prevent other storage variables from using the same slot
        if allocator.occupied_slots.get(global_nonreentrant_slot) != GLOBAL_NONREENTRANT_KEY:
            allocator.reserve_slot_range(
                global_nonreentrant_slot, NONREENTRANT_KEY_SIZE, GLOBAL_NONREENTRANT_KEY
            )

        fn_t.set_reentrancy_key_position(VarOffset(global_nonreentrant_slot))

    for node in _get_allocatable(vyper_module):
        if isinstance(node, vy_ast.InitializesDecl):
            module_info = node._metadata["initializes_info"].module_info

            sub_path = [*path, module_info.alias]
            _allocate_with_overrides_r(
                module_info.module_node, layout, allocator, global_nonreentrant_slot, sub_path
            )
            continue

        # Iterate through variables
        # Ignore immutables and transient variables
        varinfo = node.target._metadata["varinfo"]

        if not varinfo.is_storage:
            continue

        # Expect to find this variable within the storage layout overrides
        varname = node.target.id
        varpath = [*path, varname]
        qualified_varname = ".".join(varpath)

        var_slot = _fetch_path(varpath, layout, node)

        storage_length = varinfo.typ.storage_size_in_words
        # Ensure that all required storage slots are reserved, and
        # prevent other variables from using these slots
        allocator.reserve_slot_range(var_slot, storage_length, qualified_varname)
        varinfo.set_position(VarOffset(var_slot))


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


def _set_nonreentrant_keys(vyper_module, allocators):
    SLOT = allocators.get_global_nonreentrant_key_slot()

    var_decls = vyper_module.get_children(vy_ast.VariableDecl)
    funcdefs = vyper_module.get_children(vy_ast.FunctionDef)

    for var in var_decls:
        if not var.is_public:
            # no getter
            continue
        funcdefs.append(var._expanded_getter)

    for node in funcdefs:
        type_ = node._metadata["func_type"]
        if not type_.nonreentrant:
            continue

        # a nonreentrant key can appear many times in a module but it
        # only takes one slot. after the first time we see it, do not
        # increment the storage slot.
        type_.set_reentrancy_key_position(VarOffset(SLOT))


def _allocate_layout_r(
    vyper_module: vy_ast.Module, allocators: Allocators = None, no_storage=False
):
    """
    Parse module-level Vyper AST to calculate the layout of storage variables.
    Returns the layout as a dict of variable name -> variable info
    """
    if allocators is None:
        allocators = Allocators()
        # always allocate nonreentrancy slot, so that adding or removing
        # reentrancy protection from a contract does not change its layout
        allocators.allocate_global_nonreentrancy_slot()

    # tag functions with the global nonreentrant key
    if not no_storage or get_reentrancy_key_location() == DataLocation.TRANSIENT:
        _set_nonreentrant_keys(vyper_module, allocators)

    for node in _get_allocatable(vyper_module):
        if isinstance(node, vy_ast.InitializesDecl):
            module_info = node._metadata["initializes_info"].module_info
            _allocate_layout_r(module_info.module_node, allocators, no_storage)
            continue

        assert isinstance(node, vy_ast.VariableDecl)
        varinfo = node.target._metadata["varinfo"]

        # skip things we don't need to allocate, like constants
        if not varinfo.is_state_variable():
            continue

        if no_storage and varinfo.is_storage:
            continue

        allocator = allocators.get_allocator(varinfo.location)
        size = varinfo.get_size()

        # CMC 2021-07-23 note that HashMaps get assigned a slot here
        # using the same allocator (even though there is not really
        # any risk of physical overlap)
        offset = allocator.allocate_slot(size, node)
        varinfo.set_position(VarOffset(offset))


# get the layout for export
def generate_layout_export(vyper_module: vy_ast.Module):
    return _generate_layout_export_r(vyper_module)


def _generate_layout_export_r(vyper_module):
    ret: defaultdict[str, InsertableOnceDict[str, dict]] = defaultdict(InsertableOnceDict)

    for node in _get_allocatable(vyper_module):
        if isinstance(node, vy_ast.InitializesDecl):
            module_info = node._metadata["initializes_info"].module_info
            module_layout = _generate_layout_export_r(module_info.module_node)
            module_alias = module_info.alias
            for layout_key in module_layout.keys():
                assert layout_key in _LAYOUT_KEYS.values()

                # lift the nonreentrancy key (if any) into the outer dict
                # note that lifting can leave the inner dict empty, which
                # should be filtered (below) for cleanliness
                nonreentrant = module_layout[layout_key].pop(GLOBAL_NONREENTRANT_KEY, None)
                if nonreentrant is not None and GLOBAL_NONREENTRANT_KEY not in ret[layout_key]:
                    ret[layout_key][GLOBAL_NONREENTRANT_KEY] = nonreentrant

                # add the module as a nested dict, but only if it is non-empty
                if len(module_layout[layout_key]) != 0:
                    ret[layout_key][module_alias] = module_layout[layout_key]

            continue

        assert isinstance(node, vy_ast.VariableDecl)
        varinfo = node.target._metadata["varinfo"]
        # skip non-state variables
        if not varinfo.is_state_variable():
            continue

        location = varinfo.location
        layout_key = _LAYOUT_KEYS[location]
        type_ = varinfo.typ
        size = varinfo.get_size()
        offset = varinfo.position.position

        # this could have better typing but leave it untyped until
        # we understand the use case better
        if location == DataLocation.CODE:
            item = {"type": str(type_), "length": size, "offset": offset}
        elif location in (DataLocation.STORAGE, DataLocation.TRANSIENT):
            item = {"type": str(type_), "n_slots": size, "slot": offset}
        else:  # pragma: nocover
            raise CompilerPanic("unreachable")
        ret[layout_key][node.target.id] = item

    funcdefs = _get_func_defs(vyper_module)
    for fn in funcdefs:
        fn_t = fn._metadata["func_type"]
        if not fn_t.nonreentrant:
            continue

        location = get_reentrancy_key_location()
        layout_key = _LAYOUT_KEYS[location]

        if GLOBAL_NONREENTRANT_KEY in ret[layout_key]:
            break

        slot = fn_t.reentrancy_key_position.position
        ret[layout_key][GLOBAL_NONREENTRANT_KEY] = {
            "type": "nonreentrant lock",
            "slot": slot,
            "n_slots": NONREENTRANT_KEY_SIZE,
        }
        break

    return ret
