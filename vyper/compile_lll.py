from vyper.parser.parser import LLLnode
from .opcodes import opcodes
from vyper.utils import MemoryPositions


def num_to_bytearray(x):
    o = []
    while x > 0:
        o.insert(0, x % 256)
        x //= 256
    return o


PUSH_OFFSET = 0x5f
DUP_OFFSET = 0x7f
SWAP_OFFSET = 0x8f

next_symbol = [0]


def mksymbol():
    next_symbol[0] += 1
    return '_sym_' + str(next_symbol[0])


def is_symbol(i):
    return isinstance(i, str) and i[:5] == '_sym_'


def get_revert(mem_start=None, mem_len=None):
    o = []
    end_symbol = mksymbol()
    o.extend([end_symbol, 'JUMPI'])
    if (mem_start, mem_len) == (None, None):
        o.extend(['PUSH1', 0, 'DUP1', 'REVERT'])
    else:
        o.extend([mem_len, mem_start, 'REVERT'])
    o.extend([end_symbol, 'JUMPDEST'])
    return o


# Compiles LLL to assembly
def compile_to_assembly(code, withargs=None, break_dest=None, height=0):
    if withargs is None:
        withargs = {}

    # Opcodes
    if isinstance(code.value, str) and code.value.upper() in opcodes:
        o = []
        for i, c in enumerate(code.args[::-1]):
            o.extend(compile_to_assembly(c, withargs, break_dest, height + i))
        o.append(code.value.upper())
        return o
    # Numbers
    elif isinstance(code.value, int):
        if code.value <= -2**255:
            raise Exception("Value too low: %d" % code.value)
        elif code.value >= 2**256:
            raise Exception("Value too high: %d" % code.value)
        bytez = num_to_bytearray(code.value % 2**256) or [0]
        return ['PUSH' + str(len(bytez))] + bytez
    # Variables connected to with statements
    elif isinstance(code.value, str) and code.value in withargs:
        if height - withargs[code.value] > 16:
            raise Exception("With statement too deep")
        return ['DUP' + str(height - withargs[code.value])]
    # Setting variables connected to with statements
    elif code.value == "set":
        if len(code.args) != 2 or code.args[0].value not in withargs:
            raise Exception("Set expects two arguments, the first being a stack variable")
        if height - withargs[code.args[0].value] > 16:
            raise Exception("With statement too deep")
        return compile_to_assembly(code.args[1], withargs, break_dest, height) + \
            ['SWAP' + str(height - withargs[code.args[0].value]), 'POP']
    # Pass statements
    elif code.value == 'pass':
        return []
    # Code length
    elif code.value == '~codelen':
        return ['_sym_codeend']
    # Calldataload equivalent for code
    elif code.value == 'codeload':
        return compile_to_assembly(LLLnode.from_list(['seq', ['codecopy', MemoryPositions.FREE_VAR_SPACE, code.args[0], 32], ['mload', MemoryPositions.FREE_VAR_SPACE]]),
                                   withargs, break_dest, height)
    # If statements (2 arguments, ie. if x: y)
    elif code.value == 'if' and len(code.args) == 2:
        o = []
        o.extend(compile_to_assembly(code.args[0], withargs, break_dest, height))
        end_symbol = mksymbol()
        o.extend(['ISZERO', end_symbol, 'JUMPI'])
        o.extend(compile_to_assembly(code.args[1], withargs, break_dest, height))
        o.extend([end_symbol, 'JUMPDEST'])
        return o
    # If statements (3 arguments, ie. if x: y, else: z)
    elif code.value == 'if' and len(code.args) == 3:
        o = []
        o.extend(compile_to_assembly(code.args[0], withargs, break_dest, height))
        mid_symbol = mksymbol()
        end_symbol = mksymbol()
        o.extend(['ISZERO', mid_symbol, 'JUMPI'])
        o.extend(compile_to_assembly(code.args[1], withargs, break_dest, height))
        o.extend([end_symbol, 'JUMP', mid_symbol, 'JUMPDEST'])
        o.extend(compile_to_assembly(code.args[2], withargs, break_dest, height))
        o.extend([end_symbol, 'JUMPDEST'])
        return o
    # Repeat statements (compiled from for loops)
    # Repeat(memloc, start, rounds, body)
    elif code.value == 'repeat':
        o = []
        loops = num_to_bytearray(code.args[2].value)
        start, continue_dest, end = mksymbol(), mksymbol(), mksymbol()
        o.extend(compile_to_assembly(code.args[0], withargs, break_dest, height))
        o.extend(compile_to_assembly(code.args[1], withargs, break_dest, height + 1))
        o.extend(['PUSH' + str(len(loops))] + loops)
        # stack: memloc, startvalue, rounds
        o.extend(['DUP2', 'DUP4', 'MSTORE', 'ADD', start, 'JUMPDEST'])
        # stack: memloc, exit_index
        o.extend(compile_to_assembly(code.args[3], withargs, (end, continue_dest, height + 2), height + 2))
        # stack: memloc, exit_index
        o.extend([continue_dest, 'JUMPDEST', 'DUP2', 'MLOAD', 'PUSH1', 1, 'ADD', 'DUP1', 'DUP4', 'MSTORE'])
        # stack: len(loops), index memory address, new index
        o.extend(['DUP2', 'EQ', 'ISZERO', start, 'JUMPI', end, 'JUMPDEST', 'POP', 'POP'])
        return o
    # Continue to the next iteration of the for loop
    elif code.value == 'continue':
        if not break_dest:
            raise Exception("Invalid break")
        dest, continue_dest, break_height = break_dest
        return [continue_dest, 'JUMP']
    # Break from inside a for loop
    elif code.value == 'break':
        if not break_dest:
            raise Exception("Invalid break")
        dest, continue_dest, break_height = break_dest
        return ['POP'] * (height - break_height) + [dest, 'JUMP']
    # With statements
    elif code.value == 'with':
        o = []
        o.extend(compile_to_assembly(code.args[1], withargs, break_dest, height))
        old = withargs.get(code.args[0].value, None)
        withargs[code.args[0].value] = height
        o.extend(compile_to_assembly(code.args[2], withargs, break_dest, height + 1))
        if code.args[2].valency:
            o.extend(['SWAP1', 'POP'])
        else:
            o.extend(['POP'])
        if old is not None:
            withargs[code.args[0].value] = old
        else:
            del withargs[code.args[0].value]
        return o
    # LLL statement (used to contain code inside code)
    elif code.value == 'lll':
        o = []
        begincode = mksymbol()
        endcode = mksymbol()
        o.extend([endcode, 'JUMP', begincode, 'BLANK'])
        o.append(compile_to_assembly(code.args[0], {}, None, 0))  # Append is intentional
        o.extend([endcode, 'JUMPDEST', begincode, endcode, 'SUB', begincode])
        o.extend(compile_to_assembly(code.args[1], withargs, break_dest, height))
        o.extend(['CODECOPY', begincode, endcode, 'SUB'])
        return o
    # Seq (used to piece together multiple statements)
    elif code.value == 'seq':
        o = []
        for arg in code.args:
            o.extend(compile_to_assembly(arg, withargs, break_dest, height))
            if arg.valency == 1 and arg != code.args[-1]:
                o.append('POP')
        return o
    # Assert (if false, exit)
    elif code.value == 'assert':
        o = compile_to_assembly(code.args[0], withargs, break_dest, height)
        o.extend(get_revert())
        return o
    elif code.value == 'assert_reason':
        o = compile_to_assembly(code.args[0], withargs, break_dest, height)
        mem_start = compile_to_assembly(code.args[1], withargs, break_dest, height)
        mem_len = compile_to_assembly(code.args[2], withargs, break_dest, height)
        o.extend(get_revert(mem_start, mem_len))
        return o
    # Unsigned/signed clamp, check less-than
    elif code.value in ('uclamplt', 'uclample', 'clamplt', 'clample', 'uclampgt', 'uclampge', 'clampgt', 'clampge'):
        if isinstance(code.args[0].value, int) and isinstance(code.args[1].value, int):
            # Checks for clamp errors at compile time as opposed to run time
            if code.value in ('uclamplt', 'clamplt') and 0 <= code.args[0].value < code.args[1].value or \
            code.value in ('uclample', 'clample') and 0 <= code.args[0].value <= code.args[1].value or \
            code.value in ('uclampgt', 'clampgt') and 0 <= code.args[0].value > code.args[1].value or \
            code.value in ('uclampge', 'clampge') and 0 <= code.args[0].value >= code.args[1].value:
                return compile_to_assembly(code.args[0], withargs, break_dest, height)
            else:
                raise Exception("Invalid %r with values %r and %r" % (code.value, code.args[0], code.args[1]))
        o = compile_to_assembly(code.args[0], withargs, break_dest, height)
        o.extend(compile_to_assembly(code.args[1], withargs, break_dest, height + 1))
        o.extend(['DUP2'])
        # Stack: num num bound
        if code.value == 'uclamplt':
            o.extend(['LT'])
        elif code.value == "clamplt":
            o.extend(['SLT'])
        elif code.value == "uclample":
            o.extend(['GT', 'ISZERO'])
        elif code.value == "clample":
            o.extend(['SGT', 'ISZERO'])
        elif code.value == 'uclampgt':
            o.extend(['GT'])
        elif code.value == "clampgt":
            o.extend(['SGT'])
        elif code.value == "uclampge":
            o.extend(['LT', 'ISZERO'])
        elif code.value == "clampge":
            o.extend(['SLT', 'ISZERO'])
        o.extend(get_revert())
        return o
    # Signed clamp, check against upper and lower bounds
    elif code.value in ('clamp', 'uclamp'):
        comp1 = 'SGT' if code.value == 'clamp' else 'GT'
        comp2 = 'SLT' if code.value == 'clamp' else 'LT'
        o = compile_to_assembly(code.args[0], withargs, break_dest, height)
        o.extend(compile_to_assembly(code.args[1], withargs, break_dest, height + 1))
        o.extend(['DUP1'])
        o.extend(compile_to_assembly(code.args[2], withargs, break_dest, height + 3))
        o.extend(['SWAP1', comp1, 'ISZERO'])
        o.extend(get_revert())
        o.extend(['DUP1', 'SWAP2', 'SWAP1', comp2, 'ISZERO'])
        o.extend(get_revert())
        return o
    # Checks that a value is nonzero
    elif code.value == 'clamp_nonzero':
        o = compile_to_assembly(code.args[0], withargs, break_dest, height)
        o.extend(['DUP1'])
        o.extend(get_revert())
        return o
    # SHA3 a single value
    elif code.value == 'sha3_32':
        o = compile_to_assembly(code.args[0], withargs, break_dest, height)
        o.extend([
            'PUSH1', MemoryPositions.FREE_VAR_SPACE,
            'MSTORE',
            'PUSH1', 32,
            'PUSH1', MemoryPositions.FREE_VAR_SPACE,
            'SHA3'
        ])
        return o
    # SHA3 a 64 byte value
    elif code.value == 'sha3_64':
        o = compile_to_assembly(code.args[0], withargs, break_dest, height)
        o.extend(compile_to_assembly(code.args[1], withargs, break_dest, height))
        o.extend([
            'PUSH1', MemoryPositions.FREE_VAR_SPACE2,
            'MSTORE',
            'PUSH1', MemoryPositions.FREE_VAR_SPACE,
            'MSTORE',
            'PUSH1', 64,
            'PUSH1', MemoryPositions.FREE_VAR_SPACE,
            'SHA3'
        ])
        return o
    # <= operator
    elif code.value == 'le':
        return compile_to_assembly(LLLnode.from_list(['iszero', ['gt', code.args[0], code.args[1]]]), withargs, break_dest, height)
    # >= operator
    elif code.value == 'ge':
        return compile_to_assembly(LLLnode.from_list(['iszero', ['lt', code.args[0], code.args[1]]]), withargs, break_dest, height)
    # <= operator
    elif code.value == 'sle':
        return compile_to_assembly(LLLnode.from_list(['iszero', ['sgt', code.args[0], code.args[1]]]), withargs, break_dest, height)
    # >= operator
    elif code.value == 'sge':
        return compile_to_assembly(LLLnode.from_list(['iszero', ['slt', code.args[0], code.args[1]]]), withargs, break_dest, height)
    # != operator
    elif code.value == 'ne':
        return compile_to_assembly(LLLnode.from_list(['iszero', ['eq', code.args[0], code.args[1]]]), withargs, break_dest, height)
    # e.g. 95 -> 96, 96 -> 96, 97 -> 128
    elif code.value == "ceil32":
        return compile_to_assembly(LLLnode.from_list(['with', '_val', code.args[0],
                                                        ['sub', ['add', '_val', 31],
                                                                ['mod', ['sub', '_val', 1], 32]]]), withargs, break_dest, height)
    # # jump to a symbol
    elif code.value == 'goto':
        return [
            '_sym_' + str(code.args[0]),
            'JUMP'
        ]
    elif isinstance(code.value, str) and code.value.startswith('_sym_'):
        return code.value
    # set a symbol as a location.
    elif code.value == 'label':
        return [
            '_sym_' + str(code.args[0]),
            'JUMPDEST'
        ]
    # inject debug opcode.
    elif code.value == 'debugger':
        return ['PUSH1', code.pos[0], 'DEBUG']
    else:
        raise Exception("Weird code element: " + repr(code))


