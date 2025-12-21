from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from vyper.evm.opcodes import version_check
from vyper.semantics.types import VyperType
from vyper.semantics.types.function import ContractFunctionT
from vyper.semantics.types.module import ModuleT
from vyper.venom.basicblock import IRLabel, IRLiteral, IROperand, IRVariable
from vyper.venom.builder import VenomBuilder


class Constancy(Enum):
    Mutable = 0
    Constant = 1


@dataclass
class VenomVariable:
    """Tracks a variable during Venom codegen."""

    name: str
    typ: VyperType
    ptr: IRVariable  # pointer to memory location
    mutable: bool = True
    is_internal: bool = False
    scopes: set = field(default_factory=set)


@dataclass
class VenomCodegenContext:
    """Tracks state during direct Venom codegen."""

    module_ctx: ModuleT
    builder: VenomBuilder

    # Variable tracking (name -> VenomVariable)
    variables: dict[str, VenomVariable] = field(default_factory=dict)

    # Alloca ID counter (for abstract memory allocation)
    _alloca_id: int = 0

    # Scope tracking
    _scopes: set[int] = field(default_factory=set)
    _scope_id: int = 0

    # Internal variable counter
    _internal_var_id: int = 0

    # Function context
    func_t: Optional[ContractFunctionT] = None
    constancy: Constancy = Constancy.Mutable
    is_ctor_context: bool = False

    # Loop targets (for break/continue)
    break_target: Optional[IRLabel] = None
    continue_target: Optional[IRLabel] = None

    # Return handling
    return_label: Optional[IRLabel] = None
    return_buffer: Optional[IRVariable] = None

    # Loop variable tracking (prevents assignment to loop variables)
    forvars: dict[str, bool] = field(default_factory=dict)

    def new_alloca_id(self) -> int:
        """Generate unique alloca ID."""
        self._alloca_id += 1
        return self._alloca_id

    def new_variable(
        self,
        name: str,
        typ: VyperType,
        mutable: bool = True,
    ) -> IRVariable:
        """Allocate abstract memory for a variable, return pointer."""
        size = typ.memory_bytes_required
        alloca_id = self.new_alloca_id()

        # Use builder to emit alloca instruction
        ptr = self.builder.alloca(size, alloca_id)

        var = VenomVariable(
            name=name,
            typ=typ,
            ptr=ptr,
            mutable=mutable,
            scopes=self._scopes.copy(),
        )
        self.variables[name] = var
        return ptr

    def new_internal_variable(self, typ: VyperType) -> IRVariable:
        """Allocate memory for compiler-internal variable."""
        self._internal_var_id += 1
        name = f"#internal{self._internal_var_id}"

        size = typ.memory_bytes_required
        alloca_id = self.new_alloca_id()
        ptr = self.builder.alloca(size, alloca_id)

        var = VenomVariable(
            name=name,
            typ=typ,
            ptr=ptr,
            mutable=True,
            is_internal=True,
            scopes=self._scopes.copy(),
        )
        self.variables[name] = var
        return ptr

    def lookup(self, name: str) -> VenomVariable:
        """Get variable by name."""
        return self.variables[name]

    def lookup_ptr(self, name: str) -> IRVariable:
        """Get variable's memory pointer."""
        return self.variables[name].ptr

    def is_constant(self) -> bool:
        """Check if in constant (view) context."""
        return self.constancy is Constancy.Constant

    # Context managers for scoped variable management
    @contextmanager
    def block_scope(self):
        """Scope for block-level variables."""
        scope_id = self._scope_id
        self._scope_id += 1
        self._scopes.add(scope_id)

        try:
            yield
        finally:
            # Remove variables scoped to this block
            to_remove = [
                name
                for name, var in self.variables.items()
                if scope_id in var.scopes
            ]
            for name in to_remove:
                del self.variables[name]
            self._scopes.remove(scope_id)

    @contextmanager
    def loop_scope(self, break_bb: IRLabel, continue_bb: IRLabel):
        """Scope for loop with break/continue targets."""
        old_break, old_continue = self.break_target, self.continue_target
        self.break_target, self.continue_target = break_bb, continue_bb

        try:
            with self.block_scope():
                yield
        finally:
            self.break_target, self.continue_target = old_break, old_continue

    def child_for_function(
        self,
        func_t: ContractFunctionT,
        builder: VenomBuilder,
        is_ctor: bool = False,
    ) -> "VenomCodegenContext":
        """Create child context for compiling a function."""
        return VenomCodegenContext(
            module_ctx=self.module_ctx,
            builder=builder,
            func_t=func_t,
            constancy=Constancy.Constant if func_t.is_view else Constancy.Mutable,
            is_ctor_context=is_ctor or self.is_ctor_context,
        )

    # === Memory Operations ===

    def load_memory(self, ptr: IROperand, typ: VyperType) -> IROperand:
        """Load value from memory pointer.

        For primitive types (<=32 bytes), returns the loaded value.
        For complex types (>32 bytes), returns the pointer itself
        since caller will work with the pointer.
        """
        if typ.memory_bytes_required <= 32:
            return self.builder.mload(ptr)
        else:
            # Complex types: return pointer (caller handles copy if needed)
            return ptr

    def store_memory(
        self, val: IROperand, ptr: IROperand, typ: VyperType
    ) -> None:
        """Store value to memory pointer.

        For primitive types (<=32 bytes), stores the value directly.
        For complex types (>32 bytes), val is a source pointer and
        we copy from val to ptr.
        """
        if typ.memory_bytes_required <= 32:
            self.builder.mstore(val, ptr)
        else:
            # Complex type: val is a pointer, copy memory
            self.copy_memory(ptr, val, typ.memory_bytes_required)

    def copy_memory(self, dst: IROperand, src: IROperand, size: int) -> None:
        """Copy memory region from src to dst.

        Uses mcopy for Cancun+, otherwise word-by-word copy.
        """
        if size == 0:
            return

        # For Cancun+, use mcopy
        if version_check(begin="cancun"):
            self.builder.mcopy(IRLiteral(size), src, dst)
            return

        # Pre-Cancun: word-by-word copy
        for offset in range(0, size, 32):
            if isinstance(src, IRLiteral):
                src_ptr = IRLiteral(src.value + offset)
            else:
                src_ptr = self.builder.add(src, IRLiteral(offset))

            if isinstance(dst, IRLiteral):
                dst_ptr = IRLiteral(dst.value + offset)
            else:
                dst_ptr = self.builder.add(dst, IRLiteral(offset))

            val = self.builder.mload(src_ptr)
            self.builder.mstore(val, dst_ptr)

    def load_calldata(self, offset: IROperand, typ: VyperType) -> IROperand:
        """Load from calldata.

        For primitive types (<=32 bytes), returns calldataload value.
        For complex types (>32 bytes), copies calldata to memory
        and returns the memory pointer.
        """
        if typ.memory_bytes_required <= 32:
            return self.builder.calldataload(offset)
        else:
            # Allocate buffer and copy calldata to it
            size = typ.memory_bytes_required
            buf = self.new_internal_variable(typ)
            self.builder.calldatacopy(IRLiteral(size), offset, buf)
            return buf

    def allocate_buffer(self, size: int, name: str = "buf") -> IRVariable:
        """Allocate a temporary memory buffer of given size.

        Useful for ABI encoding/decoding buffers and other
        temporary scratch space.
        """
        from vyper.semantics.types.shortcuts import BYTES32_T

        # Create a dummy type for allocation purposes
        # We just need the size - type doesn't matter for buffers
        alloca_id = self.new_alloca_id()
        return self.builder.alloca(size, alloca_id)

    # === Storage Operations ===

    # Storage is word-addressed (word_scale=1): slot N is at slot N, not byte N*32.
    # This differs from memory which is byte-addressed (word_scale=32).

    DYNAMIC_ARRAY_OVERHEAD = 1  # Length word takes 1 slot (not 32 bytes)

    def load_storage(self, slot: IROperand, typ: VyperType) -> IROperand:
        """Load value from storage slot.

        For primitive types (single word), returns sload result.
        For multi-word types, allocates memory buffer and copies.
        """
        if typ.storage_size_in_words == 1:
            return self.builder.sload(slot)
        else:
            # Multi-word: allocate memory and copy from storage
            buf = self.new_internal_variable(typ)
            self._load_storage_to_memory(slot, buf, typ.storage_size_in_words)
            return buf

    def store_storage(
        self, val: IROperand, slot: IROperand, typ: VyperType
    ) -> None:
        """Store value to storage slot.

        For primitive types, direct sstore.
        For multi-word types, val is memory ptr, copy to storage.
        """
        if typ.storage_size_in_words == 1:
            self.builder.sstore(val, slot)
        else:
            # Multi-word: val is memory pointer, copy to storage
            self._store_memory_to_storage(val, slot, typ.storage_size_in_words)

    def _load_storage_to_memory(
        self, slot: IROperand, buf: IROperand, word_count: int
    ) -> None:
        """Load multi-word storage value to memory buffer.

        Storage is word-addressed, memory is byte-addressed.
        """
        for i in range(word_count):
            # Storage: slot + i (word-addressed)
            if i == 0:
                current_slot = slot
            elif isinstance(slot, IRLiteral):
                current_slot = IRLiteral(slot.value + i)
            else:
                current_slot = self.builder.add(slot, IRLiteral(i))

            val = self.builder.sload(current_slot)

            # Memory: buf + i*32 (byte-addressed)
            if i == 0:
                mem_offset = buf
            elif isinstance(buf, IRLiteral):
                mem_offset = IRLiteral(buf.value + i * 32)
            else:
                mem_offset = self.builder.add(buf, IRLiteral(i * 32))

            self.builder.mstore(val, mem_offset)

    def _store_memory_to_storage(
        self, buf: IROperand, slot: IROperand, word_count: int
    ) -> None:
        """Store memory buffer to multi-word storage.

        Memory is byte-addressed, storage is word-addressed.
        """
        for i in range(word_count):
            # Memory: buf + i*32 (byte-addressed)
            if i == 0:
                mem_offset = buf
            elif isinstance(buf, IRLiteral):
                mem_offset = IRLiteral(buf.value + i * 32)
            else:
                mem_offset = self.builder.add(buf, IRLiteral(i * 32))

            val = self.builder.mload(mem_offset)

            # Storage: slot + i (word-addressed)
            if i == 0:
                current_slot = slot
            elif isinstance(slot, IRLiteral):
                current_slot = IRLiteral(slot.value + i)
            else:
                current_slot = self.builder.add(slot, IRLiteral(i))

            self.builder.sstore(val, current_slot)

    # === Transient Storage (EIP-1153, Cancun+) ===

    def load_transient(self, slot: IROperand, typ: VyperType) -> IROperand:
        """Load from transient storage (Cancun+).

        For primitive types (single word), returns tload result.
        For multi-word types, allocates memory buffer and copies.
        """
        if typ.storage_size_in_words == 1:
            return self.builder.tload(slot)
        else:
            # Multi-word: allocate memory and copy from transient storage
            buf = self.new_internal_variable(typ)
            self._load_transient_to_memory(slot, buf, typ.storage_size_in_words)
            return buf

    def store_transient(
        self, val: IROperand, slot: IROperand, typ: VyperType
    ) -> None:
        """Store to transient storage (Cancun+).

        For primitive types, direct tstore.
        For multi-word types, val is memory ptr, copy to transient storage.
        """
        if typ.storage_size_in_words == 1:
            self.builder.tstore(val, slot)
        else:
            # Multi-word: val is memory pointer, copy to transient storage
            self._store_memory_to_transient(val, slot, typ.storage_size_in_words)

    def _load_transient_to_memory(
        self, slot: IROperand, buf: IROperand, word_count: int
    ) -> None:
        """Load multi-word transient storage value to memory buffer."""
        for i in range(word_count):
            # Transient storage: slot + i (word-addressed)
            if i == 0:
                current_slot = slot
            elif isinstance(slot, IRLiteral):
                current_slot = IRLiteral(slot.value + i)
            else:
                current_slot = self.builder.add(slot, IRLiteral(i))

            val = self.builder.tload(current_slot)

            # Memory: buf + i*32 (byte-addressed)
            if i == 0:
                mem_offset = buf
            elif isinstance(buf, IRLiteral):
                mem_offset = IRLiteral(buf.value + i * 32)
            else:
                mem_offset = self.builder.add(buf, IRLiteral(i * 32))

            self.builder.mstore(val, mem_offset)

    def _store_memory_to_transient(
        self, buf: IROperand, slot: IROperand, word_count: int
    ) -> None:
        """Store memory buffer to multi-word transient storage."""
        for i in range(word_count):
            # Memory: buf + i*32 (byte-addressed)
            if i == 0:
                mem_offset = buf
            elif isinstance(buf, IRLiteral):
                mem_offset = IRLiteral(buf.value + i * 32)
            else:
                mem_offset = self.builder.add(buf, IRLiteral(i * 32))

            val = self.builder.mload(mem_offset)

            # Transient storage: slot + i (word-addressed)
            if i == 0:
                current_slot = slot
            elif isinstance(slot, IRLiteral):
                current_slot = IRLiteral(slot.value + i)
            else:
                current_slot = self.builder.add(slot, IRLiteral(i))

            self.builder.tstore(val, current_slot)

    # === Immutables ===

    # Immutables are stored in bytecode (CODE location), accessed via iload/istore.
    # They are byte-addressed (word_scale=32), like memory.

    def load_immutable(self, offset: IROperand, typ: VyperType) -> IROperand:
        """Load immutable value from deployed bytecode.

        For primitive types (<=32 bytes), returns iload result.
        For multi-word types, allocates memory buffer and copies.
        """
        if typ.memory_bytes_required <= 32:
            return self.builder.iload(offset)
        else:
            # Multi-word immutable: copy to memory buffer
            buf = self.new_internal_variable(typ)
            size = typ.memory_bytes_required
            for i in range(0, size, 32):
                # Immutables are byte-addressed
                if i == 0:
                    imm_offset = offset
                elif isinstance(offset, IRLiteral):
                    imm_offset = IRLiteral(offset.value + i)
                else:
                    imm_offset = self.builder.add(offset, IRLiteral(i))

                val = self.builder.iload(imm_offset)

                # Memory is byte-addressed
                if i == 0:
                    mem_ptr = buf
                elif isinstance(buf, IRLiteral):
                    mem_ptr = IRLiteral(buf.value + i)
                else:
                    mem_ptr = self.builder.add(buf, IRLiteral(i))

                self.builder.mstore(val, mem_ptr)

            return buf

    def store_immutable(
        self, val: IROperand, offset: IROperand, typ: VyperType
    ) -> None:
        """Store immutable value (during constructor only).

        For primitive types (<=32 bytes), direct istore.
        For multi-word types, val is memory ptr, copy to immutables.
        """
        if typ.memory_bytes_required <= 32:
            self.builder.istore(val, offset)
        else:
            # Multi-word: val is memory pointer, copy to immutables
            size = typ.memory_bytes_required
            for i in range(0, size, 32):
                # Memory is byte-addressed
                if i == 0:
                    mem_ptr = val
                elif isinstance(val, IRLiteral):
                    mem_ptr = IRLiteral(val.value + i)
                else:
                    mem_ptr = self.builder.add(val, IRLiteral(i))

                word = self.builder.mload(mem_ptr)

                # Immutables are byte-addressed
                if i == 0:
                    imm_offset = offset
                elif isinstance(offset, IRLiteral):
                    imm_offset = IRLiteral(offset.value + i)
                else:
                    imm_offset = self.builder.add(offset, IRLiteral(i))

                self.builder.istore(word, imm_offset)

    # === Dynamic Array in Storage ===

    def get_storage_dyn_array_length(self, slot: IROperand) -> IRVariable:
        """Get length of dynamic array in storage.

        Length is stored at the base slot.
        """
        return self.builder.sload(slot)

    def set_storage_dyn_array_length(
        self, slot: IROperand, length: IROperand
    ) -> None:
        """Set length of dynamic array in storage.

        Length is stored at the base slot.
        """
        self.builder.sstore(length, slot)
