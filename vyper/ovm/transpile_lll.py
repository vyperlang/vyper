# ovm "spec" -- list of opcodes and translation utils

# This module implements a limited subroutine system.
# It rewrites opcodes like <x> <y> SSTORE
# into PUSH _return_label <x> <y> PUSH _ovm_sstore JUMP _return_label JUMPDEST
# (relying on the subroutine, _ovm_sstore, to jump back)
#
# Note the main difference between EVM and OVM instructions is that args to EVM
# instructions are basically provided on the stack, but the OVM execution
# manager is implemented as a solidity contract, it takes args in a memory
# buffer like any other CALL. So let's call EVM instructions "opcodes" and OVM
# instructions "OVM methods". _ovm_<opcode> basically looks like
# 1. Convert the stack args to ABI-encoded memory
# 2. Call into the execution manager using the designated OVM CALL string
# 3. abi_decode the output buffer (and if the EVM opcode expects items to be
#    output on the stack, mload them from the buffer)
# 4. Jump out.
#
# The ABI encoding process is a little complex for opcodes which operate
# on memory buffers because generally the OVM methods require calldata
# which is larger than the provided buffers. So we copy all the memory to
# a new buffer at MSIZE to ensure we have enough memory, and now we have to
# also fiddle with the buffer offset and length to provide to CALL. We can't
# just use the vyper abi_encode/decode macros because we need to preserve the
# semantics of returndatasize; also the arguments are on the stack and
# abi_encode expects its arguments in memory. Also note this clobbers MSIZE,
# which luckily isn't used elsewhere in the vyper codebase.
#
# For execution-manager methods with no dynamic args (and the method args are
# the same as the order they appear on the stack), the ABI-encoding of static
# data is identical to memory encoding, so the strategy is very simple, we just
# write the method_id and then sequentially copy the args from the stack
# word-for-word to the args buffer. For methods with dynamic args or returndata
# (CREATE*,CALL*,REVERT,EXTCODECOPY), we need to convert the provided
# offset and length args into ABI-encoded bytestrings. Since the order of the
# stack arguments is a little different for each of those ops, we do this on a
# case by case basis, in _marshal_bytestring and _unmarshal_bytestring.
# In pseudocode then, the strategy for steps 1-3 is:
#
#  marshal_static_args
#  if has_bytes:
#      marshal_bytestring
#  push_ovm_exec_
#  OVM_EXEC_STRING
#  if has_returndata:
#      unmarshal_bytestring
#  unmarshal_static_return

# note changes in https://github.com/ethereum-optimism/solidity/pull/28
# ovmBALANCE, ovmCALLVALUE, ovmSELFBALANCE have been added.
# ovmCALL params have changed.

import warnings
from typing import List

import vyper.utils as util
from vyper.exceptions import VyperException
from vyper.old_codegen.lll_node import LLLnode


class OVMException(VyperException):
    pass


class OVMBlockedOpException(OVMException):
    pass


