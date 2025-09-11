from vyper.venom.analysis import IRAnalysesCache, VarDefinition
from vyper.venom.basicblock import IRBasicBlock, IRVariable, IROperand, IRAbstractMemLoc
from vyper.venom.context import IRContext
from vyper.venom.function import IRFunction


class VenomError(Exception):
    message: str


class BasicBlockNotTerminated(VenomError):
    message: str = "basic block does not terminate"

    def __init__(self, basicblock):
        self.basicblock = basicblock

    def __str__(self):
        return f"basic block is not terminated:\n{self.basicblock}"


class VarNotDefined(VenomError):
    message: str = "variable is used before definition"

    def __init__(self, var, inst):
        self.var = var
        self.inst = inst

    def __str__(self):
        bb = self.inst.parent
        return f"var {self.var} not defined:\n  {self.inst}\n\n{bb}"


def _handle_var_definition(
    fn: IRFunction, bb: IRBasicBlock, var_def: VarDefinition
) -> list[VenomError]:
    errors: list[VenomError] = []
    for inst in bb.instructions:
        if inst.opcode == "phi":
            for label, op in inst.phi_operands:
                defined = var_def.defined_vars_bb[fn.get_basic_block(label.name)]
                if op not in defined:
                    errors.append(VarNotDefined(var=op, inst=inst))
            continue
        defined = var_def.defined_vars[inst]
        for op in inst.operands:
            if isinstance(op, IRVariable):
                if op not in defined:
                    errors.append(VarNotDefined(var=op, inst=inst))
    return errors


def find_semantic_errors_fn(fn: IRFunction) -> list[VenomError]:
    errors: list[VenomError] = []

    # check that all the bbs are terminated
    for bb in fn.get_basic_blocks():
        if not bb.is_terminated:
            errors.append(BasicBlockNotTerminated(basicblock=bb))

    if len(errors) > 0:
        return errors

    ac = IRAnalysesCache(fn)
    var_def: VarDefinition = ac.request_analysis(VarDefinition)
    for bb in fn.get_basic_blocks():
        e = _handle_var_definition(fn, bb, var_def)
        errors.extend(e)
    return errors


def find_semantic_errors(context: IRContext) -> list[VenomError]:
    errors: list[VenomError] = []

    for fn in context.functions.values():
        errors.extend(find_semantic_errors_fn(fn))

    return errors


def check_venom_ctx(context: IRContext):
    errors = find_semantic_errors(context)

    if errors:
        raise ExceptionGroup("venom semantic errors", errors)

def no_concrete_locations_fn(function: IRFunction):
    for bb in function.get_basic_blocks():
        for inst in bb.instructions:
            write_op = _get_memory_write_op(inst)
            read_op = _get_memory_read_op(inst)
            if write_op is not None:
                assert isinstance(write_op, (IRVariable, IRAbstractMemLoc)), inst.parent
            if read_op is not None:
                assert isinstance(read_op, (IRVariable, IRAbstractMemLoc)), inst.parent

def _get_memory_write_op(inst) -> IROperand | None:
    opcode = inst.opcode
    if opcode == "mstore":
        dst = inst.operands[1]
        return dst 
    elif opcode in ("mcopy", "calldatacopy", "dloadbytes", "codecopy", "returndatacopy"):
        _, _, dst = inst.operands
        return dst
    elif opcode == "call":
        _, dst, _, _, _, _, _ = inst.operands
        return dst
    elif opcode in ("delegatecall", "staticcall"):
        _, dst, _, _, _, _ = inst.operands
        return dst
    elif opcode == "extcodecopy":
        _, _, dst, _ = inst.operands
        return dst 

    return None


def _get_memory_read_op(inst) -> IROperand | None:
    opcode = inst.opcode
    if opcode == "mload":
        return inst.operands[0]
    elif opcode == "mcopy":
        _, src, _ = inst.operands
        return src
    elif opcode == "call":
        _, _, _, dst, _, _, _ = inst.operands
        return dst
    elif opcode in ("delegatecall", "staticcall"):
        _, _, _, dst, _, _ = inst.operands
        return dst
    elif opcode == "return":
        _, src = inst.operands
        return src
    elif opcode == "create":
        _, src, _value = inst.operands
        return src
    elif opcode == "create2":
        _salt, size, src, _value = inst.operands
        return src
    elif opcode == "sha3":
        _, offset = inst.operands
        return offset
    elif opcode == "log":
        _, src = inst.operands[-2:]
        return src
    elif opcode == "revert":
        size, src = inst.operands
        if size.value == 0:
            return None
        return src

    return None

