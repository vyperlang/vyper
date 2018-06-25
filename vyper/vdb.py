import cmd
import evm

from evm import constants
from evm.vm.opcode import as_opcode
from vyper.opcodes import opcodes as vyper_opcodes


commands = [
    'continue',
    'locals',
    'globals'
]


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
        super().__init__()

    def _print_code_position(self):

        if not all((self.source_code, self.line_no)):
            print('No source loaded')
            return

        lines = self.source_code.splitlines()
        begin = self.line_no - 1 if self.line_no > 1 else 0
        end = self.line_no + 1 if self.line_no < len(lines) else self.line_no
        for idx, line in enumerate(lines[begin:end]):
            line_number = begin + idx + 1
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

    def do_continue(self, *args):
        return True

    def do_globals(self, *args):
        if not self.globals:
            print('No globals found.')

        print('Name\tType')
        for name, info in self.globals.items():
            print('self.{}\t{}'.format(name, info['type']))

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

    def do(self, *args):
        print('%%%%')
        pass

    def do_EOF(self, line):
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
