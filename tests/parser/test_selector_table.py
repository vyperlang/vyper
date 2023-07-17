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
        args = "" if not calldata_words else f"uint256[{calldata_words}]"
        return f"""
@external
{mutability}
def foo{seed + i}({args}) -> uint256:
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
        code = "\n".join(generate_func_def(m, s, i) for i, (m, s) in enumerate(methods))

        default_function = """
event CalledDefault:
    pass

@external
def __default__():
    log CalledDefault()
        """
        code = code + default_function

        c = get_contract(code)

        for i, (mutability, n_calldata_words) in enumerate(methods):
            funcname = f"foo{seed + i}"
            func = getattr(c, funcname)
            assert func([1] * n_calldata_words) == i

            if mutability == "@payable":
                assert func([1] * n_calldata_words, transact={"value": 1}) == i
            else:
                assert_tx_failed(lambda: func([1] * n_calldata_words, transact={"value": 1}))

            # now do calldatasize check
            method_id = utils.method_id(abi_sig(n_calldata_words, i))
            argsdata = b"\x00" * (n_calldata_words * 32)
            calldata = (method_id + argsdata)[:-1]  # strip one byte
            hexstr = calldata.hex()
            if method_id.endswith(b"\x00"):
                # hit default function

                tx = w3.eth.send_transaction({"to": c.address, "data": hexstr})
                logs = get_logs(tx, c, "CalledDefault")
                assert len(logs) == 1

            else:
                assert_tx_failed(w3.eth.send_transaction({"to": c.address, "data": hexstr}))

        # TODO:
        # - test default function with 0 bytes
        # - test default function with 0-3 bytes of calldata

    _test()