# OVMSubroutine is a simple class encapsulating everything we want to know
# about converting an EVM opcode to its corresponding OVM method.
class _OVMSubroutine:
    # defaults
    opcode: str = ""
    method_name: str = ""  # the method name in the execution manager contract
    evm_args: List[str] = []
    ovm_args: List[str] = []
    evm_returns: List[str] = []
    ovm_returns: List[str] = []
    ovm_arg_types: List[str] = []  # to calculate method_id

    @property
    def abi_signature(self):
        args = ",".join(t for t in self.ovm_arg_types)
        return f"{self.method_name}({args})"

    # all of the utility functions operate on the same buffer, which
    # is the original location of msize

    def args_ofst(self, buf):
        """The args buffer to pass to ovm_exec. This is the same for every op"""
        return ["add", self.method_id_overhead - self.method_id_len, buf]

    def ret_ofst(self, buf):
        """The ret ofst to pass to ovm_exec. This is the same for every op"""
        return buf

    def args_len(self):
        """The args len to pass to ovm_exec."""
        raise NotImplementedError()

    def ret_len(self):
        """The ret len to pass to ovm_exec"""
        raise NotImplementedError()

    # common util funcs
    def _mstore_method_id(self, buf):
        method_id = util.abi_method_id(self.abi_signature)
        return ["mstore", buf, method_id]  # left padded 28

    @property
    def method_id_overhead(self):
        """The number of bytes reserved for the method_id"""
        # Could be 4 but we left pad the method_id with 0s to align everything
        return 32

    @property
    def method_id_len(self):
        """The actual number of bytes used by a method_id"""
        return 4

    @property
    def bytestring_overhead(self):
        """The number of bytes used by the length word in the ABI encoding"""
        return 32

    @property
    def static_args_len(self):
        """The length of the static data in the ABI-encoded args"""
        # 32*num words, i.e. len(sig_args), not including method_id
        return 32 * len(self.ovm_args)

    @property
    def static_return_len(self):
        """The length of the static data in the ABI-encoded returndata"""
        return 32 * len(self.ovm_returns)

    def _marshal_static_args(self, buf):
        """Take the EVM opcode-provided stack items and write them
           into the static section of the ABI-encoded calldata to
           prepare for CALL to OVM execution manager
        """
        # sanity check
        assert len(self.ovm_args) == len(self.ovm_arg_types), (self.ovm_args, self.ovm_arg_types)
        args = zip(self.ovm_args, self.ovm_arg_types)
        ret = ["seq"]
        for i, (arg, arg_ty) in enumerate(args):
            dst = ["add", buf, (i + 1) * 32]
            if arg_ty == "bytes":
                ret.append(["mstore", dst, self.static_args_len])
            else:
                assert arg in self.evm_args
                # arg is an LLL variable defined in with_subroutine_vars
                ret.append(["mstore", dst, arg])
        return ret

    def _unmarshal_static_return(self, buf):
        """Push any items expected by the EVM opcode onto the stack
        """
        # not really a requirement, just a sanity check
        assert len(self.evm_returns) <= 1
        ret = ["seq_unchecked"]
        for x in self.evm_returns:
            # sanity check: will throw if arg not in self.ovm_args
            ix = self.ovm_returns.index(x)
            ret.append(["mload", ["add", buf, ix * 32]])
        return ret

    def _marshal_bytestring(self, buf):
        """Copy the argument bytestring (if any) from the buffer
           specified by the EVM opcode into the appropriate place in
           the ABI-encoded calldata buffer
        """
        return ["pass"]  # default no bytestring

    def _unmarshal_bytestring(self, _buf):
        """Copy the returned bytestring (if any) into the buffer
           specified by the EVM opcode
        """
        return ["pass"]  # default no bytestring

    def _cleanup(self, buf):
        # zero out used memory
        return ["calldatacopy", buf, "calldatasize", ["sub", "msize", buf]]

    def _with_subroutine_vars(self, subroutine):
        """nest with instructions, e.g.
        build(x, y, ...) -> (with x pass (with y pass (...)))
        """

        def build(evm_args, subroutine):
            if len(evm_args) == 0:
                return subroutine
            else:
                arg = evm_args[0]
                remaining_args = evm_args[1:]
                return ["with", arg, "pass", build(remaining_args, subroutine)]

        return build(self.evm_args, subroutine)

    def _call_execution_manager(self, buf):
        return [
            "ovm_exec",
            self.args_ofst(buf),
            self.args_len,
            self.ret_ofst(buf),
            self.ret_len,
        ]

    def subroutine_label(self):
        """The label to use for the subroutine in the rewritten LLL"""
        return "_ovm_" + self.opcode

    def subroutine_lll(self):
        """Generate the OVM subroutine to call the execution manager
           for a given opcode.
           Expects jumpdest + args on the stack, pushes the stack return
           items expected by the EVM opcode.
        """
        buf = "buf"
        lll = [
            "seq_unchecked",
            self._with_subroutine_vars(
                [
                    "with",
                    buf,
                    "msize",
                    [
                        "seq_unchecked",
                        self._mstore_method_id(buf),
                        self._marshal_static_args(buf),
                        self._marshal_bytestring(buf),
                        self._call_execution_manager(buf),
                        self._unmarshal_bytestring(buf),
                        self._unmarshal_static_return(buf),
                        self._cleanup(buf),
                    ],
                ]
            ),
        ]
        # it returned an item, we need to swap it with the next stack item
        # to prepare for the jump
        if len(self.evm_returns) > 0:
            lll.append(["swap1", "pass", "pass"])
        # jump out of here
        lll.append(["jump", "pass"])
        return LLLnode.from_list(lll)


class _OVMSimpleSubroutine(_OVMSubroutine):
    """
    Instructions which simply take their arguments as stack items,
    may return up to one item on the stack, and the execution
    manager takes the arguments in the same order as they appear
    on the stack.
    """

    @property
    def args_len(self):
        return self.method_id_len + self.static_args_len

    @property
    def ret_len(self):
        return self.static_return_len

    def unmarshal_return(self, buf):
        return self._unmarshal_static_return(buf)


