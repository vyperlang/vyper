import pytest

from vyper.venom.mem_allocator import MemoryAllocator

MEM_BLOCK_ADDRESS = 0x1000


@pytest.fixture
def allocator():
    return MemoryAllocator(1024, MEM_BLOCK_ADDRESS)


def test_initial_state(allocator):
    assert allocator.get_free_memory() == 1024
    assert allocator.get_allocated_memory() == 0


def test_single_allocation(allocator):
    addr = allocator.allocate(256)
    assert addr == MEM_BLOCK_ADDRESS
    assert allocator.get_free_memory() == 768
    assert allocator.get_allocated_memory() == 256


def test_multiple_allocations(allocator):
    addr1 = allocator.allocate(256)
    addr2 = allocator.allocate(128)
    addr3 = allocator.allocate(64)

    assert addr1 == MEM_BLOCK_ADDRESS
    assert addr2 == MEM_BLOCK_ADDRESS + 256
    assert addr3 == MEM_BLOCK_ADDRESS + 384
    assert allocator.get_free_memory() == 576
    assert allocator.get_allocated_memory() == 448


def test_deallocation(allocator):
    addr1 = allocator.allocate(256)
    addr2 = allocator.allocate(128)

    assert allocator.deallocate(addr1) is True
    assert allocator.get_free_memory() == 896
    assert allocator.get_allocated_memory() == 128

    assert allocator.deallocate(addr2) is True
    assert allocator.get_free_memory() == 1024
    assert allocator.get_allocated_memory() == 0


def test_allocation_after_deallocation(allocator):
    addr1 = allocator.allocate(256)
    allocator.deallocate(addr1)
    addr2 = allocator.allocate(128)

    assert addr2 == MEM_BLOCK_ADDRESS
    assert allocator.get_free_memory() == 896
    assert allocator.get_allocated_memory() == 128


def test_out_of_memory(allocator):
    allocator.allocate(1000)
    with pytest.raises(MemoryError):
        allocator.allocate(100)


def test_invalid_deallocation(allocator):
    assert allocator.deallocate(0x2000) is False


def test_fragmentation_and_merging(allocator):
    addr1 = allocator.allocate(256)
    addr2 = allocator.allocate(256)
    addr3 = allocator.allocate(256)

    assert allocator.get_free_memory() == 256
    assert allocator.get_allocated_memory() == 768

    allocator.deallocate(addr1)
    assert allocator.get_free_memory() == 512
    assert allocator.get_allocated_memory() == 512

    allocator.deallocate(addr3)
    assert allocator.get_free_memory() == 768
    assert allocator.get_allocated_memory() == 256

    addr4 = allocator.allocate(512)
    assert addr4 == MEM_BLOCK_ADDRESS + 512
    assert allocator.get_free_memory() == 256
    assert allocator.get_allocated_memory() == 768

    allocator.deallocate(addr2)
    assert allocator.get_free_memory() == 512
    assert allocator.get_allocated_memory() == 512

    allocator.deallocate(addr4)
    assert allocator.get_free_memory() == 1024  # All blocks merged
    assert allocator.get_allocated_memory() == 0

    # Test if we can now allocate the entire memory
    addr5 = allocator.allocate(1024)
    assert addr5 == MEM_BLOCK_ADDRESS
    assert allocator.get_free_memory() == 0
    assert allocator.get_allocated_memory() == 1024


def test_exact_fit_allocation(allocator):
    addr1 = allocator.allocate(1024)
    assert addr1 == MEM_BLOCK_ADDRESS
    assert allocator.get_free_memory() == 0
    assert allocator.get_allocated_memory() == 1024

    allocator.deallocate(addr1)
    addr2 = allocator.allocate(1024)
    assert addr2 == MEM_BLOCK_ADDRESS
    assert allocator.get_free_memory() == 0
    assert allocator.get_allocated_memory() == 1024
