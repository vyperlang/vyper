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

from vyper.codegen_venom.buffer import Buffer, Ptr
from vyper.codegen_venom.constants import IDENTITY_PRECOMPILE
from vyper.codegen_venom.value import VyperValue
from vyper.evm.opcodes import version_check
from vyper.exceptions import CompilerPanic, MemoryAllocationException, StateAccessViolation
from vyper.semantics.data_locations import DataLocation
from vyper.semantics.types import TupleT, VyperType
from vyper.semantics.types.bytestrings import _BytestringT
from vyper.semantics.types.function import ContractFunctionT, StateMutability
from vyper.semantics.types.module import ModuleT
from vyper.semantics.types.subscriptable import DArrayT, SArrayT
from vyper.semantics.types.user import StructT
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

    # Immutables region alloca (for constructor context).
    # Reserves memory at position 0 for immutables staging;
    # used by deploy epilogue to copy staging area into bytecode.
    immutables_alloca: Optional[IRVariable] = None

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
        - If complex type (>32 bytes): return operand as pointer (or copy)
        - Otherwise: emit load instruction and return the loaded value
        """
        if vv.location is None:
            return vv.operand

        # Complex types (>32 bytes)
        if vv.typ is not None and not vv.typ._is_prim_word:
            if vv.location == DataLocation.IMMUTABLES:
                return self.load_immutable_to_memory(vv.operand, vv.typ)
            if vv.location == DataLocation.STORAGE:
                return self.load_storage_to_memory(vv.operand, vv.typ)
            if vv.location == DataLocation.TRANSIENT:
                return self.load_transient_to_memory(vv.operand, vv.typ)
            # MEMORY location: return pointer directly
            return vv.operand

        # Primitive word type: emit load based on location
        return self.load_word(vv.operand, vv.location)

    def store_vyper_value(
        self, vv: VyperValue, ptr: IROperand, typ: Optional[VyperType] = None
    ) -> None:
        """Store a VyperValue into memory, preserving its source layout."""
        if typ is None:
            typ = vv.typ
        self.store_memory(self.unwrap(vv), ptr, typ, src_typ=vv.typ)

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
        return self._with_byte_offset(vv.operand, word_scale)

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

    def load_word(self, addr: IROperand, location: DataLocation) -> IROperand:
        """Load a single word from addr at the given location.

        Handles IMMUTABLES via iload (ctor) or dload (runtime).
        CODE always uses dload (for constructor args in code section).
        """
        if location == DataLocation.IMMUTABLES:
            if self.is_ctor_context:
                return self.builder.iload(addr)
            return self.builder.dload(addr)
        # NOTE: CODE falls through to builder.load (dload). If a future
        # code path needs ctor-aware CODE loads, add an explicit branch here.
        return self.builder.load(addr, location)

    def ensure_bytestring_in_memory(self, vv: VyperValue, typ: _BytestringT) -> VyperValue:
        """Return a bytestring value guaranteed to be in memory.

        Hashing and certain builtins require memory-backed bytestring data.
        STORAGE/TRANSIENT/CODE values are copied into a temporary memory buffer.
        """
        if vv.location is DataLocation.STORAGE or vv.location is DataLocation.TRANSIENT:
            buf_val = self.new_temporary_value(typ)
            self.slot_to_memory(vv.operand, buf_val.operand, typ.storage_size_in_words, vv.location)
            return buf_val

        if vv.location is DataLocation.IMMUTABLES:
            buf_val = self.new_temporary_value(typ)
            self.copy_to_memory(
                buf_val.operand, vv.operand, typ.memory_bytes_required, DataLocation.IMMUTABLES
            )
            return buf_val

        assert vv.location is None or vv.location is DataLocation.MEMORY
        return vv

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

    def store_memory(
        self, val: IROperand, ptr: IROperand, typ: VyperType, src_typ: Optional[VyperType] = None
    ) -> None:
        """Store value to memory pointer.

        For primitive word types, stores the value directly via mstore.
        For complex types (structs, arrays), val is a source pointer and
        we copy from val to ptr.
        For bytestrings, copies actual length from source, not max size.

        Note: Single-word structs are NOT primitive word types - they are
        complex types that happen to fit in one word. The caller passes
        a pointer to struct data, not the struct value itself.
        """
        if src_typ is None:
            src_typ = typ

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
        elif src_typ != typ:
            # Layout-aware copy for assignments between compatible but not
            # identical memory layouts (e.g. DynArray[Bytes[540]] -> DynArray[Bytes[704]]).
            self._store_memory_typed(dst=ptr, dst_typ=typ, src=val, src_typ=src_typ)
        else:
            # Complex type: val is a pointer, copy memory
            self.copy_memory(ptr, val, typ.memory_bytes_required)

    def _store_memory_typed(
        self, dst: IROperand, dst_typ: VyperType, src: IROperand, src_typ: VyperType
    ) -> None:
        """Store memory value with potential source/destination type layout differences."""
        if dst_typ._is_prim_word:
            self.builder.mstore(dst, self.builder.mload(src))
            return

        if isinstance(dst_typ, _BytestringT) and isinstance(src_typ, _BytestringT):
            # Bytes/string assignment is value-based: copy actual runtime length.
            self.store_memory(src, dst, dst_typ)
            return

        if isinstance(dst_typ, DArrayT) and isinstance(src_typ, DArrayT):
            self._copy_dynarray_memory_typed(dst, dst_typ, src, src_typ)
            return

        if isinstance(dst_typ, SArrayT) and isinstance(src_typ, SArrayT):
            assert src_typ.count == dst_typ.count
            self._copy_sarray_memory_typed(dst, dst_typ, src, src_typ)
            return

        if isinstance(dst_typ, TupleT) and isinstance(src_typ, TupleT):
            dst_ofst = 0
            src_ofst = 0
            for dst_member_t, src_member_t in zip(dst_typ.member_types, src_typ.member_types):
                dst_ptr = self._with_byte_offset(dst, dst_ofst)
                src_ptr = self._with_byte_offset(src, src_ofst)
                self._store_memory_typed(dst_ptr, dst_member_t, src_ptr, src_member_t)
                dst_ofst += dst_member_t.memory_bytes_required
                src_ofst += src_member_t.memory_bytes_required
            return

        if isinstance(dst_typ, StructT) and isinstance(src_typ, StructT):
            dst_ofst = 0
            src_ofst = 0
            for name, dst_member_t in dst_typ.member_types.items():
                src_member_t = src_typ.member_types[name]
                dst_ptr = self._with_byte_offset(dst, dst_ofst)
                src_ptr = self._with_byte_offset(src, src_ofst)
                self._store_memory_typed(dst_ptr, dst_member_t, src_ptr, src_member_t)
                dst_ofst += dst_member_t.memory_bytes_required
                src_ofst += src_member_t.memory_bytes_required
            return

        raise CompilerPanic(f"_store_memory_typed: unhandled types {src_typ} -> {dst_typ}")

    def _copy_sarray_memory_typed(
        self, dst: IROperand, dst_typ: SArrayT, src: IROperand, src_typ: SArrayT
    ) -> None:
        """Copy SArray in memory when source and destination element layouts
        may differ.

        Mirrors the legacy codegen heuristic (_complex_make_setter):
        batch-copy when element layouts match and no dynamic-sized children;
        otherwise emit a runtime loop that copies element-by-element.
        """
        count = src_typ.count
        dst_elem_t = dst_typ.value_type
        src_elem_t = src_typ.value_type
        dst_elem_size = dst_elem_t.memory_bytes_required
        src_elem_size = src_elem_t.memory_bytes_required

        # Fast path: batch copy when element layouts match and there is no
        # dynamic-sized data (same heuristic as legacy _complex_make_setter).
        if dst_elem_size == src_elem_size and not dst_typ.abi_type.is_dynamic():
            self.copy_memory(dst, src, dst_typ.memory_bytes_required)
            return

        # Slow path: runtime loop, element-by-element copy.
        b = self.builder
        length = IRLiteral(count)

        cond_block = b.create_block("typed_sa_copy_cond")
        body_block = b.create_block("typed_sa_copy_body")
        exit_block = b.create_block("typed_sa_copy_exit")

        counter = b.assign(IRLiteral(0))
        b.jmp(cond_block.label)

        b.append_block(cond_block)
        b.set_block(cond_block)
        done = b.iszero(b.lt(counter, length))
        cond_finish = b.current_block

        b.append_block(body_block)
        b.set_block(body_block)

        src_ofst = b.mul(counter, IRLiteral(src_elem_size))
        dst_ofst = b.mul(counter, IRLiteral(dst_elem_size))
        src_elem_ptr = b.add(src, src_ofst)
        dst_elem_ptr = b.add(dst, dst_ofst)

        self._store_memory_typed(dst_elem_ptr, dst_elem_t, src_elem_ptr, src_elem_t)

        new_counter = b.add(counter, IRLiteral(1))
        b.assign_to(new_counter, counter)
        b.jmp(cond_block.label)

        cond_finish.append_instruction("jnz", done, exit_block.label, body_block.label)
        b.append_block(exit_block)
        b.set_block(exit_block)

    def _copy_dynarray_memory_typed(
        self, dst: IROperand, dst_typ: DArrayT, src: IROperand, src_typ: DArrayT
    ) -> None:
        """Copy DynArray in memory when source and destination element layouts may differ."""
        b = self.builder
        length = b.mload(src)
        # defensive: runtime length must not exceed destination capacity
        b.assert_(b.iszero(b.gt(length, IRLiteral(dst_typ.length))))
        b.mstore(dst, length)

        dst_elem_t = dst_typ.value_type
        src_elem_t = src_typ.value_type
        dst_elem_size = dst_elem_t.memory_bytes_required
        src_elem_size = src_elem_t.memory_bytes_required

        src_data = self._with_byte_offset(src, 32)
        dst_data = self._with_byte_offset(dst, 32)

        # Fast path when element layouts match: copy exactly `length` elements.
        if src_elem_t == dst_elem_t and src_elem_size == dst_elem_size:
            data_size = b.mul(length, IRLiteral(dst_elem_size))
            self.copy_memory_dynamic(dst_data, src_data, data_size)
            return

        cond_block = b.create_block("typed_dyn_copy_cond")
        body_block = b.create_block("typed_dyn_copy_body")
        exit_block = b.create_block("typed_dyn_copy_exit")

        counter = b.assign(IRLiteral(0))
        b.jmp(cond_block.label)

        b.append_block(cond_block)
        b.set_block(cond_block)
        done = b.iszero(b.lt(counter, length))
        cond_finish = b.current_block

        b.append_block(body_block)
        b.set_block(body_block)

        src_ofst = b.mul(counter, IRLiteral(src_elem_size))
        dst_ofst = b.mul(counter, IRLiteral(dst_elem_size))
        src_elem_ptr = b.add(src_data, src_ofst)
        dst_elem_ptr = b.add(dst_data, dst_ofst)

        self._store_memory_typed(dst_elem_ptr, dst_elem_t, src_elem_ptr, src_elem_t)

        new_counter = b.add(counter, IRLiteral(1))
        b.assign_to(new_counter, counter)
        b.jmp(cond_block.label)

        cond_finish.append_instruction("jnz", done, exit_block.label, body_block.label)
        b.append_block(exit_block)
        b.set_block(exit_block)

    # Threshold for using identity precompile vs unrolling (pre-Cancun).
    # Identity precompile has ~25 bytes overhead, unrolling is ~15 bytes/word.
    # For 3+ words, identity precompile produces smaller bytecode.
    _IDENTITY_PRECOMPILE_THRESHOLD = 96  # 3 words

    def _with_byte_offset(self, base: IROperand, byte_offset: int) -> IROperand:
        """Add a compile-time byte offset to an operand, preserving literals."""
        if byte_offset == 0:
            return base
        if isinstance(base, IRLiteral):
            return IRLiteral(base.value + byte_offset)
        return self.builder.add(base, IRLiteral(byte_offset))

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
            src_ptr = self._with_byte_offset(src, offset)
            dst_ptr = self._with_byte_offset(dst, offset)
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

    def load_storage_to_memory(self, slot: IROperand, typ: VyperType) -> IROperand:
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
        """Load word_count words from slot-addressed location to memory buffer.

        For slot-addressed locations (storage, transient) where slots
        increment by 1.  For byte-addressed locations, use copy_to_memory.
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

    def copy_to_memory(
        self, dst: IROperand, src: IROperand, size: int, location: DataLocation
    ) -> None:
        """Copy size bytes from src at location into dst (memory).

        For byte-addressed locations (memory, code, immutables, calldata).
        Word-by-word using load_word, so IMMUTABLES is handled correctly
        in both constructor and runtime contexts.

        For slot-addressed locations (storage, transient), use slot_to_memory.
        """
        # TODO: refactor — DataLocation should have word_scale/word_addressable
        # properties (like AddrSpace does) instead of hardcoding this.
        _byte_addressed = (
            DataLocation.MEMORY,
            DataLocation.CODE,
            DataLocation.IMMUTABLES,
            DataLocation.CALLDATA,
        )
        assert (
            location in _byte_addressed
        ), f"copy_to_memory: expected byte-addressed location, got {location}"
        for i in range(0, size, 32):
            src_ptr = self._with_byte_offset(src, i)
            dst_ptr = self._with_byte_offset(dst, i)
            word = self.load_word(src_ptr, location)
            self.builder.mstore(dst_ptr, word)

    def _word_copy_loop(
        self,
        src_addr: IROperand,
        dst_addr: IROperand,
        word_count: int,
        load_fn,
        store_fn,
        src_scale: int,
        dst_scale: int,
        prefix: str,
    ) -> None:
        """Emit a word-copy loop between two address spaces.

        Parameterized over load/store functions and addressing scales.
        Slot-addressed spaces (storage, transient) use scale=1.
        Byte-addressed spaces (memory) use scale=32.

        Used for storage↔memory and transient↔memory bulk copies.
        One parameterized loop → one HOL inductive proof covers all 4 directions.
        """
        b = self.builder

        cond_block = b.create_block(f"{prefix}_cond")
        body_block = b.create_block(f"{prefix}_body")
        exit_block = b.create_block(f"{prefix}_exit")

        counter = b.assign(IRLiteral(0))
        b.jmp(cond_block.label)

        b.append_block(cond_block)
        b.set_block(cond_block)
        done = b.eq(counter, IRLiteral(word_count))
        cond_finish = b.current_block

        b.append_block(body_block)
        b.set_block(body_block)

        if src_scale == 1:
            src_offset = b.add(src_addr, counter)
        else:
            src_offset = b.add(src_addr, b.mul(counter, IRLiteral(src_scale)))
        val = load_fn(src_offset)

        if dst_scale == 1:
            dst_offset = b.add(dst_addr, counter)
        else:
            dst_offset = b.add(dst_addr, b.mul(counter, IRLiteral(dst_scale)))
        store_fn(dst_offset, val)

        new_counter = b.add(counter, IRLiteral(1))
        b.assign_to(new_counter, counter)
        b.jmp(cond_block.label)

        cond_finish.append_instruction("jnz", done, exit_block.label, body_block.label)

        b.append_block(exit_block)
        b.set_block(exit_block)

    def _load_storage_to_memory(self, slot: IROperand, buf: IROperand, word_count: int) -> None:
        """Load multi-word storage value to memory buffer."""
        self._word_copy_loop(
            slot, buf, word_count, self.builder.sload, self.builder.mstore, 1, 32, "s2m"
        )

    def _store_memory_to_storage(self, buf: IROperand, slot: IROperand, word_count: int) -> None:
        """Store memory buffer to multi-word storage."""
        self._word_copy_loop(
            buf, slot, word_count, self.builder.mload, self.builder.sstore, 32, 1, "m2s"
        )

    # === Transient Storage (EIP-1153, Cancun+) ===

    def load_transient_to_memory(self, slot: IROperand, typ: VyperType) -> IROperand:
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
        """Load multi-word transient storage value to memory buffer."""
        self._word_copy_loop(
            slot, buf, word_count, self.builder.tload, self.builder.mstore, 1, 32, "t2m"
        )

    def _store_memory_to_transient(self, buf: IROperand, slot: IROperand, word_count: int) -> None:
        """Store memory buffer to multi-word transient storage."""
        self._word_copy_loop(
            buf, slot, word_count, self.builder.mload, self.builder.tstore, 32, 1, "m2t"
        )

    # === Immutables ===

    # Immutables are stored in bytecode (CODE location), accessed via iload/istore.
    # They are byte-addressed (word_scale=32), like memory.

    def load_immutable_to_memory(self, offset: IROperand, typ: VyperType) -> IROperand:
        """Load immutable value into a memory buffer.

        Uses load_word which dispatches correctly for IMMUTABLES
        (iload in ctor, dload at runtime).

        For primitive word types, returns the loaded value directly.
        For complex types, allocates a memory buffer and returns the pointer.
        """
        if typ._is_prim_word:
            return self.load_word(offset, DataLocation.IMMUTABLES)

        val = self.new_temporary_value(typ)
        self.copy_to_memory(val.operand, offset, typ.memory_bytes_required, DataLocation.IMMUTABLES)
        return val.operand

    def store_immutable(self, val: IROperand, offset: IROperand, typ: VyperType) -> None:
        """Store immutable value (during constructor only).

        For primitive types (<=32 bytes), store single word.
        For multi-word types, val is memory ptr, copy word-by-word.
        """
        if typ.memory_bytes_required <= 32:
            self.store_word(offset, val, DataLocation.IMMUTABLES)
        else:
            size = typ.memory_bytes_required
            for i in range(0, size, 32):
                mem_ptr = self._with_byte_offset(val, i)
                word = self.builder.mload(mem_ptr)
                imm_offset = self._with_byte_offset(offset, i)
                self.store_word(imm_offset, word, DataLocation.IMMUTABLES)

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
        return self.load_word(src.operand, src.location)

    def ptr_store(self, dst: Ptr, val: IROperand) -> None:
        """Store 32-byte value to pointer. Dispatches on location."""
        return self.store_word(dst.operand, val, dst.location)

    def store_word(self, addr: IROperand, val: IROperand, location: DataLocation) -> None:
        """Store a single word to addr at the given location."""
        if location == DataLocation.IMMUTABLES:
            self.builder.istore(addr, val)
        elif location == DataLocation.MEMORY:
            self.builder.mstore(addr, val)
        elif location == DataLocation.STORAGE:
            self.builder.sstore(addr, val)
        elif location == DataLocation.TRANSIENT:
            self.builder.tstore(addr, val)
        elif location == DataLocation.CODE:
            raise CompilerPanic("cannot store to CODE")
        else:
            raise CompilerPanic(f"cannot store to: {location}")
