from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from vyper.semantics.types import VyperType
from vyper.semantics.types.function import ContractFunctionT
from vyper.semantics.types.module import ModuleT
from vyper.venom.basicblock import IRLabel, IRVariable
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
