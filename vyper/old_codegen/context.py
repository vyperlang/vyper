import contextlib
import enum

from vyper.ast import VyperNode
from vyper.ast.signatures.function_signature import VariableRecord
from vyper.exceptions import CompilerPanic
from vyper.old_codegen.types import NodeType, get_size_of_type


class Constancy(enum.Enum):
    Mutable = 0
    Constant = 1


# Contains arguments, variables, etc
class Context:
    def __init__(
        self,
        vars,
        global_ctx,
        memory_allocator,
        sigs=None,
        forvars=None,
        return_type=None,
        constancy=Constancy.Mutable,
        is_internal=False,
        is_payable=False,
        method_id="",
        sig=None,
    ):
        # In-memory variables, in the form (name, memory location, type)
        self.vars = vars or {}
        # Global variables, in the form (name, storage location, type)
        self.globals = global_ctx._globals
        # ABI objects, in the form {classname: ABI JSON}
        self.sigs = sigs or {"self": {}}
        # Variables defined in for loops, e.g. for i in range(6): ...
        self.forvars = forvars or {}
        # Return type of the function
        self.return_type = return_type
        # Is the function constant?
        self.constancy = constancy
        # Whether body is currently in an assert statement
        self.in_assertion = False
        # Whether we are currently parsing a range expression
        self.in_range_expr = False
        # Is the function payable?
        self.is_payable = is_payable
        # List of custom structs that have been defined.
        self.structs = global_ctx._structs
        # Callback pointer to jump back to, used in internal functions.
        self.callback_ptr = None
        self.is_internal = is_internal
        # method_id of current function
        self.method_id = method_id
        # store global context
        self.global_ctx = global_ctx
        # full function signature
        self.sig = sig
        # Active scopes
        self._scopes = set()

        # Memory alloctor, keeps track of currently allocated memory.
        # Not intended to be accessed directly
        self.memory_allocator = memory_allocator

        # Intermented values, used for internal IDs
        self._internal_var_iter = 0
        self._scope_id_iter = 0

    def is_constant(self):
        return self.constancy is Constancy.Constant or self.in_assertion or self.in_range_expr

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

    def _new_variable(self, name: str, typ: NodeType, var_size: int, is_internal: bool) -> int:
        if is_internal:
            var_pos = self.memory_allocator.expand_memory(var_size)
        else:
            var_pos = self.memory_allocator.allocate_memory(var_size)
        self.vars[name] = VariableRecord(
            name=name,
            pos=var_pos,
            typ=typ,
            mutable=True,
            blockscopes=self._scopes.copy(),
            is_internal=is_internal,
        )
        return var_pos

    def new_variable(self, name: str, typ: NodeType, pos: VyperNode = None) -> int:
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
            var_size = 32 * get_size_of_type(typ)
        return self._new_variable(name, typ, var_size, False)

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
        var_id = self._internal_var_iter
        self._internal_var_iter += 1
        name = f"#internal_{var_id}"

        if hasattr(typ, "size_in_bytes"):
            # temporary requirement to support both new and old type objects
            var_size = typ.size_in_bytes  # type: ignore
        else:
            var_size = 32 * get_size_of_type(typ)
        return self._new_variable(name, typ, var_size, True)

    def parse_type(self, ast_node, location):
        return self.global_ctx.parse_type(ast_node, location)

    # Pretty print constancy for error messages
    def pp_constancy(self):
        if self.in_assertion:
            return "an assertion"
        elif self.in_range_expr:
            return "a range expression"
        elif self.constancy == Constancy.Constant:
            return "a constant function"
        raise CompilerPanic(f"unknown constancy in pp_constancy: {self.constancy}")
