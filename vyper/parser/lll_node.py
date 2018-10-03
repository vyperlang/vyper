import os
import re

from vyper.types import (
    ceil32,
    BaseType,
    NodeType,
    NullType
)
from vyper.opcodes import (
    comb_opcodes
)
from vyper.utils import valid_lll_macros

# Set default string representation for ints in LLL output.
AS_HEX_DEFAULT = False
# Terminal color types
APPLY_COLOR = os.environ.get('VYPER_COLOR_OUTPUT', '0') == '1'


if APPLY_COLOR:
    OKBLUE = '\033[94m'
    OKMAGENTA = '\033[35m'
    OKLIGHTMAGENTA = '\033[95m'
    OKLIGHTBLUE = '\033[94m'
    ENDC = '\033[0m'
else:
    OKBLUE = ''
    OKMAGENTA = ''
    OKLIGHTMAGENTA = ''
    OKLIGHTBLUE = ''
    ENDC = ''


class NullAttractor():
    def __add__(self, other):
        return NullAttractor()

    def __repr__(self):
        return 'None'

    __radd__ = __add__
    __mul__ = __add__


# Data structure for LLL parse tree
class LLLnode():
    repr_show_gas = False

    def __init__(self, value, args=None, typ=None, location=None, pos=None, annotation='', mutable=True, add_gas_estimate=0, valency=0):
        if args is None:
            args = []

        self.value = value
        self.args = args
        self.typ = typ
        assert isinstance(self.typ, NodeType) or self.typ is None, repr(self.typ)
        self.location = location
        self.pos = pos
        self.annotation = annotation
        self.mutable = mutable
        self.add_gas_estimate = add_gas_estimate
        self.as_hex = AS_HEX_DEFAULT
        self.valency = valency

        # Determine this node's valency (1 if it pushes a value on the stack,
        # 0 otherwise) and checks to make sure the number and valencies of
        # children are correct. Also, find an upper bound on gas consumption
        # Numbers
        if isinstance(self.value, int):
            self.valency = 1
            self.gas = 5
        elif isinstance(self.value, str):
            # Opcodes and pseudo-opcodes (e.g. clamp)
            if self.value.upper() in comb_opcodes:
                _, ins, outs, gas = comb_opcodes[self.value.upper()]
                self.valency = outs
                if len(self.args) != ins:
                    raise Exception("Number of arguments mismatched: %r %r" % (self.value, self.args))
                # We add 2 per stack height at push time and take it back
                # at pop time; this makes `break` easier to handle
                self.gas = gas + 2 * (outs - ins)
                for arg in self.args:
                    # if arg.valency == 0:
                    #     raise Exception("Can't have a zerovalent argument to an opcode or a pseudo-opcode! %r: %r" % (arg.value, arg))
                    self.gas += arg.gas
                # Dynamic gas cost: 8 gas for each byte of logging data
                if self.value.upper()[0:3] == 'LOG' and isinstance(self.args[1].value, int):
                    self.gas += self.args[1].value * 8
                # Dynamic gas cost: non-zero-valued call
                if self.value.upper() == 'CALL' and self.args[2].value != 0:
                    self.gas += 34000
                # Dynamic gas cost: filling sstore (ie. not clearing)
                elif self.value.upper() == 'SSTORE' and self.args[1].value != 0:
                    self.gas += 15000
                # Dynamic gas cost: calldatacopy
                elif self.value.upper() in ('CALLDATACOPY', 'CODECOPY'):
                    size = 34000
                    if isinstance(self.args[2].value, int):
                        size = self.args[2].value
                    elif isinstance(self.args[2], LLLnode) and len(self.args[2].args) > 0:
                        size = self.args[2].args / [-1].value
                    self.gas += ceil32(size) // 32 * 3
                # Gas limits in call
                if self.value.upper() == 'CALL' and isinstance(self.args[0].value, int):
                    self.gas += self.args[0].value
            # If statements
            elif self.value == 'if':
                if len(self.args) == 3:
                    self.gas = self.args[0].gas + max(self.args[1].gas, self.args[2].gas) + 3
                    if self.args[1].valency != self.args[2].valency:
                        raise Exception("Valency mismatch between then and else clause: %r %r" % (self.args[1], self.args[2]))
                if len(self.args) == 2:
                    self.gas = self.args[0].gas + self.args[1].gas + 17
                    if self.args[1].valency:
                        raise Exception("2-clause if statement must have a zerovalent body: %r" % self.args[1])
                if not self.args[0].valency:
                    raise Exception("Can't have a zerovalent argument as a test to an if statement! %r" % self.args[0])
                if len(self.args) not in (2, 3):
                    raise Exception("If can only have 2 or 3 arguments")
                self.valency = self.args[1].valency
            # With statements: with <var> <initial> <statement>
            elif self.value == 'with':
                if len(self.args) != 3:
                    raise Exception("With statement must have 3 arguments")
                if len(self.args[0].args) or not isinstance(self.args[0].value, str):
                    raise Exception("First argument to with statement must be a variable")
                if not self.args[1].valency:
                    raise Exception("Second argument to with statement (initial value) cannot be zerovalent: %r" % self.args[1])
                self.valency = self.args[2].valency
                self.gas = sum([arg.gas for arg in self.args]) + 5
            # Repeat statements: repeat <index_memloc> <startval> <rounds> <body>
            elif self.value == 'repeat':
                if len(self.args[2].args) or not isinstance(self.args[2].value, int) or self.args[2].value <= 0:
                    raise Exception("Number of times repeated must be a constant nonzero positive integer: %r" % self.args[2])
                if not self.args[0].valency:
                    raise Exception("First argument to repeat (memory location) cannot be zerovalent: %r" % self.args[0])
                if not self.args[1].valency:
                    raise Exception("Second argument to repeat (start value) cannot be zerovalent: %r" % self.args[1])
                if self.args[3].valency:
                    raise Exception("Third argument to repeat (clause to be repeated) must be zerovalent: %r" % self.args[3])
                self.valency = 0
                if self.args[1].value == 'mload' or self.args[1].value == 'sload':
                    rounds = self.args[2].value
                else:
                    rounds = abs(self.args[2].value - self.args[1].value)
                self.gas = rounds * (self.args[3].gas + 50) + 30
            # Seq statements: seq <statement> <statement> ...
            elif self.value == 'seq':
                self.valency = self.args[-1].valency if self.args else 0
                self.gas = sum([arg.gas for arg in self.args]) + 30
            # Multi statements: multi <expr> <expr> ...
            elif self.value == 'multi':
                for arg in self.args:
                    if not arg.valency:
                        raise Exception("Multi expects all children to not be zerovalent: %r" % arg)
                self.valency = sum([arg.valency for arg in self.args])
                self.gas = sum([arg.gas for arg in self.args])
            # LLL brackets (don't bother gas counting)
            elif self.value == 'lll':
                self.valency = 1
                self.gas = NullAttractor()
            # Stack variables
            else:
                self.valency = 1
                self.gas = 5
                if self.value == 'seq_unchecked':
                    self.gas = sum([arg.gas for arg in self.args]) + 30
                if self.value == 'if_unchecked':
                    self.gas = self.args[0].gas + self.args[1].gas + 17
        elif self.value is None and isinstance(self.typ, NullType):
            self.valency = 1
            self.gas = 5
        else:
            raise Exception("Invalid value for LLL AST node: %r" % self.value)
        assert isinstance(self.args, list)

        self.gas += self.add_gas_estimate

    def to_list(self):
        return [self.value] + [a.to_list() for a in self.args]

    @property
    def repr_value(self):
        if isinstance(self.value, int) and self.as_hex:
            return hex(self.value)
        if not isinstance(self.value, str):
            return str(self.value)
        return self.value

    @staticmethod
    def _colorise_keywords(val):
        if val.lower() in valid_lll_macros:  # highlight macro
            return OKLIGHTMAGENTA + val + ENDC
        elif val.upper() in comb_opcodes.keys():
            return OKMAGENTA + val + ENDC
        return val

    def repr(self):

        if not len(self.args):

            if self.annotation:
                return '%r ' % self.repr_value + OKLIGHTBLUE + '<%s>' % self.annotation + ENDC
            else:
                return str(self.repr_value)
        # x = repr(self.to_list())
        # if len(x) < 80:
        #     return x
        o = ''
        if self.annotation:
            o += '/* %s */ \n' % self.annotation
        if self.repr_show_gas and self.gas:
            o += OKBLUE + "{" + ENDC + str(self.gas) + OKBLUE + "} " + ENDC  # add gas for info.
        o += '[' + self._colorise_keywords(self.repr_value)
        prev_lineno = self.pos[0] if self.pos else None
        arg_lineno = None
        annotated = False
        has_inner_newlines = False
        for arg in self.args:
            o += ',\n  '
            arg_lineno = arg.pos[0] if arg.pos else None
            if arg_lineno is not None and arg_lineno != prev_lineno and self.value in ('seq', 'if'):
                o += '# Line %d\n  ' % (arg_lineno)
                prev_lineno = arg_lineno
                annotated = True
            arg_repr = arg.repr()
            if '\n' in arg_repr:
                has_inner_newlines = True
            sub = arg_repr.replace('\n', '\n  ').strip(' ')
            o += self._colorise_keywords(sub)
        output = o.rstrip(' ') + ']'
        output_on_one_line = re.sub(r',\n *', ', ', output).replace('\n', '')
        if (len(output_on_one_line) < 80 or len(self.args) == 1) and not annotated and not has_inner_newlines:
            return output_on_one_line
        else:
            return output

    def __repr__(self):
        return self.repr()

    @classmethod
    def from_list(cls, obj, typ=None, location=None, pos=None, annotation=None, mutable=True, add_gas_estimate=0):
        if isinstance(typ, str):
            typ = BaseType(typ)
        if isinstance(obj, LLLnode):
            if obj.pos is None:
                obj.pos = pos
            if obj.location is None:
                obj.location = location
            return obj
        elif not isinstance(obj, list):
            return cls(obj, [], typ, location, pos, annotation, mutable, add_gas_estimate=add_gas_estimate)
        else:
            return cls(obj[0], [cls.from_list(o, pos=pos) for o in obj[1:]], typ, location, pos, annotation, mutable, add_gas_estimate=add_gas_estimate)