class _OVMMarshalsBytestring(_OVMSubroutine):
    """Instructions which have input bytestrings"""

    def arg_copy_ofst(self):
        """An expression returning the input bytestring location"""
        raise NotImplementedError(self.method_name)

    def arg_copy_len(self):
        """An expression returning the input bytestring length"""
        raise NotImplementedError(self.method_name)

    # offset of the actual bytestring after method_id, bytestring length
    # word and all static args
    @property
    def total_args_overhead(self):
        return self.method_id_len + self.bytestring_overhead + self.static_args_len

    # Dealing With Bytestrings
    #
    # abbreviations:
    # a: args
    # b: bytes
    # f: fake
    # r: real
    # o: offset
    # l: length
    # e.g.: fao == fake args offset
    #       fabo == fake arg bytes offset (calldata arg location)
    # ovm_copy and ovm_exec both take src_ofst, src_len, dst_ofst, dst_len
    # what we want to do:
    # 1. ovm_copy macro real arg buffer into calldata arg
    #   ovm_copy(rao, ral, fabo, ral)
    # 2. ovm_exec macro fake args buffer into the fake return buffer:
    #   ovm_exec(fao, fal, fro, frl)
    # then (if this is CALL*, N/A to CREATE* or REVERT), to make sure
    # returndatasize and returndatacopy still work correctly,
    # 3. ovm_copy macro the returndata into real return buffer:
    #   ovm_copy(fro, frl, rro, rrl)
    # notes: use the same buffer for fake args and fake return. fro == fao
    # args_overhead = arg_bytes_ofst + 32 (static data len + 1 word to store bytes len)
    # return_overhead = arg_bytes_ofst + 32 (ditto)
    # fal  = ral + args_overhead
    # fabo = fao + args_overhead
    # frl  = rrl + return_overhead
    # frbo = fbo + return_overhead
    def _marshal_bytestring(self, buf):
        src_ofst = self.arg_copy_ofst
        src_len = self.arg_copy_len
        dst_ofst = ["add", buf, self.total_args_overhead]
        dst_len = self.arg_copy_len  # same as src

        # location of the bytestring length in ABI encoding
        length_ofst = self.method_id_overhead + self.static_args_len

        return [
            "seq",
            # store calldata length for ABI encoding
            ["mstore", ["add", length_ofst, buf], self.args_len],
            # copy the bytes to the appropriate place in abi buffer
            ["ovm_copy", src_ofst, src_len, dst_ofst, dst_len],
        ]


class _OVMCallLike(_OVMMarshalsBytestring):
    # evm_args are something like
    # (..., "args_ofst", "args_len", "ret_ofst", "ret_len")

    @property
    def arg_copy_ofst(self):
        return ["args_ofst"]

    @property
    def arg_copy_len(self):
        return ["args_len"]

    @property
    def args_len(self):
        # 32 + 32 + 32*len(args) + "args_len"
        return ["add", self.total_args_overhead, self.arg_copy_len]

    @property
    def ret_len(self):
        # 32 + 32*len(args) + "args_len"
        return ["add", self.bytestring_overhead + self.static_return_len, "ret_len"]

    def _unmarshal_bytestring(self, buf):
        # to preserve the semantics of returndatasize, it's
        # important to provide `returndatasize - return_overhead` to the
        # identity here (instead of the provided ret_len) in case the
        # returndata is larger than the provided buffer.
        src_ofst = buf
        src_len = ["sub", "returndatasize", self.bytestring_overhead + self.static_return_len]
        dst_ofst = ["ret_ofst"]
        dst_len = ["ret_len"]
        # returndatasize and returndatacopy are both now set correctly.
        return ["ovm_copy", src_ofst, src_len, dst_ofst, dst_len]

    def _cleanup(self, buf):
        return ["pass"]
        # in the future we might want something like this:
        # return [
        #    "seq",
        #    [
        #        "with",
        #        "return_buffer_end",
        #        ["add", "ret_ofst", "ret_len"],
        #        # return buffer could be past the end of original msize,
        #        # we don't want to accidentally zero it.
        #        ["if", ["gt", "return_buffer_end", buf], ["set", buf, "return_buffer_end"]],
        #    ],
        #    ["calldatacopy", buf, ["sub", "msize", buf]],
        # ]


class _OVMCreateLike(_OVMMarshalsBytestring):
    # evm_args something like
    # (..., "code_ofst", "code_len")

    @property
    def arg_copy_ofst(self):
        return ["code_ofst"]

    @property
    def arg_copy_len(self):
        return ["code_len"]

    @property
    def args_len(self):
        return [
            "add",
            self.method_id_len + self.bytestring_overhead + self.static_args_len,
            self.total_args_overhead,
            "code_len",
        ]

    @property
    def ret_len(self):
        return 0x20  # only care about the returned address


