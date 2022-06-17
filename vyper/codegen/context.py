import contextlib
import enum
from typing import Optional

from vyper.ast import VyperNode
from vyper.ast.signatures.function_signature import VariableRecord
from vyper.codegen.types import NodeType
from vyper.exceptions import CompilerPanic, StateAccessViolation


class Constancy(enum.Enum):
    Mutable = 0
    Constant = 1


# Contains arguments, variables, etc
class Context:
    def __init__(
        self,
        global_ctx,
        memory_allocator,
        vars_=None,
        sigs=None,
        forvars=None,
        constancy=Constancy.Mutable,
        sig=None,
    ):
        # In-memory variables, in the form (name, memory location, type)
        self.vars = vars_ or {}

        # Global variables, in the form (name, storage location, type)
        self.globals = global_ctx._globals

        # ABI objects, in the form {classname: ABI JSON}
        self.sigs = sigs or {"self": {}}

        # Variables defined in for loops, e.g. for i in range(6): ...
        self.forvars = forvars or {}

        # Is the function constant?
        self.constancy = constancy

        # Whether body is currently in an assert statement
        self.in_assertion = False

        # Whether we are currently parsing a range expression
        self.in_range_expr = False

        # List of custom structs that have been defined.
        self.structs = global_ctx._structs

        # store global context
        self.global_ctx = global_ctx

        # full function signature
        self.sig = sig
        # Active scopes
        self._scopes = set()

        # Memory alloctor, keeps track of currently allocated memory.
        # Not intended to be accessed directly
        self.memory_allocator = memory_allocator

        # Incremented values, used for internal IDs
        self._internal_var_iter = 0
        self._scope_id_iter = 0

    def is_constant(self):
        return self.constancy is Constancy.Constant or self.in_assertion or self.in_range_expr

    def check_is_not_constant(self, err, expr):
        if self.is_constant():
            raise StateAccessViolation(f"Cannot {err} from {self.pp_constancy()}", expr)

    # convenience propreties
    @property
    def is_payable(self):
        return self.sig.mutability == "payable"

    @property
    def is_internal(self):
        return self.sig.internal

    @property
    def return_type(self):
        return self.sig.return_type

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
            self.memory_allocator.deallocate_memory(var.pos, var.size * 32)
            del self.vars[name]

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
            self.memory_allocator.deallocate_memory(var.pos, var.size * 32)
            del self.vars[name]

        # Remove block scopes
        self._scopes.remove(scope_id)

    def _new_variable(
        self, name: str, typ: NodeType, var_size: int, is_internal: bool, is_mutable: bool = True
    ) -> int:
        if is_internal:
            # TODO CMC 2022-03-02 change this to `.allocate_memory()`
            # and make `expand_memory()` private.
            var_pos = self.memory_allocator.expand_memory(var_size)
        else:
            var_pos = self.memory_allocator.allocate_memory(var_size)

        assert var_pos + var_size <= self.memory_allocator.size_of_mem, "function frame overrun"

        self.vars[name] = VariableRecord(
            name=name,
            pos=var_pos,
            typ=typ,
            mutable=is_mutable,
            blockscopes=self._scopes.copy(),
            is_internal=is_internal,
        )
        return var_pos

    def new_variable(
        self, name: str, typ: NodeType, pos: VyperNode = None, is_mutable: bool = True
    ) -> int:
        # TODO remove dead arg: pos
        """
        Allocate memory for a user-defined variable.

        Arguments
        ---------
        name : str
            Name of the variable
        typ : NodeType
            Variable type, used to determine the size of memory allocation
        pos : VyperNode
            AST node corresponding to the location where the variable was created,
            used for annotating exceptions

        Returns
        -------
        int
            Memory offset for the variable
        """

        if hasattr(typ, "size_in_bytes"):
            # temporary requirement to support both new and old type objects
            var_size = typ.size_in_bytes  # type: ignore
        else:
            var_size = typ.memory_bytes_required
        return self._new_variable(name, typ, var_size, False, is_mutable=is_mutable)

    def fresh_varname(self, name: Optional[str] = None) -> str:
        """
        return a unique
        """
        if name is None:
            name = "var"
        t = self._internal_var_iter
        self._internal_var_iter += 1
        return f"{name}{t}"

    # do we ever allocate immutable internal variables?
    def new_internal_variable(self, typ: NodeType) -> int:
        """
        Allocate memory for an internal variable.

        Arguments
        ---------
        typ : NodeType
            Variable type, used to determine the size of memory allocation

        Returns
        -------
        int
            Memory offset for the variable
        """
        # internal variable names begin with a number sign so there is no chance for collision
        name = self.fresh_varname("#internal")

        if hasattr(typ, "size_in_bytes"):
            # temporary requirement to support both new and old type objects
            var_size = typ.size_in_bytes  # type: ignore
        else:
            var_size = typ.memory_bytes_required
        return self._new_variable(name, typ, var_size, True)

    def parse_type(self, ast_node):
        return self.global_ctx.parse_type(ast_node)

    def lookup_var(self, varname):
        return self.vars[varname]

    def lookup_internal_function(self, method_name, args_ir, ast_source):
        # TODO is this the right module for me?
        """
        Using a list of args, find the internal method to use, and
        the kwargs which need to be filled in by the compiler
        """

        sig = self.sigs["self"].get(method_name, None)

        def _check(cond, s="Unreachable"):
            if not cond:
                raise CompilerPanic(s)

        # these should have been caught during type checking; sanity check
        _check(sig is not None)
        _check(sig.internal)
        _check(len(sig.base_args) <= len(args_ir) <= len(sig.args))
        # more sanity check, that the types match
        # _check(all(l.typ == r.typ for (l, r) in zip(args_ir, sig.args))

        num_provided_kwargs = len(args_ir) - len(sig.base_args)
        num_kwargs = len(sig.default_args)
        kwargs_needed = num_kwargs - num_provided_kwargs

        kw_vals = list(sig.default_values.values())[:kwargs_needed]

        return sig, kw_vals

    # Pretty print constancy for error messages
    def pp_constancy(self):
        if self.in_assertion:
            return "an assertion"
        elif self.in_range_expr:
            return "a range expression"
        elif self.constancy == Constancy.Constant:
            return "a constant function"
        raise CompilerPanic(f"unknown constancy in pp_constancy: {self.constancy}")
