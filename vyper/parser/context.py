import contextlib
import enum
import itertools

from vyper.ast import VyperNode
from vyper.exceptions import CompilerPanic
from vyper.signatures.function_signature import VariableRecord
from vyper.types import NodeType, get_size_of_type
from vyper.utils import check_valid_varname


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
        origcode="",
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
        # Number of internal variables generated (used to generate random names)
        self.internal_variable_count = itertools.count()
        # Original code (for error pretty-printing purposes)
        self.origcode = origcode
        # In Loop status. Whether body is currently evaluating within a for-loop or not.
        self.in_for_loop = set()
        # Count returns in function
        self.function_return_count = 0
        # Current block scope
        self.blockscopes = set()
        # In assignment. Whether expression is currently evaluating an assignment expression.
        self.in_assignment = False
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

        # Memory alloctor, keeps track of currently allocated memory.
        # Not intended to be accessed directly
        self.memory_allocator = memory_allocator

    def is_constant(self):
        return self.constancy is Constancy.Constant or self.in_assertion or self.in_range_expr

    #
    # Context Managers
    # - Context managers are used to ensure proper wrapping of scopes and context states.

    @contextlib.contextmanager
    def in_for_loop_scope(self, name_of_list):
        self.in_for_loop.add(name_of_list)
        yield
        self.in_for_loop.remove(name_of_list)

    @contextlib.contextmanager
    def assignment_scope(self):
        self.in_assignment = True
        yield
        self.in_assignment = False

    @contextlib.contextmanager
    def range_scope(self):
        prev_value = self.in_range_expr
        self.in_range_expr = True
        yield
        self.in_range_expr = prev_value

    def internal_memory_scope(self, scope_id):
        # syntactic sugar for `make_blockscope` used to release
        # memory after creating temporary internal variables
        return self.make_blockscope(scope_id)

    @contextlib.contextmanager
    def make_blockscope(self, blockscope_id):
        self.blockscopes.add(blockscope_id)
        yield

        # Remove all variables that have specific blockscope_id attached.
        released = [(k, v) for k, v in self.vars.items() if blockscope_id in v.blockscopes]
        for name, var in released:
            self.memory_allocator.deallocate_memory(var.pos, var.size * 32)
            del self.vars[name]

        # Remove block scopes
        self.blockscopes.remove(blockscope_id)

    def _new_variable(self, name: str, typ: NodeType, var_pos: int) -> int:
        self.vars[name] = VariableRecord(
            name=name, pos=var_pos, typ=typ, mutable=True, blockscopes=self.blockscopes.copy(),
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
        self.global_ctx.is_valid_varname(name, pos)
        check_valid_varname(
            name, custom_structs=self.structs, pos=pos,
        )

        var_size = 32 * get_size_of_type(typ)
        var_pos = self.memory_allocator.allocate_memory(var_size)
        return self._new_variable(name, typ, var_pos)

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
        name = f"#internal_{next(self.internal_variable_count)}"

        var_size = 32 * get_size_of_type(typ)
        var_pos = self.memory_allocator.allocate_memory(var_size)
        return self._new_variable(name, typ, var_pos)

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