class _OVMRevertLike(_OVMMarshalsBytestring):
    @property
    def arg_copy_ofst(self):
        return "reason_ofst"

    @property
    def arg_copy_len(self):
        return "reason_len"

    @property
    def args_len(self):
        return ["add", self.total_args_overhead, "reason_len"]

    @property
    def ret_len(self):
        return 0x00  # don't care, already reverted


# aliases to make signatures prettier
bool_ = "bool"
uint256 = "uint256"
bytes_ = "bytes"
address = "address"

OVM_METHODS = {}


def ovm_mapper(cls):
    opcode = cls.__name__.lower()
    cls.opcode = opcode
    cls.method_name = f"ovm{opcode.upper()}"
    OVM_METHODS[opcode] = cls()
    return cls


@ovm_mapper
class SStore(_OVMSimpleSubroutine):
    evm_args = ["key", "value"]
    ovm_args = ["key", "value"]
    ovm_arg_types = ["uint256", "uint256"]


@ovm_mapper
class SLoad(_OVMSimpleSubroutine):
    evm_args = ["key"]
    ovm_args = ["key"]
    ovm_arg_types = ["uint256"]
    evm_returns = ["value"]
    ovm_returns = ["value"]


@ovm_mapper
class Call(_OVMCallLike):
    evm_args = ["gas", "addr", "value", "args_ofst", "args_len", "ret_ofst", "ret_len"]
    ovm_args = ["gas", "addr", "value", "BYTES_calldata"]
    ovm_arg_types = [uint256, address, uint256, bytes_]
    evm_returns = ["success"]
    ovm_returns = ["success", "BYTES_returndata"]


@ovm_mapper
class StaticCall(_OVMCallLike):
    evm_args = ["gas", "addr", "args_ofst", "args_len", "ret_ofst", "ret_len"]
    ovm_args = ["gas", "addr", "BYTES_calldata"]
    ovm_arg_types = [uint256, uint256, bytes_]
    evm_returns = ["success"]
    ovm_returns = ["success", "BYTES_returndata"]


@ovm_mapper
class DelegateCall(_OVMCallLike):
    evm_args = ["gas", "addr", "args_ofst", "args_len", "ret_ofst", "ret_len"]
    ovm_args = ["gas", "addr", "BYTES_calldata"]
    ovm_arg_types = [uint256, uint256, bytes_]
    evm_returns = ["success"]
    ovm_returns = ["success", "BYTES_returndata"]


@ovm_mapper
class Address(_OVMSimpleSubroutine):
    evm_returns = ["addr"]
    ovm_returns = ["addr"]


@ovm_mapper
class ChainID(_OVMSimpleSubroutine):
    evm_returns = ["chain_id"]
    ovm_returns = ["chain_id"]


@ovm_mapper
class ExtCodeSize(_OVMSimpleSubroutine):
    evm_args = ["addr"]
    ovm_args = ["addr"]
    ovm_arg_types = [address]
    evm_returns = ["size"]
    ovm_returns = ["size"]


@ovm_mapper
class ExtCodeHash(_OVMSimpleSubroutine):
    evm_args = ["addr"]
    ovm_args = ["addr"]
    ovm_arg_types = [address]
    evm_returns = ["hash"]
    ovm_returns = ["hash"]


@ovm_mapper
class ExtCodeCopy(_OVMSimpleSubroutine):
    # write out the signature for future reference but basically blocked
    evm_args = ["addr", "dest_ofst", "offset", "length"]
    ovm_args = ["addr", "offset", "length"]
    ovm_arg_types = [address, uint256, uint256]
    evm_returns: List[str] = []
    ovm_returns = ["BYTES_code"]

    def subroutine_lll(self):
        raise NotImplementedError("extcodecopy not generated by vyper")


@ovm_mapper
class Number(_OVMSimpleSubroutine):
    evm_returns = ["number_"]
    ovm_returns = ["number_"]


@ovm_mapper
class Timestamp:
    evm_returns = ["timestamp_"]
    ovm_returns = ["timestamp_"]


@ovm_mapper
# note that this triggers a revert in OVM_EXEC_SUBROUTINE
class Revert(_OVMRevertLike):
    evm_args = ["reason_ofst", "reason_len"]
    ovm_args = ["BYTES_reason"]
    ovm_arg_types = [bytes_]


