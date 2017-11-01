import pytest
from tests.setup_transaction_tests import chain as s, tester as t, ethereum_utils as u, check_gas, \
    get_contract_with_gas_estimation, get_contract


def test_basic_bytes_keys():
    code = """
mapped_bytes: num[bytes <= 5]

def set(k: bytes <= 5, v: num):
    self.mapped_bytes[k] = v


def get(k: bytes <= 5) -> num:
    return self.mapped_bytes[k]
    """

    c = get_contract(code)

    c.set("test", 54321)

    assert c.get("test") == 54321


def test_basic_bytes_literal_key():
    code = """
mapped_bytes: num[bytes <= 5]


def set(v: num):
    self.mapped_bytes["test"] = v

def get(k: bytes <= 5) -> num:
    return self.mapped_bytes[k]
    """

    c = get_contract(code)

    c.set(54321)

    assert c.get("test") == 54321
