import hypothesis.strategies as st
import pytest
from hypothesis import given, settings

import vyper.utils as utils
from vyper.compiler.settings import OptimizationLevel


@pytest.mark.parametrize("opt_level", list(OptimizationLevel))
@pytest.mark.parametrize("calldatasize_encoding_bytes", [1, 2, 3])
@settings(max_examples=25, deadline=None)
@given(seed=st.integers(min_value=0, max_value=2**64 - 1))
@pytest.mark.fuzzing
def test_selector_table_fuzz(
    calldatasize_encoding_bytes, seed, opt_level, w3, get_contract, assert_tx_failed, get_logs
):
    max_calldata_bytes = 2 ** (8 * calldatasize_encoding_bytes)

    def abi_sig(calldata_words, i):
        args = "" if not calldata_words else f"uint256[{calldata_words}]"
        return f"foo{seed + i}({args})"

    def generate_func_def(mutability, calldata_words, i):
        args = "" if not calldata_words else f"x: uint256[{calldata_words}]"
        _log_return = f"log _Return({i})" if mutability == "@payable" else ""
        return f"""
@external
{mutability}
def foo{seed + i}({args}) -> uint256:
    {_log_return}
    return {i}
    """

    @given(
        methods=st.lists(
            st.tuples(
                st.sampled_from(["@pure", "@view", "@nonpayable", "@payable"]),
                st.integers(min_value=0, max_value=max_calldata_bytes // 32),
            ),
            min_size=1,
            max_size=100,
        )
    )
    def _test(methods):
        func_defs = "\n".join(generate_func_def(m, s, i) for i, (m, s) in enumerate(methods))

        code = f"""
event CalledDefault: pass  #TODO: allow newline in lark grammar

event _Return:
    val: uint256

{func_defs}


@external
def __default__():
    log CalledDefault()"""

        c = get_contract(code, override_opt_level=opt_level)

        for i, (mutability, n_calldata_words) in enumerate(methods):
            funcname = f"foo{seed + i}"
            func = getattr(c, funcname)
            args = [[1] * n_calldata_words] if n_calldata_words else []
            assert func(*args) == i

            method_id = utils.method_id(abi_sig(n_calldata_words, i))
            argsdata = b"\x00" * (n_calldata_words * 32)

            # do payable check
            if mutability == "@payable":
                tx = func(*args, transact={"value": 1})
                (event,) = get_logs(tx, c, "_Return")
                assert event.args.val == i
            else:
                hexstr = (method_id + argsdata).hex()
                assert_tx_failed(
                    lambda: w3.eth.send_transaction({"to": c.address, "data": hexstr, "value": 1})
                )

            # now do calldatasize check
            calldata = (method_id + argsdata)[:-1]  # strip one byte
            hexstr = calldata.hex()
            if n_calldata_words == 0:
                # no args, hit default function

                tx = w3.eth.send_transaction({"to": c.address, "data": hexstr})
                logs = get_logs(tx, c, "CalledDefault")
                assert len(logs) == 1

            else:
                assert_tx_failed(lambda: w3.eth.send_transaction({"to": c.address, "data": hexstr}))

        # TODO:
        # - test default function with 0 bytes
        # - test default function with 0-3 bytes of calldata

    _test()
