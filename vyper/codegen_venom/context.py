"""
Code generation context and state management.

VenomCodegenContext tracks:
- Current function/module being compiled
- Variable locations (memory offsets, storage slots)
- Memory allocation (free pointer, allocations)
- VenomBuilder instance for IR emission
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Optional

from vyper.codegen.core import is_tuple_like
from vyper.codegen_venom.buffer import Buffer, Ptr
from vyper.codegen_venom.constants import IDENTITY_PRECOMPILE
from vyper.codegen_venom.value import VyperValue
from vyper.evm.opcodes import version_check
from vyper.exceptions import CompilerPanic, MemoryAllocationException, StateAccessViolation
from vyper.semantics.data_locations import DataLocation
from vyper.semantics.types import VyperType
from vyper.semantics.types.bytestrings import _BytestringT
from vyper.semantics.types.function import ContractFunctionT, StateMutability
from vyper.semantics.types.module import ModuleT
from vyper.venom.basicblock import IRLabel, IRLiteral, IROperand, IRVariable
from vyper.venom.builder import VenomBuilder

if TYPE_CHECKING:
    pass


class Constancy(Enum):
    Mutable = 0
    Constant = 1


@dataclass
class LocalVariable:
    """Tracks a variable during Venom codegen."""

    name: str
    value: VyperValue  # must be located in MEMORY
    mutable: bool = True
    scopes: set = field(default_factory=set)

    def __post_init__(self):
        if self.value.is_stack_value:
            raise CompilerPanic("LocalVariable.value must be located")
        if self.value.location != DataLocation.MEMORY:
            raise CompilerPanic("LocalVariable must be in MEMORY")

    @property
    def typ(self) -> VyperType:
        return self.value.typ

    @property
    def buf(self) -> Buffer:
        # Invariant: LocalVariable is always in MEMORY (enforced by __post_init__),
        # and Ptr.buf is always set when location is MEMORY (enforced by Ptr.__post_init__)
        buf = self.value.ptr().buf
        assert buf is not None
        return buf


@dataclass
class VenomCodegenContext:
    """Tracks state during direct Venom codegen."""

    module_ctx: ModuleT
    builder: VenomBuilder

    # Variable tracking (name -> LocalVariable)
    variables: dict[str, LocalVariable] = field(default_factory=dict)

    # Scope tracking
    _scopes: set[int] = field(default_factory=set)
    _scope_id: int = 0

    # Function context
    func_t: Optional[ContractFunctionT] = None
    constancy: Constancy = Constancy.Mutable
    is_ctor_context: bool = False

    # Loop targets (for break/continue)
    break_target: Optional[IRLabel] = None
    continue_target: Optional[IRLabel] = None

    # Return handling
    return_buffer: Optional[IRVariable] = None
    return_pc: Optional[IRVariable] = None  # For internal function returns

    # Loop variable tracking (prevents assignment to loop variables)
    forvars: dict[str, bool] = field(default_factory=dict)

    # Range expression context - set to True when evaluating range/iterator expressions
    in_range_expr: bool = False

    # Immutables region alloca (for constructor context)
    # When set, iload/istore use GEP from this base instead of raw offsets
    immutables_alloca: Optional[IRVariable] = None

    # Constants for internal function calling convention
    MAX_STACK_ARGS: int = 6
    MAX_STACK_RETURNS: int = 2

    def new_alloca_id(self) -> int:
        """Generate unique alloca ID."""
        return self.builder.ctx.get_next_alloca_id()

    def new_variable(self, name: str, typ: VyperType, mutable: bool = True) -> LocalVariable:
        """Allocate memory for a named variable, register it, return the variable."""
        buf = self.allocate_buffer(typ.memory_bytes_required, annotation=name)
        value = VyperValue.from_ptr(buf.base_ptr(), typ)
        var = LocalVariable(name=name, value=value, mutable=mutable, scopes=self._scopes.copy())
        self.variables[name] = var
        return var

    def register_variable(
        self, name: str, typ: VyperType, ptr: IRVariable, mutable: bool = True
    ) -> None:
        """Register a variable with an existing pointer (no allocation).

        Used for internal function parameters where memory is already
        allocated by the caller.
        """
        # Create a dummy buffer for the existing pointer
        buf = Buffer(_ptr=ptr, size=typ.memory_bytes_required, annotation=name)
        value = VyperValue.from_ptr(buf.base_ptr(), typ)
        var = LocalVariable(name=name, value=value, mutable=mutable, scopes=self._scopes.copy())
        self.variables[name] = var

    def new_temporary_value(self, typ: VyperType, annotation: Optional[str] = None) -> VyperValue:
        """
        Allocate typed scratch memory.

        Returns VyperValue pointing to a new buffer. Not registered anywhere -
        caller holds the only reference. Use for temporary/intermediate values
        during code generation.
        """
        buf = self.allocate_buffer(typ.memory_bytes_required, annotation)
        return VyperValue.from_ptr(buf.base_ptr(), typ)

    def lookup(self, name: str) -> LocalVariable:
        """Get variable by name."""
        return self.variables[name]

    def unwrap(self, vv: VyperValue) -> IROperand:
        """Unwrap a VyperValue, loading from location if needed.

        - If already a value (location=None): return operand directly
        - If complex type (>32 bytes): return operand as pointer (or copy for CODE)
        - Otherwise: emit load instruction and return the loaded value
        """
        if vv.location is None:
            return vv.operand

        # Complex types (>32 bytes)
        if vv.typ is not None and not vv.typ._is_prim_word:
            # CODE location requires copy to memory (can't use pointer directly)
            if vv.location == DataLocation.CODE:
                if self.is_ctor_context:
                    return self.load_immutable_ctor(vv.operand, vv.typ)
                return self.load_immutable(vv.operand, vv.typ)
            # STORAGE location requires copy to memory
            if vv.location == DataLocation.STORAGE:
                return self.load_storage(vv.operand, vv.typ)
            # TRANSIENT location requires copy to memory
            if vv.location == DataLocation.TRANSIENT:
                return self.load_transient(vv.operand, vv.typ)
            # MEMORY location: return pointer directly
            return vv.operand

        # Primitive word type: emit load based on location
        if vv.location == DataLocation.CODE:
            # ctor context uses iload; runtime uses dload
            if self.is_ctor_context:
                return self.builder.iload(vv.operand)
            return self.builder.dload(vv.operand)
        return self.builder.load(vv.operand, vv.location)

    def bytes_data_ptr(self, vv: VyperValue) -> IROperand:
        """Get pointer to bytestring data (skipping length word).

        Like legacy bytes_data_ptr: add_ofst(ptr, location.word_scale)
        """
        # None location treated as MEMORY (for in-memory bytestrings without explicit location)
        loc = vv.location
        assert loc is None or loc in (
            DataLocation.MEMORY,
            DataLocation.STORAGE,
            DataLocation.TRANSIENT,
        ), f"bytes_data_ptr expects MEMORY, STORAGE, or TRANSIENT, got {loc}"
        word_scale = 32 if loc is None or loc == DataLocation.MEMORY else 1
        return self.builder.add(vv.operand, IRLiteral(word_scale))

    def bytestring_length(self, vv: VyperValue) -> IROperand:
        """Get length of bytestring from its pointer.

        Like legacy get_bytearray_length: LOAD(ptr)
        None location treated as MEMORY (for in-memory bytestrings without explicit location).
        """
        loc = vv.location
        assert loc is None or loc in (
            DataLocation.MEMORY,
            DataLocation.STORAGE,
            DataLocation.TRANSIENT,
        ), f"bytestring_length expects MEMORY, STORAGE, or TRANSIENT, got {loc}"
        # None location treated as MEMORY
        if loc is None:
            return self.builder.mload(vv.operand)
        return self.builder.load(vv.operand, loc)

    def is_constant(self) -> bool:
        """Check if in constant (view) context or range expression."""
        return self.constancy is Constancy.Constant or self.in_range_expr

    def check_is_not_constant(self, err: str, node) -> None:
        """Raise StateAccessViolation if in constant/view context."""
        if self.is_constant():
            raise StateAccessViolation(f"Cannot {err} from {self.pp_constancy()}", node)

    def pp_constancy(self) -> str:
        """Pretty-print the current constancy context."""
        if self.in_range_expr:
            return "a range expression"
        elif self.constancy == Constancy.Constant:
            return "a constant function"
        raise CompilerPanic(f"bad constancy: {self.constancy}")  # pragma: nocover

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
            to_remove = [name for name, var in self.variables.items() if scope_id in var.scopes]
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

    @contextmanager
    def range_scope(self):
        """Scope for range expression evaluation (treats context as constant)."""
        prev_value = self.in_range_expr
        self.in_range_expr = True
        try:
            yield
        finally:
            self.in_range_expr = prev_value

    def child_for_function(
        self, func_t: ContractFunctionT, builder: VenomBuilder, is_ctor: bool = False
    ) -> "VenomCodegenContext":
        """Create child context for compiling a function."""
        return VenomCodegenContext(
            module_ctx=self.module_ctx,
            builder=builder,
            func_t=func_t,
            constancy=Constancy.Constant
            if func_t.mutability in (StateMutability.VIEW, StateMutability.PURE)
            else Constancy.Mutable,
            is_ctor_context=is_ctor or self.is_ctor_context,
        )

    # === Internal Function Helpers ===

    def is_word_type(self, typ: VyperType) -> bool:
        """Check if type fits in one stack slot (32 bytes)."""
        return typ.memory_bytes_required == 32

    def pass_via_stack(self, func_t: ContractFunctionT) -> dict[str, bool]:
        """Determine which args pass via stack vs memory.

        Returns dict mapping arg name -> True if stack, False if memory.
        Word types pass via stack up to MAX_STACK_ARGS.
        """
        ret = {}
        stack_items = 0

        # Return takes one stack slot if it's a word type
        if func_t.return_type is not None and self.is_word_type(func_t.return_type):
            stack_items += 1

        for arg in func_t.arguments:
            if not self.is_word_type(arg.typ) or stack_items > self.MAX_STACK_ARGS:
                ret[arg.name] = False
            else:
                ret[arg.name] = True
                stack_items += 1

        return ret

    def returns_stack_count(self, func_t: ContractFunctionT) -> int:
        """How many values returned via stack (0, 1, or 2 for tuples)."""
        ret_t = func_t.return_type
        if ret_t is None:
            return 0

        if is_tuple_like(ret_t):
            members = ret_t.tuple_items()  # type: ignore[attr-defined]
            if 1 <= len(members) <= self.MAX_STACK_RETURNS:
                if all(self.is_word_type(t) for (_k, t) in members):
                    return len(members)
            return 0

        return 1 if self.is_word_type(ret_t) else 0

    # === Nonreentrant Lock Support ===

    def emit_nonreentrant_lock(self, func_t: ContractFunctionT) -> None:
        """Emit nonreentrant lock acquire (at function entry)."""
        if not func_t.nonreentrant:
            return

        nkey = func_t.reentrancy_key_position.position

        if version_check(begin="cancun"):
            LOAD = self.builder.tload
            STORE = self.builder.tstore
            temp_value = 1
        else:
            LOAD = self.builder.sload
            STORE = self.builder.sstore
            temp_value = 2

        # Check not already locked
        current = LOAD(IRLiteral(nkey))
        not_locked = self.builder.iszero(self.builder.eq(current, IRLiteral(temp_value)))
        self.builder.assert_(not_locked)

        # Set lock (unless view function)
        if func_t.mutability != StateMutability.VIEW:
            STORE(IRLiteral(nkey), IRLiteral(temp_value))

    def emit_nonreentrant_unlock(self, func_t: ContractFunctionT) -> None:
        """Emit nonreentrant lock release (at function exit)."""
        if not func_t.nonreentrant:
            return

        if func_t.mutability == StateMutability.VIEW:
            return  # View functions don't modify lock

        nkey = func_t.reentrancy_key_position.position

        if version_check(begin="cancun"):
            final_value = 0
            self.builder.tstore(IRLiteral(nkey), IRLiteral(final_value))
        else:
            final_value = 3
            self.builder.sstore(IRLiteral(nkey), IRLiteral(final_value))

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

    def store_memory(self, val: IROperand, ptr: IROperand, typ: VyperType) -> None:
        """Store value to memory pointer.

        For primitive word types, stores the value directly via mstore.
        For complex types (structs, arrays), val is a source pointer and
        we copy from val to ptr.
        For bytestrings, copies actual length from source, not max size.

        Note: Single-word structs are NOT primitive word types - they are
        complex types that happen to fit in one word. The caller passes
        a pointer to struct data, not the struct value itself.
        """
        if typ._is_prim_word:
            self.builder.mstore(ptr, val)
        elif isinstance(typ, _BytestringT):
            # Bytestring: copy length word + ceil32(actual data), not max size
            # Length is at val+0, data starts at val+32
            # Must copy complete 32-byte words to avoid leaving dirty data
            src_len = self.builder.mload(val)
            # ceil32(length) = (length + 31) & ~31
            padded_len = self.builder.and_(
                self.builder.add(src_len, IRLiteral(31)),
                IRLiteral((1 << 256) - 32),  # ~31 in 256-bit
            )
            # Copy 32 (length word) + ceil32(length) bytes
            copy_len = self.builder.add(padded_len, IRLiteral(32))
            self.copy_memory_dynamic(ptr, val, copy_len)
        else:
            # Complex type: val is a pointer, copy memory
            self.copy_memory(ptr, val, typ.memory_bytes_required)

    # Threshold for using identity precompile vs unrolling (pre-Cancun).
    # Identity precompile has ~25 bytes overhead, unrolling is ~15 bytes/word.
    # For 3+ words, identity precompile produces smaller bytecode.
    _IDENTITY_PRECOMPILE_THRESHOLD = 96  # 3 words

    def copy_memory(self, dst: IROperand, src: IROperand, size: int) -> None:
        """Copy memory region from src to dst (static size known at compile time).

        Uses mcopy for Cancun+. Pre-Cancun uses identity precompile for large
        copies (>= 96 bytes) and word-by-word for small copies.
        """
        if size == 0:
            return

        # For Cancun+, use mcopy
        if version_check(begin="cancun"):
            self.builder.mcopy(dst, src, IRLiteral(size))
            return

        # Pre-Cancun: use identity precompile for large copies
        if size >= self._IDENTITY_PRECOMPILE_THRESHOLD:
            b = self.builder
            success = b.staticcall(
                b.gas(), IRLiteral(IDENTITY_PRECOMPILE), src, IRLiteral(size), dst, IRLiteral(size)
            )
            b.assert_(success)
            return

        # Pre-Cancun: word-by-word copy for small copies
        for offset in range(0, size, 32):
            src_ptr: IROperand
            if isinstance(src, IRLiteral):
                src_ptr = IRLiteral(src.value + offset)
            else:
                src_ptr = self.builder.add(src, IRLiteral(offset))

            dst_ptr: IROperand
            if isinstance(dst, IRLiteral):
                dst_ptr = IRLiteral(dst.value + offset)
            else:
                dst_ptr = self.builder.add(dst, IRLiteral(offset))

            val = self.builder.mload(src_ptr)
            self.builder.mstore(dst_ptr, val)

    def copy_memory_dynamic(self, dst: IROperand, src: IROperand, length: IROperand) -> None:
        """Copy memory region with dynamic length (known at runtime).

        Uses mcopy for Cancun+, otherwise identity precompile (address 4).
        """
        b = self.builder

        # For Cancun+, use mcopy
        if version_check(begin="cancun"):
            b.mcopy(dst, src, length)
            return

        # Pre-Cancun: use identity precompile
        # staticcall(gas, IDENTITY_PRECOMPILE, src, length, dst, length)
        success = b.staticcall(b.gas(), IRLiteral(IDENTITY_PRECOMPILE), src, length, dst, length)
        b.assert_(success)

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
            val = self.new_temporary_value(typ)
            self.builder.calldatacopy(val.operand, offset, IRLiteral(size))
            return val.operand

    _ALLOCATION_LIMIT: int = 2**64

    def allocate_buffer(self, size: int, annotation: Optional[str] = None) -> Buffer:
        """Allocate anonymous memory buffer. Use buf.base_ptr() to get a Ptr."""
        if size >= self._ALLOCATION_LIMIT:
            raise MemoryAllocationException(
                f"Tried to allocate {size} bytes! (limit is {self._ALLOCATION_LIMIT} (2**64) bytes)"
            )
        alloca_id = self.new_alloca_id()
        ptr = self.builder.alloca(size, alloca_id)
        return Buffer(_ptr=ptr, size=size, annotation=annotation)

    # === Storage Operations ===

    # Storage is word-addressed (word_scale=1): slot N is at slot N, not byte N*32.
    # This differs from memory which is byte-addressed (word_scale=32).

    def load_storage(self, slot: IROperand, typ: VyperType) -> IROperand:
        """Load value from storage slot.

        For primitive types, returns sload result directly.
        For complex types (structs, etc.), allocates memory buffer and copies,
        even for single-word types (needed for ABI encoding and return handling).
        """
        if typ._is_prim_word:
            # Primitive types: return value directly
            return self.builder.sload(slot)
        else:
            # Complex types: always need memory buffer for struct/tuple handling
            val = self.new_temporary_value(typ)
            if typ.storage_size_in_words == 1:
                # Single-word complex type: sload and store to memory
                loaded = self.builder.sload(slot)
                self.builder.mstore(val.operand, loaded)
            else:
                # Multi-word: copy from storage to memory
                self._load_storage_to_memory(slot, val.operand, typ.storage_size_in_words)
            return val.operand

    def store_storage(self, val: IROperand, slot: IROperand, typ: VyperType) -> None:
        """Store value to storage slot.

        For primitive types, direct sstore.
        For complex types, val is memory ptr - load value first or copy.
        """
        if typ._is_prim_word:
            # Primitive types: store value directly
            self.builder.sstore(slot, val)
        elif typ.storage_size_in_words == 1:
            # Single-word complex type: val is memory pointer, load and store
            self.builder.sstore(slot, self.builder.mload(val))
        else:
            # Multi-word: val is memory pointer, copy to storage
            self._store_memory_to_storage(val, slot, typ.storage_size_in_words)

    def storage_to_memory(self, slot: IROperand, buf: IROperand, word_count: int) -> None:
        """Load multi-word storage value to memory buffer.

        Public wrapper for iteration loops and other contexts.
        """
        self._load_storage_to_memory(slot, buf, word_count)

    def slot_to_memory(
        self, slot: IROperand, buf: IROperand, word_count: int, location: DataLocation
    ) -> None:
        """Load multi-word slot-addressed value to memory buffer.

        Generic helper that dispatches based on location (STORAGE or TRANSIENT).
        """
        if location == DataLocation.STORAGE:
            self._load_storage_to_memory(slot, buf, word_count)
        elif location == DataLocation.TRANSIENT:
            self._load_transient_to_memory(slot, buf, word_count)
        else:
            raise CompilerPanic(f"slot_to_memory: unexpected location {location}")

    def memory_to_storage(self, buf: IROperand, slot: IROperand, word_count: int) -> None:
        """Store memory buffer to multi-word storage.

        Public wrapper for assignment contexts.
        """
        self._store_memory_to_storage(buf, slot, word_count)

    def code_to_memory(self, offset: IROperand, dst: IROperand, word_count: int) -> None:
        """Copy multi-word immutable from CODE to memory."""
        b = self.builder
        for i in range(word_count):
            byte_offset = i * 32
            if byte_offset == 0:
                imm_offset = offset
            elif isinstance(offset, IRLiteral):
                imm_offset = IRLiteral(offset.value + byte_offset)
            else:
                imm_offset = b.add(offset, IRLiteral(byte_offset))

            if self.immutables_alloca is not None:
                ptr = b.gep(self.immutables_alloca, imm_offset)
                word = b.mload(ptr)
            else:
                word = b.dload(imm_offset)

            if byte_offset == 0:
                mem_ptr = dst
            elif isinstance(dst, IRLiteral):
                mem_ptr = IRLiteral(dst.value + byte_offset)
            else:
                mem_ptr = b.add(dst, IRLiteral(byte_offset))

            b.mstore(mem_ptr, word)

    def _load_storage_to_memory(self, slot: IROperand, buf: IROperand, word_count: int) -> None:
        """Load multi-word storage value to memory buffer.

        Storage is word-addressed, memory is byte-addressed.
        Always emits IR loop (matches legacy `repeat` behavior).
        """
        b = self.builder

        # Create blocks
        cond_block = b.create_block("s2m_cond")
        body_block = b.create_block("s2m_body")
        exit_block = b.create_block("s2m_exit")

        # Entry: counter = 0, jump to cond
        counter = b.assign(IRLiteral(0))
        b.jmp(cond_block.label)

        # Condition block: if counter == word_count, goto exit, else goto body
        b.append_block(cond_block)
        b.set_block(cond_block)
        done = b.eq(counter, IRLiteral(word_count))
        cond_finish = b.current_block

        # Body block
        b.append_block(body_block)
        b.set_block(body_block)

        # Storage slot = base_slot + counter (storage is word-addressed)
        current_slot = b.add(slot, counter)
        val = b.sload(current_slot)

        # Memory offset = buf + counter * 32 (memory is byte-addressed)
        mem_offset = b.add(buf, b.mul(counter, IRLiteral(32)))
        b.mstore(mem_offset, val)

        # Increment counter and jump back to cond
        new_counter = b.add(counter, IRLiteral(1))
        b.assign_to(new_counter, counter)
        b.jmp(cond_block.label)

        # Add conditional jump from cond block (after body processed)
        cond_finish.append_instruction("jnz", done, exit_block.label, body_block.label)

        # Exit block
        b.append_block(exit_block)
        b.set_block(exit_block)

    def _store_memory_to_storage(self, buf: IROperand, slot: IROperand, word_count: int) -> None:
        """Store memory buffer to multi-word storage.

        Memory is byte-addressed, storage is word-addressed.
        Always emits IR loop (matches legacy `repeat` behavior).
        """
        b = self.builder

        # Create blocks
        cond_block = b.create_block("m2s_cond")
        body_block = b.create_block("m2s_body")
        exit_block = b.create_block("m2s_exit")

        # Entry: counter = 0, jump to cond
        counter = b.assign(IRLiteral(0))
        b.jmp(cond_block.label)

        # Condition block: if counter == word_count, goto exit, else goto body
        b.append_block(cond_block)
        b.set_block(cond_block)
        done = b.eq(counter, IRLiteral(word_count))
        cond_finish = b.current_block

        # Body block
        b.append_block(body_block)
        b.set_block(body_block)

        # Memory offset = buf + counter * 32 (memory is byte-addressed)
        mem_offset = b.add(buf, b.mul(counter, IRLiteral(32)))
        val = b.mload(mem_offset)

        # Storage slot = base_slot + counter (storage is word-addressed)
        current_slot = b.add(slot, counter)
        b.sstore(current_slot, val)

        # Increment counter and jump back to cond
        new_counter = b.add(counter, IRLiteral(1))
        b.assign_to(new_counter, counter)
        b.jmp(cond_block.label)

        # Add conditional jump from cond block (after body processed)
        cond_finish.append_instruction("jnz", done, exit_block.label, body_block.label)

        # Exit block
        b.append_block(exit_block)
        b.set_block(exit_block)

    # === Transient Storage (EIP-1153, Cancun+) ===

    def load_transient(self, slot: IROperand, typ: VyperType) -> IROperand:
        """Load from transient storage (Cancun+).

        For primitive types, returns tload result directly.
        For complex types (structs, etc.), allocates memory buffer and copies,
        even for single-word types (needed for ABI encoding and return handling).
        """
        if typ._is_prim_word:
            # Primitive types: return value directly
            return self.builder.tload(slot)
        else:
            # Complex types: always need memory buffer for struct/tuple handling
            val = self.new_temporary_value(typ)
            if typ.storage_size_in_words == 1:
                # Single-word complex type: tload and store to memory
                loaded = self.builder.tload(slot)
                self.builder.mstore(val.operand, loaded)
            else:
                # Multi-word: copy from transient storage to memory
                self._load_transient_to_memory(slot, val.operand, typ.storage_size_in_words)
            return val.operand

    def store_transient(self, val: IROperand, slot: IROperand, typ: VyperType) -> None:
        """Store to transient storage (Cancun+).

        For primitive types, direct tstore.
        For complex types, val is memory ptr - load value first or copy.
        """
        if typ._is_prim_word:
            # Primitive types: store value directly
            self.builder.tstore(slot, val)
        elif typ.storage_size_in_words == 1:
            # Single-word complex type: val is memory pointer, load and store
            self.builder.tstore(slot, self.builder.mload(val))
        else:
            # Multi-word: val is memory pointer, copy to transient storage
            self._store_memory_to_transient(val, slot, typ.storage_size_in_words)

    def _load_transient_to_memory(self, slot: IROperand, buf: IROperand, word_count: int) -> None:
        """Load multi-word transient storage value to memory buffer.

        Always emits IR loop (matches legacy `repeat` behavior).
        """
        b = self.builder

        # Create blocks
        cond_block = b.create_block("t2m_cond")
        body_block = b.create_block("t2m_body")
        exit_block = b.create_block("t2m_exit")

        # Entry: counter = 0, jump to cond
        counter = b.assign(IRLiteral(0))
        b.jmp(cond_block.label)

        # Condition block: if counter == word_count, goto exit, else goto body
        b.append_block(cond_block)
        b.set_block(cond_block)
        done = b.eq(counter, IRLiteral(word_count))
        cond_finish = b.current_block

        # Body block
        b.append_block(body_block)
        b.set_block(body_block)

        # Transient slot = base_slot + counter (word-addressed)
        current_slot = b.add(slot, counter)
        val = b.tload(current_slot)

        # Memory offset = buf + counter * 32 (byte-addressed)
        mem_offset = b.add(buf, b.mul(counter, IRLiteral(32)))
        b.mstore(mem_offset, val)

        # Increment counter and jump back to cond
        new_counter = b.add(counter, IRLiteral(1))
        b.assign_to(new_counter, counter)
        b.jmp(cond_block.label)

        # Add conditional jump from cond block (after body processed)
        cond_finish.append_instruction("jnz", done, exit_block.label, body_block.label)

        # Exit block
        b.append_block(exit_block)
        b.set_block(exit_block)

    def _store_memory_to_transient(self, buf: IROperand, slot: IROperand, word_count: int) -> None:
        """Store memory buffer to multi-word transient storage.

        Always emits IR loop (matches legacy `repeat` behavior).
        """
        b = self.builder

        # Create blocks
        cond_block = b.create_block("m2t_cond")
        body_block = b.create_block("m2t_body")
        exit_block = b.create_block("m2t_exit")

        # Entry: counter = 0, jump to cond
        counter = b.assign(IRLiteral(0))
        b.jmp(cond_block.label)

        # Condition block: if counter == word_count, goto exit, else goto body
        b.append_block(cond_block)
        b.set_block(cond_block)
        done = b.eq(counter, IRLiteral(word_count))
        cond_finish = b.current_block

        # Body block
        b.append_block(body_block)
        b.set_block(body_block)

        # Memory offset = buf + counter * 32 (byte-addressed)
        mem_offset = b.add(buf, b.mul(counter, IRLiteral(32)))
        val = b.mload(mem_offset)

        # Transient slot = base_slot + counter (word-addressed)
        current_slot = b.add(slot, counter)
        b.tstore(current_slot, val)

        # Increment counter and jump back to cond
        new_counter = b.add(counter, IRLiteral(1))
        b.assign_to(new_counter, counter)
        b.jmp(cond_block.label)

        # Add conditional jump from cond block (after body processed)
        cond_finish.append_instruction("jnz", done, exit_block.label, body_block.label)

        # Exit block
        b.append_block(exit_block)
        b.set_block(exit_block)

    # === Immutables ===

    # Immutables are stored in bytecode (CODE location), accessed via iload/istore.
    # They are byte-addressed (word_scale=32), like memory.

    def load_immutable(self, offset: IROperand, typ: VyperType) -> IROperand:
        """Load immutable value from deployed bytecode (runtime).

        For primitive word types, returns dload result directly.
        For complex types (structs, arrays), allocates memory buffer and copies.
        """
        if typ._is_prim_word:
            return self.builder.dload(offset)
        else:
            # Multi-word immutable: copy to memory buffer
            val = self.new_temporary_value(typ)
            buf = val.operand
            size = typ.memory_bytes_required
            for i in range(0, size, 32):
                # Immutables are byte-addressed
                if i == 0:
                    imm_offset = offset
                elif isinstance(offset, IRLiteral):
                    imm_offset = IRLiteral(offset.value + i)
                else:
                    imm_offset = self.builder.add(offset, IRLiteral(i))

                word = self.builder.dload(imm_offset)

                # Memory is byte-addressed
                mem_ptr: IROperand
                if i == 0:
                    mem_ptr = buf
                elif isinstance(buf, IRLiteral):
                    mem_ptr = IRLiteral(buf.value + i)
                else:
                    mem_ptr = self.builder.add(buf, IRLiteral(i))

                self.builder.mstore(mem_ptr, word)

            return buf

    def load_immutable_ctor(self, offset: IROperand, typ: VyperType) -> IROperand:
        """Load immutable value during constructor (uses GEP + mload).

        For primitive word types, returns single mload result directly.
        For complex types (structs, arrays), allocates memory buffer and copies.
        """
        if typ._is_prim_word:
            if self.immutables_alloca is not None:
                ptr = self.builder.gep(self.immutables_alloca, offset)
                return self.builder.mload(ptr)
            return self.builder.iload(offset)
        else:
            # Multi-word immutable: copy to memory buffer
            val = self.new_temporary_value(typ)
            buf = val.operand
            size = typ.memory_bytes_required
            for i in range(0, size, 32):
                # Immutables are byte-addressed
                if i == 0:
                    imm_offset = offset
                elif isinstance(offset, IRLiteral):
                    imm_offset = IRLiteral(offset.value + i)
                else:
                    imm_offset = self.builder.add(offset, IRLiteral(i))

                if self.immutables_alloca is not None:
                    ptr = self.builder.gep(self.immutables_alloca, imm_offset)
                    word = self.builder.mload(ptr)
                else:
                    word = self.builder.iload(imm_offset)

                # Memory is byte-addressed
                mem_ptr: IROperand
                if i == 0:
                    mem_ptr = buf
                elif isinstance(buf, IRLiteral):
                    mem_ptr = IRLiteral(buf.value + i)
                else:
                    mem_ptr = self.builder.add(buf, IRLiteral(i))

                self.builder.mstore(mem_ptr, word)

            return buf

    def store_immutable(self, val: IROperand, offset: IROperand, typ: VyperType) -> None:
        """Store immutable value (during constructor only).

        For primitive types (<=32 bytes), direct mstore via GEP.
        For multi-word types, val is memory ptr, copy to immutables.
        """
        if typ.memory_bytes_required <= 32:
            if self.immutables_alloca is not None:
                ptr = self.builder.gep(self.immutables_alloca, offset)
                self.builder.mstore(ptr, val)
            else:
                self.builder.istore(offset, val)
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

                if self.immutables_alloca is not None:
                    ptr = self.builder.gep(self.immutables_alloca, imm_offset)
                    self.builder.mstore(ptr, word)
                else:
                    self.builder.istore(imm_offset, word)

    # === Dynamic Array Length ===

    def get_dyn_array_length(self, ptr: Ptr) -> IROperand:
        """Get length of dynamic array. Works for any location."""
        return self.ptr_load(ptr)

    def set_dyn_array_length(self, ptr: Ptr, length: IROperand) -> None:
        """Set length of dynamic array. Works for any location."""
        self.ptr_store(ptr, length)

    # === Ptr Operations ===

    def add_offset(self, p: Ptr, n: IROperand | int) -> Ptr:
        """Add an offset to a pointer. Preserves location and buf."""
        if isinstance(n, int):
            n = IRLiteral(n)
        new_operand = self.builder.add(p.operand, n)
        return Ptr(operand=new_operand, location=p.location, buf=p.buf)

    def ptr_load(self, src: Ptr) -> IROperand:
        """Load 32-byte value from pointer. Dispatches on location."""
        if src.location == DataLocation.MEMORY:
            return self.builder.mload(src.operand)
        elif src.location == DataLocation.STORAGE:
            return self.builder.sload(src.operand)
        elif src.location == DataLocation.TRANSIENT:
            return self.builder.tload(src.operand)
        elif src.location == DataLocation.CALLDATA:
            return self.builder.calldataload(src.operand)
        elif src.location == DataLocation.CODE:
            # Immutables: ctor context uses GEP from immutables_alloca, runtime uses dload
            if self.is_ctor_context:
                if self.immutables_alloca is not None:
                    # Use GEP to get proper memory address within immutables region
                    ptr = self.builder.gep(self.immutables_alloca, src.operand)
                    return self.builder.mload(ptr)
                return self.builder.iload(src.operand)
            return self.builder.dload(src.operand)
        else:
            raise CompilerPanic(f"cannot load from: {src.location}")

    def ptr_store(self, dst: Ptr, val: IROperand) -> None:
        """Store 32-byte value to pointer. Dispatches on location."""
        if dst.location == DataLocation.MEMORY:
            self.builder.mstore(dst.operand, val)
        elif dst.location == DataLocation.STORAGE:
            self.builder.sstore(dst.operand, val)
        elif dst.location == DataLocation.TRANSIENT:
            self.builder.tstore(dst.operand, val)
        elif dst.location == DataLocation.CODE:
            # Immutables in constructor context - use GEP from immutables_alloca
            if self.immutables_alloca is not None:
                ptr = self.builder.gep(self.immutables_alloca, dst.operand)
                self.builder.mstore(ptr, val)
            else:
                self.builder.istore(dst.operand, val)
        else:
            raise CompilerPanic(f"cannot store to: {dst.location}")
