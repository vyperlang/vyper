from tests.venom_utils import PrePostChecker
from vyper.venom.passes import DFTPass

_check_pre_post = PrePostChecker([DFTPass])


def _check_no_change(pre, hevm=None):
    _check_pre_post(pre, pre, hevm=hevm)


def test_dft():
    """
    Basic test for dft pass
    """
    pre = """
    main:
        %x = 1
        %y = 2
        return %x, %y
    """
    post = """
    main:
        %y = 2
        %x = 1
        return %x, %y
    """
    _check_pre_post(pre, post)


def test_dft_memtop_stays_after_memory_read():
    """
    `memtop` lowers to MSIZE, and memory reads (like mload) can expand
    memory, advancing MSIZE. DFT must not schedule `memtop` before a
    prior memory read.
    """
    pre = """
    main:
        %ptr = source
        %v = mload %ptr
        %m = memtop
        sink %v, %m
    """
    # hevm does not model msize-dependent equivalence
    _check_no_change(pre, hevm=False)


def test_dft_memory_read_stays_after_memtop():
    """
    The converse direction: a memory read scheduled before a prior
    `memtop` could expand memory and change the observed MSIZE.
    """
    pre = """
    main:
        %ptr = source
        %m = memtop
        %v = mload %ptr
        sink %m, %v
    """
    _check_no_change(pre, hevm=False)
