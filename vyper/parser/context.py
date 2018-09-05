from vyper.utils import (
    MemoryPositions,
    is_varname_valid,
)
from vyper.types import (
    get_size_of_type
)

from vyper.exceptions import (
    VariableDeclarationException,
)

from vyper.signatures.function_signature import (
    VariableRecord,
)


# Contains arguments, variables, etc
class Context():
    def __init__(self, vars=None, globals=None, custom_units=None, sigs=None, forvars=None, return_type=None, is_constant=False, is_payable=False, origcode=''):
        # In-memory variables, in the form (name, memory location, type)
        self.vars = vars or {}
        self.next_mem = MemoryPositions.RESERVED_MEMORY
        # Global variables, in the form (name, storage location, type)
        self.globals = globals or {}
        # ABI objects, in the form {classname: ABI JSON}
        self.sigs = sigs or {}
        # Variables defined in for loops, e.g. for i in range(6): ...
        self.forvars = forvars or {}
        # Return type of the function
        self.return_type = return_type
        # Is the function constant?
        self.is_constant = is_constant
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
        # In assignment. Whether expressiong is currently evaluating an assignment expression.
        self.in_assignment = False
        # List of custom units that have been defined.
        self.custom_units = custom_units

    def set_in_assignment(self, state: bool):
        self.in_assignment = state

    def set_in_for_loop(self, name_of_list):
        self.in_for_loop.add(name_of_list)

    def remove_in_for_loop(self, name_of_list):
        self.in_for_loop.remove(name_of_list)

    def start_blockscope(self, blockscope_id):
        self.blockscopes.add(blockscope_id)

    def end_blockscope(self, blockscope_id):
        # Remove all variables that have specific blockscope_id attached.
        self.vars = {
            name: var_record for name, var_record in self.vars.items()
            if blockscope_id not in var_record.blockscopes
        }
        # Remove block scopes
        self.blockscopes.remove(blockscope_id)

    def increment_return_counter(self):
        self.function_return_count += 1

    # Add a new variable
    def new_variable(self, name, typ):
        if not is_varname_valid(name, custom_units=self.custom_units):
            raise VariableDeclarationException("Variable name invalid or reserved: " + name)
        if name in self.vars or name in self.globals:
            raise VariableDeclarationException("Duplicate variable name: %s" % name)
        self.vars[name] = VariableRecord(name, self.next_mem, typ, True, self.blockscopes.copy())
        pos = self.next_mem
        self.next_mem += 32 * get_size_of_type(typ)
        return pos

    # Add an anonymous variable (used in some complex function definitions)
    def new_placeholder(self, typ):
        name = '_placeholder_' + str(self.placeholder_count)
        self.placeholder_count += 1
        return self.new_variable(name, typ)

    # Get the next unused memory location
    def get_next_mem(self):
        return self.next_mem
