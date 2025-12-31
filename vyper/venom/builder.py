from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Sequence, Union

from vyper.venom.basicblock import IRBasicBlock, IRLabel, IRLiteral, IROperand, IRVariable
from vyper.venom.function import IRFunction

if TYPE_CHECKING:
    from vyper.venom.context import IRContext

# IROperand is the base class for IRVariable, IRLiteral, IRLabel
Operand = Union[IROperand, int]


class VenomBuilder:
    """Clean API for building Venom IR.

    Wraps IRContext/IRFunction/IRBasicBlock to provide explicit,
    type-safe instruction emission.
    """

    ctx: IRContext
    fn: IRFunction
    _current_bb: IRBasicBlock

    def __init__(self, ctx: IRContext, fn: IRFunction):
        self.ctx = ctx
        self.fn = fn
        self._current_bb = fn.entry

    # === Block Management ===
    @property
    def current_block(self) -> IRBasicBlock:
        """Get current emission target block."""
        return self._current_bb

    def create_block(self, suffix: str = "") -> IRBasicBlock:
        """Create new block with auto-generated label. Does NOT switch to it or append it."""
        label = self.ctx.get_next_label(suffix)
        return IRBasicBlock(label, self.fn)

    def append_block(self, bb: IRBasicBlock) -> None:
        """Append block to function (must be done before emitting to it)."""
        self.fn.append_basic_block(bb)

    def set_block(self, bb: IRBasicBlock) -> None:
        """Switch emission target to given block."""
        self._current_bb = bb

    def is_terminated(self) -> bool:
        """Check if current block has a terminator instruction."""
        return self._current_bb.is_terminated

    def create_and_switch_block(self, suffix: str = "") -> IRBasicBlock:
        """Create, append, and switch to new block. Convenience method."""
        bb = self.create_block(suffix)
        self.append_block(bb)
        self.set_block(bb)
        return bb

    def new_variable(self) -> IRVariable:
        """Create fresh SSA variable without emitting any instruction.

        Useful for ternary expressions and multi-return patterns where
        you need a target variable before the value is computed.
        """
        return self.fn.get_next_variable()

    # === Arithmetic ===
    def add(self, a: Operand, b: Operand) -> IRVariable:
        return self._emit1("add", a, b)

    def sub(self, a: Operand, b: Operand) -> IRVariable:
        return self._emit1("sub", b, a)  # reversed for EVM stack order

    def mul(self, a: Operand, b: Operand) -> IRVariable:
        return self._emit1("mul", a, b)

    def div(self, a: Operand, b: Operand) -> IRVariable:
        return self._emit1("div", b, a)  # reversed for EVM stack order

    def sdiv(self, a: Operand, b: Operand) -> IRVariable:
        return self._emit1("sdiv", b, a)  # reversed for EVM stack order

    def mod(self, a: Operand, b: Operand) -> IRVariable:
        return self._emit1("mod", b, a)  # reversed for EVM stack order

    def smod(self, a: Operand, b: Operand) -> IRVariable:
        return self._emit1("smod", b, a)  # reversed for EVM stack order

    def exp(self, base: Operand, exponent: Operand) -> IRVariable:
        return self._emit1("exp", exponent, base)  # reversed for EVM stack order

    def addmod(self, a: Operand, b: Operand, n: Operand) -> IRVariable:
        return self._emit1("addmod", a, b, n)

    def mulmod(self, a: Operand, b: Operand, n: Operand) -> IRVariable:
        return self._emit1("mulmod", a, b, n)

    def signextend(self, byte_width: Operand, val: Operand) -> IRVariable:
        return self._emit1("signextend", val, byte_width)  # reversed for EVM stack order

    # === Bitwise ===
    def and_(self, a: Operand, b: Operand) -> IRVariable:
        return self._emit1("and", a, b)

    def or_(self, a: Operand, b: Operand) -> IRVariable:
        return self._emit1("or", a, b)

    def xor(self, a: Operand, b: Operand) -> IRVariable:
        return self._emit1("xor", a, b)

    def not_(self, a: Operand) -> IRVariable:
        return self._emit1("not", a)

    def shl(self, bits: Operand, val: Operand) -> IRVariable:
        return self._emit1("shl", val, bits)  # reversed for EVM stack order

    def shr(self, bits: Operand, val: Operand) -> IRVariable:
        return self._emit1("shr", val, bits)  # reversed for EVM stack order

    def sar(self, bits: Operand, val: Operand) -> IRVariable:
        return self._emit1("sar", val, bits)  # reversed for EVM stack order

    # === Comparison ===
    def eq(self, a: Operand, b: Operand) -> IRVariable:
        return self._emit1("eq", a, b)

    def lt(self, a: Operand, b: Operand) -> IRVariable:
        return self._emit1("lt", b, a)  # reversed for EVM stack order

    def gt(self, a: Operand, b: Operand) -> IRVariable:
        return self._emit1("gt", b, a)  # reversed for EVM stack order

    def slt(self, a: Operand, b: Operand) -> IRVariable:
        return self._emit1("slt", b, a)  # reversed for EVM stack order

    def sgt(self, a: Operand, b: Operand) -> IRVariable:
        return self._emit1("sgt", b, a)  # reversed for EVM stack order

    def iszero(self, a: Operand) -> IRVariable:
        return self._emit1("iszero", a)

    # === Memory ===
    def mload(self, ptr: Operand) -> IRVariable:
        return self._emit1("mload", ptr)

    def mstore(self, val: Operand, ptr: Operand) -> None:
        """Store val at memory ptr. Note: val, ptr order matches EVM."""
        self._emit("mstore", val, ptr)

    def mcopy(self, size: Operand, src: Operand, dst: Operand) -> None:
        """Copy size bytes from src to dst in memory."""
        self._emit("mcopy", size, src, dst)

    def msize(self) -> IRVariable:
        return self._emit1("msize")

    def alloca(self, size: int, alloca_id: int) -> IRVariable:
        """Allocate abstract memory. Returns pointer."""
        return self._emit1("alloca", size, alloca_id)

    def palloca(self, size: int, alloca_id: int) -> IRVariable:
        """Allocate parameter memory in callee frame. Returns pointer."""
        return self._emit1("palloca", size, alloca_id)

    def calloca(self, size: int, alloca_id: int, callsite: IRLabel) -> IRVariable:
        """Allocate argument staging memory at call site. Returns pointer.

        Used for memory-passed arguments when calling internal functions.
        The callsite label links this allocation to a specific invoke.
        """
        return self._emit1("calloca", size, alloca_id, callsite)

    def gep(self, ptr: Operand, offset: Operand) -> IRVariable:
        """Get element pointer into memory region.

        Used for accessing elements within abstract memory (e.g., immutables).
        """
        return self._emit1("gep", ptr, offset)

    # === Storage ===
    def sload(self, slot: Operand) -> IRVariable:
        return self._emit1("sload", slot)

    def sstore(self, val: Operand, slot: Operand) -> None:
        self._emit("sstore", val, slot)

    def tload(self, slot: Operand) -> IRVariable:
        return self._emit1("tload", slot)

    def tstore(self, val: Operand, slot: Operand) -> None:
        self._emit("tstore", val, slot)

    # === Immutables / Data Section ===
    def dload(self, offset: Operand) -> IRVariable:
        """Load 32 bytes from data section."""
        return self._emit1("dload", offset)

    def dloadbytes(self, size: Operand, src: Operand, dst: Operand) -> None:
        """Copy size bytes from data section (src) to memory (dst)."""
        self._emit("dloadbytes", size, src, dst)

    def iload(self, offset: Operand) -> IRVariable:
        """Load from immutable memory region."""
        return self._emit1("iload", offset)

    def istore(self, val: Operand, offset: Operand) -> None:
        """Store to immutable memory region (deploy-time only)."""
        self._emit("istore", val, offset)

    def offset(self, label: IRLabel, operand: Operand) -> IRVariable:
        """Compute static offset from label. Used for code position calculations."""
        return self._emit1("offset", label, operand)

    # === Control Flow ===
    def jmp(self, target: IRLabel) -> None:
        """Unconditional jump. Terminates block."""
        self._emit("jmp", target)

    def jnz(self, cond: Operand, then_label: IRLabel, else_label: IRLabel) -> None:
        """Conditional branch. Terminates block."""
        self._emit("jnz", cond, then_label, else_label)

    def djmp(self, target: Operand, *labels: IRLabel) -> None:
        """Dynamic jump to one of labels based on target. Terminates block."""
        self._emit("djmp", target, *labels)

    def ret(self, *values: Operand) -> None:
        """Return from internal function. Terminates block."""
        self._emit("ret", *values)

    def return_(self, size: Operand, offset: Operand) -> None:
        """Return from external call (EVM RETURN). Terminates block."""
        self._emit("return", size, offset)

    def stop(self) -> None:
        """Halt execution. Terminates block."""
        self._emit("stop")

    def revert(self, size: Operand, offset: Operand) -> None:
        """Revert execution. Terminates block."""
        self._emit("revert", size, offset)

    def invalid(self) -> None:
        """Invalid opcode. Terminates block."""
        self._emit("invalid")

    # === Assertions ===
    def assert_(self, cond: Operand) -> None:
        """Assert condition (reverts if false)."""
        self._emit("assert", cond)

    def assert_unreachable(self, cond: Operand) -> None:
        """Assert unreachable code path."""
        self._emit("assert_unreachable", cond)

    # === Internal Calls ===
    def invoke(
        self, target: IRLabel, args: Sequence[Operand], returns: int = 0
    ) -> list[IRVariable]:
        """Call internal function. Returns list of output variables."""
        all_args = [target] + list(args)
        return self._current_bb.append_invoke_instruction(all_args, returns=returns)

    def param(self) -> IRVariable:
        """Declare function parameter (must be at block start)."""
        return self._emit1("param")

    # === External Calls ===
    def call(
        self,
        gas: Operand,
        addr: Operand,
        val: Operand,
        argsptr: Operand,
        argsz: Operand,
        retptr: Operand,
        retsz: Operand,
    ) -> IRVariable:
        return self._emit1("call", gas, addr, val, argsptr, argsz, retptr, retsz)

    def staticcall(
        self,
        gas: Operand,
        addr: Operand,
        argsptr: Operand,
        argsz: Operand,
        retptr: Operand,
        retsz: Operand,
    ) -> IRVariable:
        return self._emit1("staticcall", gas, addr, argsptr, argsz, retptr, retsz)

    def delegatecall(
        self,
        gas: Operand,
        addr: Operand,
        argsptr: Operand,
        argsz: Operand,
        retptr: Operand,
        retsz: Operand,
    ) -> IRVariable:
        return self._emit1("delegatecall", gas, addr, argsptr, argsz, retptr, retsz)

    def create(self, val: Operand, offset: Operand, size: Operand) -> IRVariable:
        return self._emit1("create", val, offset, size)

    def create2(self, val: Operand, offset: Operand, size: Operand, salt: Operand) -> IRVariable:
        return self._emit1("create2", val, offset, size, salt)

    # === Crypto ===
    def sha3(self, ptr: Operand, size: Operand) -> IRVariable:
        return self._emit1("sha3", ptr, size)

    def sha3_64(self, a: Operand, b: Operand) -> IRVariable:
        """Hash two 32-byte values (optimized keccak)."""
        return self._emit1("sha3_64", a, b)

    # === Data Copy ===
    def calldatacopy(self, size: Operand, src: Operand, dst: Operand) -> None:
        self._emit("calldatacopy", size, src, dst)

    def codecopy(self, size: Operand, src: Operand, dst: Operand) -> None:
        self._emit("codecopy", size, src, dst)

    def extcodecopy(self, addr: Operand, size: Operand, src: Operand, dst: Operand) -> None:
        self._emit("extcodecopy", addr, size, src, dst)

    def returndatacopy(self, size: Operand, src: Operand, dst: Operand) -> None:
        self._emit("returndatacopy", size, src, dst)

    # === Environment ===
    def caller(self) -> IRVariable:
        return self._emit1("caller")

    def callvalue(self) -> IRVariable:
        return self._emit1("callvalue")

    def calldatasize(self) -> IRVariable:
        return self._emit1("calldatasize")

    def calldataload(self, offset: Operand) -> IRVariable:
        return self._emit1("calldataload", offset)

    def address(self) -> IRVariable:
        return self._emit1("address")

    def balance(self, addr: Operand) -> IRVariable:
        return self._emit1("balance", addr)

    def selfbalance(self) -> IRVariable:
        return self._emit1("selfbalance")

    def origin(self) -> IRVariable:
        return self._emit1("origin")

    def gas(self) -> IRVariable:
        return self._emit1("gas")

    def gasprice(self) -> IRVariable:
        return self._emit1("gasprice")

    def codesize(self) -> IRVariable:
        return self._emit1("codesize")

    def extcodesize(self, addr: Operand) -> IRVariable:
        return self._emit1("extcodesize", addr)

    def extcodehash(self, addr: Operand) -> IRVariable:
        return self._emit1("extcodehash", addr)

    def returndatasize(self) -> IRVariable:
        return self._emit1("returndatasize")

    # === Block Info ===
    def blockhash(self, block_num: Operand) -> IRVariable:
        return self._emit1("blockhash", block_num)

    def coinbase(self) -> IRVariable:
        return self._emit1("coinbase")

    def timestamp(self) -> IRVariable:
        return self._emit1("timestamp")

    def number(self) -> IRVariable:
        return self._emit1("number")

    def prevrandao(self) -> IRVariable:
        return self._emit1("prevrandao")

    def difficulty(self) -> IRVariable:
        """Deprecated: use prevrandao."""
        return self._emit1("difficulty")

    def gaslimit(self) -> IRVariable:
        return self._emit1("gaslimit")

    def chainid(self) -> IRVariable:
        return self._emit1("chainid")

    def basefee(self) -> IRVariable:
        return self._emit1("basefee")

    def blobhash(self, index: Operand) -> IRVariable:
        return self._emit1("blobhash", index)

    def blobbasefee(self) -> IRVariable:
        return self._emit1("blobbasefee")

    # === Logging ===
    def log(self, topic_count: int, offset: Operand, size: Operand, *topics: Operand) -> None:
        """Emit log with N topics.

        Args:
            topic_count: Number of topics (0-4)
            offset: Memory offset of data
            size: Size of data to log
            topics: topic0, topic1, ... (in logical order)

        Matches EVM LOG opcode order: LOG(offset, size, topic0, ...).
        Internally reorders to match venom IR format.
        """
        # Venom IR format: log topic_count, topic_n-1, ..., topic0, size, offset
        self._emit("log", topic_count, *reversed(topics), size, offset)

    # === Other ===
    def selfdestruct(self, addr: Operand) -> None:
        self._emit("selfdestruct", addr)

    def nop(self) -> None:
        """No operation. Placeholder instruction."""
        self._emit("nop")

    # === Helpers ===
    def assign(self, val: Operand) -> IRVariable:
        """Copy value to new variable (SSA phi-like)."""
        return self._emit1("assign", val)

    def assign_to(self, val: Operand, target: IRVariable) -> None:
        """Assign value to existing variable (for loop counters etc)."""
        self._current_bb.append_instruction("assign", val, ret=target)

    def literal(self, val: int) -> IRLiteral:
        """Create literal operand (convenience, can also just pass int)."""
        return IRLiteral(val)

    def label(self, name: str, is_symbol: bool = False) -> IRLabel:
        """Create a label."""
        return IRLabel(name, is_symbol)

    def select(self, cond: Operand, true_val: Operand, false_val: Operand) -> IRVariable:
        """
        Conditional selection: returns true_val if cond is nonzero, else false_val.

        Equivalent to: cond ? true_val : false_val

        Uses: xor(b, mul(cond, xor(a, b)))
        Matches ir_node_to_venom.py implementation.
        Requires cond to be exactly 0 or 1 (which Vyper comparisons guarantee).
        """
        diff = self.xor(true_val, false_val)
        scaled = self.mul(cond, diff)
        return self.xor(false_val, scaled)

    # === Source Tracking ===
    @contextmanager
    def source_context(self, ast_node):
        """Track source location for error messages.

        Usage:
            with b.source_context(node):
                b.add(x, y)  # Instructions get source info
        """
        self.fn.push_source(ast_node)
        try:
            yield
        finally:
            self.fn.pop_source()

    # === Internal Implementation ===
    def _emit(self, opcode: str, *args: Operand) -> None:
        """Emit instruction with no output."""
        self._current_bb.append_instruction(opcode, *args)

    def _emit1(self, opcode: str, *args: Operand) -> IRVariable:
        """Emit instruction that produces output, return the output variable."""
        return self._current_bb.append_instruction1(opcode, *args)