@ovm_mapper
class Create(_OVMCreateLike):
    evm_args = ["value", "code_ofst", "code_len"]
    ovm_args = ["BYTES_bytecode"]
    # TODO future ovm_args = ("value", "BYTES_bytecode")
    ovm_arg_types = [bytes_]
    evm_returns = ["addr"]
    ovm_returns = ["addr", "BYTES_revert_reason"]

    def subroutine_lll(self):
        warnings.warn("ovmCREATE ABI is unstable, this is an untested codepath")
        return super().subroutine_lll()


@ovm_mapper
class Create2(_OVMCreateLike):
    evm_args = ["value", "code_ofst", "code_len", "salt"]
    ovm_args = ["BYTES_bytecode", "salt"]
    # TODO future ovm_args = ("value", "BYTES_bytecode", "salt")
    ovm_arg_types = [bytes_]
    evm_returns = ["addr"]
    ovm_returns = ["addr", "BYTES_revert_reason"]

    def subroutine_lll(self):
        warnings.warn("ovmCREATE2 ABI is unstable, this is an untested codepath")
        return super().subroutine_lll()


@ovm_mapper
class CallValue(_OVMSimpleSubroutine):
    evm_returns = ["value_"]
    ovm_returns = ["value_"]


@ovm_mapper
class Balance(_OVMSimpleSubroutine):
    evm_args = ["addr"]
    ovm_args = ["addr"]
    ovm_arg_types = [address]
    evm_returns = ["value_"]
    ovm_returns = ["value_"]


@ovm_mapper
class SelfBalance(_OVMSimpleSubroutine):
    evm_returns = ["value_"]
    ovm_returns = ["value_"]


OVM_BLOCKED_OPS = {
    "blockhash",
    "callcode",
    "coinbase",
    "difficulty",
    "gasprice",
    "origin",
    "selfdestruct",
}


# Overwrite evm opcodes so that ovm_copy and ovm_exec are accepted by
# LLLnode. (This isn't great but the alternative is rewriting the import
# graph for LLLnode).
def monkeypatch_evm_opcodes(opcodes):
    # this inserts values which will get replaced by
    # vyper.ovm.asm.rewrite_asm
    opcodes["OVM_COPY"] = ("OVM_COPY", 4, 0, 700)
    opcodes["OVM_EXEC"] = ("OVM_EXEC", 4, 0, 700)


# is this useful?
def undo_monkeypatch_evm_opcodes(opcodes):
    opcodes.pop("OVM_COPY", None)
    opcodes.pop("OVM_EXEC", None)


# entry point for the module
def rewrite_lll_for_ovm(lll_node, labels=None, outer=True):
    if labels is None:
        labels = {}

    def generate_label(opcode):
        labels[opcode] = labels.get(opcode, 0) + 1
        return opcode + str(labels[opcode])

    opcode = lll_node.value

    # check valid ovm
    if opcode in OVM_BLOCKED_OPS:
        raise OVMBlockedOpException(opcode)
    if opcode in ("create", "create2"):
        value_ = lll_node.args[0]
        if value_ != 0:  # safest is to check it's a literal 0.
            raise OVMException(f"ovmCREATE cannot be called with nonzero value {value_}")

    # recurse
    if opcode == "lll":  # each LLL block is it's own code
        rewritten_args = [rewrite_lll_for_ovm(arg, None, True) for arg in lll_node.args]
    else:
        rewritten_args = [rewrite_lll_for_ovm(arg, labels, False) for arg in lll_node.args]

    if opcode in OVM_METHODS:
        label = generate_label(opcode)  # unique location to jump back to
        subroutine = OVM_METHODS[opcode]
        return LLLnode.from_list(
            ["seq_unchecked"]
            + ["_sym_" + label]  # undocumented LLL: push the jumpdest onto the stack
            + [lll for lll in reversed(rewritten_args)]
            + [["goto", subroutine.subroutine_label()]]
            + [["label", label]]
            + ["dummy"]
            if subroutine.evm_returns
            else ["pass"]
        )

    lll_ret = [lll_node.value] + rewritten_args

    # add postambles if it's an "outer" code block
    if outer:
        lll_ret = ["seq", lll_ret]
        # only need to add opcodes we've seen, conveniently stored in `labels`
        seen_opcodes = list(labels.keys())
        # lll_to_assembly might add the revert0 string, even if we don't
        # see any explicit revert instructions in the LLL.
        seen_opcodes.append("revert")
        for seen_opcode in labels.keys():
            subroutine = OVM_METHODS[seen_opcode]
            lll_ret.append(["label", subroutine.subroutine_label()])
            lll_ret.append(subroutine.subroutine_lll())

    ret = LLLnode.from_list(lll_ret)
    return ret
