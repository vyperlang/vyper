import pytest

from vyper.utils import erc7201_storage_slot


def test_erc7201_slot_calculation():
    """Test basic ERC-7201 slot calculation."""
    namespace = "test.namespace"
    slot = erc7201_storage_slot(namespace)

    # Verify the result is aligned to 256 (last byte is 0)
    assert slot & 0xFF == 0, "ERC-7201 slots should be 256-aligned"

    # Verify reproducibility
    assert erc7201_storage_slot(namespace) == slot


def test_erc7201_different_namespaces():
    """Test that different namespaces produce different slots."""
    slot1 = erc7201_storage_slot("namespace.one")
    slot2 = erc7201_storage_slot("namespace.two")
    slot3 = erc7201_storage_slot("completely.different")

    assert slot1 != slot2
    assert slot1 != slot3
    assert slot2 != slot3


def test_erc7201_hex_namespace():
    """Test that hex namespaces are treated as raw slot values."""
    # Simple hex value
    assert erc7201_storage_slot("0x100") == 256
    assert erc7201_storage_slot("0x1000") == 4096
    assert erc7201_storage_slot("0x0") == 0

    # Large hex value
    large_hex = "0x" + "ff" * 32
    expected = int("0x" + "ff" * 32, 16)
    assert erc7201_storage_slot(large_hex) == expected


def test_erc7201_formula_correctness():
    """
    Verify the ERC-7201 formula: keccak256(keccak256(id) - 1) & ~0xff

    This test manually computes the expected value to verify the implementation.
    """
    namespace = "example.main"

    # Step 1: Hash the namespace
    first_hash = keccak256(namespace.encode("utf-8"))
    first_hash_int = int.from_bytes(first_hash, "big")

    # Step 2: Subtract 1
    decremented = first_hash_int - 1

    # Step 3: Hash again
    decremented_bytes = decremented.to_bytes(32, "big")
    second_hash = keccak256(decremented_bytes)
    result = int.from_bytes(second_hash, "big")

    # Step 4: Clear last byte for 256-alignment
    expected = result & ~0xFF

    # Compare with function
    actual = erc7201_storage_slot(namespace)
@pytest.mark.parametrize(
    "namespace,expected",
    [
         ("example.main", 0x183a6125c38840424c4a85fa12bab2ab606c4b6d0e7cc73c0c06ba5300eab500),
    ],
)
def test_erc7201_reference(namespace, expected):
    assert erc7201_storage_slot(namespace) == expected


def test_erc7201_alignment():
    """Test that all ERC-7201 slots are 256-aligned."""
    namespaces = [
        "a",
        "abc",
        "test.namespace.v1",
        "org.project.storage",
        "very.long.namespace.with.many.segments.for.testing",
    ]

    for ns in namespaces:
        slot = erc7201_storage_slot(ns)
        assert slot % 256 == 0, f"Namespace '{ns}' produced non-aligned slot {slot}"


def test_erc7201_empty_namespace():
    """Test that empty string namespace still works (edge case)."""
    slot = erc7201_storage_slot("")
    assert slot & 0xFF == 0  # Should still be aligned
