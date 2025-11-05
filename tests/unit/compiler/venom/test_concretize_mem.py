from tests.venom_utils import PrePostChecker
from vyper.venom.passes import ConcretizeMemLocPass

_check_pre_post = PrePostChecker([ConcretizeMemLocPass], default_hevm=False)


def test_valid_overlap():
    pre = """
    main:
        calldatacopy [3,256], 100, 256
        %1 = mload [3,256]
        calldatacopy [4,32], 200, 32
        %2 = mload [4,32]
        calldatacopy [3,256], 1000, 256
        %3 = mload [3,256]
        sink %1, %2, %3
    """
    post = """
    main:
        calldatacopy 64, 100, 256
        %1 = mload 64
        calldatacopy 64, 200, 32
        %2 = mload 64
        calldatacopy 64, 1000, 256
        %3 = mload 64
        sink %1, %2, %3
    """

    _check_pre_post(pre, post)
