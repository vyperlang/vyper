from vyper import ast as vy_ast
from vyper.exceptions import CompilerPanic, StorageLayoutException
from vyper.semantics.analysis.base import CodeOffset, ModuleVarInfo, StorageSlot
from vyper.typing import StorageLayout


def allocate_variables(vyper_module: vy_ast.Module) -> StorageLayout:
    """
    Parse the annotated Vyper AST, determine data positions for all variables,
    and annotate the AST nodes with the position data.

    Arguments
    ---------
    vyper_module : vy_ast.Module
        Top-level Vyper AST node that has already been annotated with type data.
    """
    code_offsets = _set_code_offsets(vyper_module)
    storage_slots = _set_storage_slots(vyper_module)

    return {"storage_layout": storage_slots, "code_layout": code_offsets}


class SimpleAllocator:
    _max_slots = None

    def __init__(self, starting_slot: int = 0):
        self._slot = starting_slot

    def allocate(self, n, var_name="<unknown>"):
        ret = self._slot
        if self._slot + n >= self._max_slots:
            raise StorageLayoutException(
                f"Invalid storage slot for var {var_name}, tried to allocate"
                f" slots {self._slot} through {self._slot + n}"
            )
        self._slot += n
        return ret


class SimpleStorageAllocator(SimpleAllocator):
    _max_slots = 2**256


class SimpleImmutablesAllocator(SimpleAllocator):
    _max_slots = 0x6000  # eip-170


def _set_storage_slots(vyper_module: vy_ast.Module) -> StorageLayout:
    """
    Parse module-level Vyper AST to calculate the layout of storage variables.
    Returns the layout as a dict of variable name -> variable info
    """
    # Allocate storage slots from 0
    # note storage is word-addressable, not byte-addressable
    allocator = SimpleStorageAllocator()

    ret: dict[str, dict] = {}

    for funcdef in vyper_module.get_children(vy_ast.FunctionDef):
        type_ = funcdef._metadata["func_type"]
        if type_.nonreentrant is None:
            continue

        keyname = f"nonreentrant.{type_.nonreentrant}"

        # a nonreentrant key can appear many times in a module but it
        # only takes one slot. after the first time we see it, do not
        # increment the storage slot.
        if keyname in ret:
            _slot = ret[keyname]["slot"]
            type_.set_reentrancy_key_position(StorageSlot(_slot))
            continue

        # TODO use one byte - or bit - per reentrancy key
        # requires either an extra SLOAD or caching the value of the
        # location in memory at entrance
        slot = allocator.allocate(1, keyname)

        type_.set_reentrancy_key_position(StorageSlot(slot))

        # TODO this could have better typing but leave it untyped until
        # we nail down the format better
        ret[keyname] = {"type": "nonreentrant lock", "slot": slot}

    for varinfo in vyper_module._metadata["type"].variables.values():
        # skip non-storage variables
        if varinfo.is_constant or varinfo.is_immutable:
            continue

        type_ = varinfo.typ

        vardecl = varinfo.decl_node
        assert isinstance(vardecl, vy_ast.VariableDecl)

        varname = vardecl.target.id

        # CMC 2021-07-23 note that HashMaps get assigned a slot here.
        # I'm not sure if it's safe to avoid allocating that slot
        # for HashMaps because downstream code might use the slot
        # ID as a salt.
        n_slots = type_.storage_slots_required
        slot = allocator.allocate(n_slots, varname)

        varinfo.set_storage_position(StorageSlot(slot))

        assert varname not in ret
        # this could have better typing but leave it untyped until
        # we understand the use case better
        ret[varname] = {"type": str(type_), "slot": slot}

    return ret


def _set_code_offsets(vyper_module: vy_ast.Module) -> dict[str, dict]:
    ret = {}
    allocator = SimpleImmutablesAllocator()

    for varinfo in vyper_module._metadata["type"].variables.values():
        type_ = varinfo.typ

        if not varinfo.is_immutable and not isinstance(varinfo, ModuleVarInfo):
            continue

        len_ = type_.immutable_bytes_required

        # sanity check. there are ways to construct varinfo with no
        # decl_node but they shouldn't make it to here
        vardecl = varinfo.decl_node
        assert isinstance(vardecl, vy_ast.VariableDecl)
        varname = vardecl.target.id

        if len_ % 32 != 0:
            # sanity check length is a multiple of 32, it's an invariant
            # that is used a lot in downstream code.
            raise CompilerPanic("bad invariant")

        offset = allocator.allocate(len_, varname)
        varinfo.set_immutables_position(CodeOffset(offset))

        # this could have better typing but leave it untyped until
        # we understand the use case better
        output_dict = {"type": str(type_), "offset": offset, "length": len_}

        # put it into the storage layout
        assert varname not in ret
        ret[varname] = output_dict

    return ret
