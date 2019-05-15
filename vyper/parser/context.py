import contextlib
import enum

from vyper.exceptions import (
    VariableDeclarationException,
)
from vyper.signatures.function_signature import (
    VariableRecord,
)
from vyper.types import (
    get_size_of_type,
)
from vyper.utils import (
    check_valid_varname,
)


class Constancy(enum.Enum):
    Mutable = 0
    Constant = 1


# Contains arguments, variables, etc
class Context:
    def __init__(self,
                 vars,
                 global_ctx,
                 memory_allocator,
                 sigs=None,
                 forvars=None,
                 return_type=None,
                 constancy=Constancy.Mutable,
                 is_private=False,
                 is_payable=False,
                 origcode='',
                 method_id=''):
        # In-memory variables, in the form (name, memory location, type)
        self.vars = vars or {}
        # Memory alloctor, keeps track of currently allocated memory.
        self.memory_allocator = memory_allocator
        # Global variables, in the form (name, storage location, type)
        self.globals = global_ctx._globals
        # ABI objects, in the form {classname: ABI JSON}
        self.sigs = sigs or {}
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
        # Number of placeholders generated (used to generate random names)
        self.placeholder_count = 1
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
        # List of custom units that have been defined.
        self.custom_units = global_ctx._custom_units
        # List of custom structs that have been defined.
        self.structs = global_ctx._structs
        # defined constants
        self.constants = global_ctx._constants
        # Callback pointer to jump back to, used in private functions.
        self.callback_ptr = None
        self.is_private = is_private
        # method_id of current function
        self.method_id = method_id
        # store global context
        self.global_ctx = global_ctx

    def is_constant(self):
        return self.constancy is Constancy.Constant or \
                self.in_assertion or \
                self.in_range_expr

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
    def assertion_scope(self):
        prev_value = self.in_assertion
        self.in_assertion = True
        yield
        self.in_assertion = prev_value

    @contextlib.contextmanager
    def range_scope(self):
        prev_value = self.in_range_expr
        self.in_range_expr = True
        yield
        self.in_range_expr = prev_value

    @contextlib.contextmanager
    def make_blockscope(self, blockscope_id):
        self.blockscopes.add(blockscope_id)
        yield
        # Remove all variables that have specific blockscope_id attached.
        self.vars = {
            name: var_record for name, var_record in self.vars.items()
            if blockscope_id not in var_record.blockscopes
        }
        # Remove block scopes
        self.blockscopes.remove(blockscope_id)

    def is_valid_varname(self, name, pos):
        # Global context check first.
        if self.global_ctx.is_valid_varname(name, pos):
            check_valid_varname(
                name,
                custom_units=self.custom_units,
                custom_structs=self.structs,
                constants=self.constants, pos=pos,
            )
            # Local context duplicate context check.
            if any((name in self.vars, name in self.globals, name in self.constants)):
                raise VariableDeclarationException("Duplicate variable name: %s" % name, name)
        return True

    # TODO location info for errors
    # Add a new variable
    def new_variable(self, name, typ, pos=None):
        if self.is_valid_varname(name, pos):
            var_size = 32 * get_size_of_type(typ)
            var_pos, _ = self.memory_allocator.increase_memory(var_size)
            self.vars[name] = VariableRecord(
                name,
                var_pos,
                typ,
                True,
                self.blockscopes.copy(),
            )
            return var_pos

    # Add an anonymous variable (used in some complex function definitions)
    def new_placeholder(self, typ):
        name = '_placeholder_' + str(self.placeholder_count)
        self.placeholder_count += 1
        return self.new_variable(name, typ)

    def get_next_mem(self):
        return self.memory_allocator.get_next_mem()

    def parse_type(self, ast_node, location):
        return self.global_ctx.parse_type(ast_node, location)

    # Pretty print constancy for error messages
    def pp_constancy(self):
        if self.in_assertion:
            return 'an assertion'
        elif self.in_range_expr:
            return 'a range expression'
        elif self.constancy == Constancy.Constant:
            return 'a constant function'
        raise ValueError('Compiler error: unknown constancy in pp_constancy: %r' % self.constancy)