# Assembles assembly into EVM
def assembly_to_evm(assembly):
    posmap = {}
    sub_assemblies = []
    codes = []
    pos = 0
    for i, item in enumerate(assembly):
        if is_symbol(item):
            if assembly[i + 1] == 'JUMPDEST' or assembly[i + 1] == 'BLANK':
                posmap[item] = pos  # Don't increment position as the symbol itself doesn't go into code
            else:
                pos += 3  # PUSH2 highbits lowbits
        elif item == 'BLANK':
            pos += 0
        elif isinstance(item, list):
            c = assembly_to_evm(item)
            sub_assemblies.append(item)
            codes.append(c)
            pos += len(c)
        else:
            pos += 1
    posmap['_sym_codeend'] = pos
    o = b''
    for i, item in enumerate(assembly):
        if is_symbol(item):
            if assembly[i + 1] != 'JUMPDEST' and assembly[i + 1] != 'BLANK':
                o += bytes([PUSH_OFFSET + 2, posmap[item] // 256, posmap[item] % 256])
        elif isinstance(item, int):
            o += bytes([item])
        elif isinstance(item, str) and item.upper() in opcodes:
            o += bytes([opcodes[item.upper()][0]])
        elif item[:4] == 'PUSH':
            o += bytes([PUSH_OFFSET + int(item[4:])])
        elif item[:3] == 'DUP':
            o += bytes([DUP_OFFSET + int(item[3:])])
        elif item[:4] == 'SWAP':
            o += bytes([SWAP_OFFSET + int(item[4:])])
        elif item == 'BLANK':
            pass
        elif isinstance(item, list):
            for i in range(len(sub_assemblies)):
                if sub_assemblies[i] == item:
                    o += codes[i]
                    break
        else:
            # Should never reach because, assembly is create in compile_to_assembly.
            raise Exception("Weird symbol in assembly: " + str(item))  # pragma: no cover

    assert len(o) == pos
    return o
