import contextlib
import enum
from dataclasses import dataclass
from typing import Any, Optional

from vyper.codegen.ir_node import Encoding, IRnode
from vyper.compiler.settings import get_global_settings
from vyper.evm.address_space import MEMORY, AddrSpace
from vyper.exceptions import CompilerPanic, StateAccessViolation
from vyper.semantics.types import VyperType


class Constancy(enum.Enum):
    Mutable = 0
    Constant = 1


@dataclass(frozen=True)
class Alloca:
    name: str
    pos: int
    typ: VyperType
    size: int

    def __post_init__(self):
        assert self.typ.memory_bytes_required == self.size


# Function variable
@dataclass
class VariableRecord:
    name: str
    pos: int
    typ: VyperType
    mutable: bool
    encoding: Encoding = Encoding.VYPER
    location: AddrSpace = MEMORY
    size: Optional[int] = None  # allocated size
    blockscopes: Optional[list] = None
    defined_at: Any = None
    is_internal: bool = False

    # the following members are probably dead
    is_immutable: bool = False
    is_transient: bool = False
    data_offset: Optional[int] = None

    def __hash__(self):
        return hash(id(self))

    def __post_init__(self):
        if self.blockscopes is None:
            self.blockscopes = []

    def __repr__(self):
        ret = vars(self)
        ret["allocated"] = self.typ.memory_bytes_required
        return f"VariableRecord({ret})"

    def as_ir_node(self):
        ret = IRnode.from_list(
            self.pos,
            typ=self.typ,
            annotation=self.name,
            encoding=self.encoding,
            mutable=self.mutable,
        )
        ret._referenced_vars = {self}
        if self.location == MEMORY:  # don't need alloca in other locations
            ret.passthrough_metadata["alloca"] = Alloca(
                name=self.name, pos=self.pos, typ=self.typ, size=self.typ.memory_bytes_required
            )
        return ret


# compilation context for a function
class Context:
    def __init__(
        self,
        module_ctx,
        memory_allocator,
        vars_=None,
        forvars=None,
        constancy=Constancy.Mutable,
        func_t=None,
        is_ctor_context=False,
    ):
        # In-memory variables, in the form (name, memory location, type)
        self.vars = vars_ or {}

        # Variables defined in for loops, e.g. for i in range(6): ...
        self.forvars = forvars or {}

        # Is the function constant?
        self.constancy = constancy

        # Whether we are currently parsing a range expression
        self.in_range_expr = False

        # store module context
        self.module_ctx = module_ctx

        # full function type
        self.func_t = func_t
        # Active scopes
        self._scopes = set()

        # Memory allocator, keeps track of currently allocated memory.
        # Not intended to be accessed directly
        self.memory_allocator = memory_allocator

        # save the starting memory location so we can find out (later)
        # how much memory this function uses.
        self.starting_memory = memory_allocator.next_mem

        # Incremented values, used for internal IDs
        self._internal_var_iter = 0
        self._scope_id_iter = 0

        # either the constructor, or called from the constructor
        self.is_ctor_context = is_ctor_context

        self.settings = get_global_settings()

    def is_constant(self):
        return self.constancy is Constancy.Constant or self.in_range_expr

    def check_is_not_constant(self, err, expr):
        if self.is_constant():
            raise StateAccessViolation(f"Cannot {err} from {self.pp_constancy()}", expr)

    def get_var(self, name):
        return self.vars[name]

    # convenience properties
    @property
    def is_payable(self):
        return self.func_t.is_payable

    @property
    def is_internal(self):
        return self.func_t.is_internal

    @property
    def return_type(self):
        return self.func_t.return_type

    #
    # Context Managers
    # - Context managers are used to ensure proper wrapping of scopes and context states.

    @contextlib.contextmanager
    def range_scope(self):
        prev_value = self.in_range_expr
        self.in_range_expr = True
        yield
        self.in_range_expr = prev_value

    @contextlib.contextmanager
    def internal_memory_scope(self):
        """
        Internal memory scope context manager.

        Internal variables that are declared within this context are de-allocated
        upon exiting the context.
        """
        scope_id = self._scope_id_iter
        self._scope_id_iter += 1
        self._scopes.add(scope_id)
        yield

        # Remove all variables that have specific scope_id attached
        released = [
            (k, v) for k, v in self.vars.items() if v.is_internal and scope_id in v.blockscopes
        ]
        for name, var in released:
            self.deallocate_variable(name, var)

        # Remove block scopes
        self._scopes.remove(scope_id)

    @contextlib.contextmanager
    def block_scope(self):
        """
        Block scope context manager.

        All variables (public and internal) that are declared within this context
        are de-allocated upon exiting the context.
        """
        scope_id = self._scope_id_iter
        self._scope_id_iter += 1
        self._scopes.add(scope_id)
        yield

        # Remove all variables that have specific scope_id attached
        released = [(k, v) for k, v in self.vars.items() if scope_id in v.blockscopes]
        for name, var in released:
            self.deallocate_variable(name, var)

        # Remove block scopes
        self._scopes.remove(scope_id)

    def deallocate_variable(self, varname, var):
        assert varname == var.name

        # sanity check the type's size hasn't changed since allocation.
        n = var.typ.memory_bytes_required
        assert n == var.size

        if self.settings.experimental_codegen:
            # do not deallocate at this stage because this will break
            # analysis in venom; venom will do its own alloc/dealloc/analysis.
            pass
        else:
            self.memory_allocator.deallocate_memory(var.pos, var.size)

        del self.vars[var.name]

    def _new_variable(
        self, name: str, typ: VyperType, var_size: int, is_internal: bool, is_mutable: bool = True
    ) -> IRnode:
        var_pos = self.memory_allocator.allocate_memory(var_size)

        assert var_pos + var_size <= self.memory_allocator.size_of_mem, "function frame overrun"

        var = VariableRecord(
            name=name,
            pos=var_pos,
            typ=typ,
            size=var_size,
            mutable=is_mutable,
            blockscopes=self._scopes.copy(),
            is_internal=is_internal,
        )
        self.vars[name] = var
        return var.as_ir_node()

    def new_variable(self, name: str, typ: VyperType, is_mutable: bool = True) -> IRnode:
        """
        Allocate memory for a user-defined variable and return an IR node referencing it.

        Arguments
        ---------
        name : str
            Name of the variable
        typ : VyperType
            Variable type, used to determine the size of memory allocation

        Returns
        -------
        int
            Memory offset for the variable
        """

        var_size = typ.memory_bytes_required
        return self._new_variable(name, typ, var_size, False, is_mutable=is_mutable)

    def fresh_varname(self, name: str) -> str:
        """
        return a unique variable name
        """
        t = self._internal_var_iter
        self._internal_var_iter += 1
        return f"{name}{t}"

    # do we ever allocate immutable internal variables?
    def new_internal_variable(self, typ: VyperType) -> IRnode:
        """
        Allocate memory for an internal variable.

        Arguments
        ---------
        typ : VyperType
            Variable type, used to determine the size of memory allocation

        Returns
        -------
        int
            Memory offset for the variable
        """
        # internal variable names begin with a number sign so there is no chance for collision
        name = self.fresh_varname("#internal")

        var_size = typ.memory_bytes_required
        return self._new_variable(name, typ, var_size, True)

    def lookup_var(self, varname) -> VariableRecord:
        return self.vars[varname]

    # Pretty print constancy for error messages
    def pp_constancy(self):
        if self.in_range_expr:
            return "a range expression"
        elif self.constancy == Constancy.Constant:
            return "a constant function"
        raise CompilerPanic(f"bad constancy: {self.constancy}")  # pragma: nocover
