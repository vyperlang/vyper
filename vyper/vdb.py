import cmd
import evm

# from eth_hash.auto import keccak
from eth_utils import to_hex
from evm import constants
from evm.vm.opcode import as_opcode
from evm.utils.numeric import (
    int_to_big_endian,
    big_endian_to_int,
    # ceil32
)
from vyper.opcodes import opcodes as vyper_opcodes


commands = [
    'continue',
    'locals',
    'globals'
]
base_types = ('int128', 'uint256', 'address', 'bytes32')


def history():
    import readline
    for i in range(1, readline.get_current_history_length() + 1):
        print("%3d %s" % (i, readline.get_history_item(i)))


logo = """
__     __
\ \ _ / /
 \ v v /  Vyper Debugger
  \   /  0.0.0b1
   \ /  "help" to get a list of commands
    v
"""


def print_var(value, var_typ):

    if isinstance(value, int):
        v = int_to_big_endian(value)
    else:
        v = value

    if isinstance(v, bytes):
        if var_typ == 'uint256':
            print(big_endian_to_int(v))
        elif var_typ == 'int128':
            print('TODO!')
        elif var_typ == 'address':
            print(to_hex(v[12:]))
    else:
        print(v)


class VyperDebugCmd(cmd.Cmd):
    def __init__(self, computation, line_no=None, source_code=None, source_map=None):
        if source_map is None:
            source_map = {}
        self.computation = computation
        self.prompt = '\033[92mvdb\033[0m> '
        self.intro = logo
        self.source_code = source_code
        self.line_no = line_no
        self.globals = source_map.get("globals")
        self.locals = source_map.get("locals")
        super().__init__()

    def _print_code_position(self):

        if not all((self.source_code, self.line_no)):
            print('No source loaded')
            return

        lines = self.source_code.splitlines()
        begin = self.line_no - 1 if self.line_no > 1 else 0
        end = self.line_no + 1 if self.line_no < len(lines) else self.line_no
        for idx, line in enumerate(lines[begin - 1:end]):
            line_number = begin + idx
            if line_number == self.line_no:
                print("--> \033[92m{}\033[0m\t{}".format(line_number, line))
            else:
                print("    \033[92m{}\033[0m\t{}".format(line_number, line))

    def preloop(self):
        super().preloop()
        self._print_code_position()

    def postloop(self):
        print('Exiting vdb')
        super().postloop()

    def do_state(self, *args):
        """ Show current EVM state information. """
        print('Block Number => {}'.format(self.computation.state.block_number))
        print('Program Counter => {}'.format(self.computation.code.pc))
        print('Memory Size => {}'.format(len(self.computation._memory)))
        print('Gas Remaining => {}'.format(self.computation.get_gas_remaining()))

    def do_globals(self, *args):
        if not self.globals:
            print('No globals found.')
        print('Name\t\tType')
        for name, info in self.globals.items():
            print('self.{}\t\t{}'.format(name, info['type']))

    def _get_fn_name_locals(self):
        for fn_name, info in self.locals.items():
            if info['from_lineno'] < self.line_no < info['to_lineno']:
                return fn_name, info['variables']
        return '', {}

    def do_locals(self, *args):
        if not self.locals:
            print('No locals found.')
        fn_name, variables = self._get_fn_name_locals()
        print('Function: {}'.format(fn_name))
        print('Name\t\tType')
        for name, info in variables.items():
            print('{}\t\t{}'.format(name, info['type']))

    def default(self, line):
        fn_name, local_variables = self._get_fn_name_locals()
        if not self.globals:
            print('No globals found.')
        if line.startswith('self.') and len(line) > 4:
            # print global value.
            name = line.split('.')[1]
            if name not in self.globals:
                print('Global named "{}" not found.'.format(name))
            else:
                global_type = self.globals[name]['type']
                slot = None

                if global_type in base_types:
                    slot = self.globals[name]['position']
                elif global_type == 'mapping':
                    # location_hash= keccak(int_to_big_endian(self.globals[name]['position']).rjust(32, b'\0'))
                    # slot = big_endian_to_int(location_hash)
                    pass
                else:
                    print('Can not read global of type "{}".'.format(global_type))

                if slot is not None:
                    value = self.computation.state.account_db.get_storage(
                        address=self.computation.msg.storage_address,
                        slot=slot,
                    )
                    print_var(value, global_type)
        elif line in local_variables:
            var_info = local_variables[line]
            local_type = var_info['type']
            if local_type in base_types:
                start_position = var_info['position']
                value = self.computation.memory_read(start_position, 32)
                print_var(value, local_type)
            else:
                print('Can not read local of type ')
        else:
            self.stdout.write('*** Unknown syntax: %s\n' % line)

    def do_stack(self, *args):
        """ Show contents of the stack """
        for idx, value in enumerate(self.computation._stack.values):
            print("{}\t{}".format(idx, to_hex(value)))
        else:
            print("Stack is empty")

    def do_pdb(self, *args):
        # Break out to pdb for vdb debugging.
        import pdb; pdb.set_trace()  # noqa

    def do_history(self, *args):
        history()

    def emptyline(self):
        pass

    def do_quit(self, *args):
        return True

    def do_exit(self, *args):
        """ Exit vdb """
        return True

    def do_continue(self, *args):
        """ Exit vdb """
        return True

    def do_EOF(self, line):
        """ Exit vdb """
        return True


original_opcodes = evm.vm.forks.byzantium.computation.ByzantiumComputation.opcodes


def set_evm_opcode_debugger(source_code=None, source_map=None):

    def debug_opcode(computation):
        line_no = computation.stack_pop(num_items=1, type_hint=constants.UINT256)
        VyperDebugCmd(computation, line_no=line_no, source_code=source_code, source_map=source_map).cmdloop()

    opcodes = original_opcodes.copy()
    opcodes[vyper_opcodes['DEBUG'][0]] = as_opcode(
        logic_fn=debug_opcode,
        mnemonic="DEBUG",
        gas_cost=0
    )

    setattr(evm.vm.forks.byzantium.computation.ByzantiumComputation, 'opcodes', opcodes)


def set_evm_opcode_pass():

    def debug_opcode(computation):
        computation.stack_pop(num_items=1, type_hint=constants.UINT256)

    opcodes = original_opcodes.copy()
    opcodes[vyper_opcodes['DEBUG'][0]] = as_opcode(
        logic_fn=debug_opcode,
        mnemonic="DEBUG",
        gas_cost=0
    )
    setattr(evm.vm.forks.byzantium.computation.ByzantiumComputation, 'opcodes', opcodes)
