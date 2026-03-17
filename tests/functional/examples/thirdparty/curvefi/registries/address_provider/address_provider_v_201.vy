# pragma version >=0.4.2
"""
@title CurveAddressProvider
@custom:version 2.0.1
@author Curve.Fi
@license Copyright (c) Curve.Fi, 2020-2024 - all rights reserved
@notice An entrypoint contract for Curve's various registries
@dev Allows adding arbitrary IDs instead of sequential IDs.
     Mapping for non Ethereum deployments
     (empty IDs are specific to mainnet):
        0: ---- empty ----
        1: ---- empty ----
        2: Exchange Router
        3: ---- empty ----
        4: Fee Distributor
        5: ---- empty ----
        6: ---- empty ----
        7: Metaregistry
        8: ---- empty ----
        9: ---- empty ----
        10: ---- empty ----
        11: TricryptoNG Factory
        12: StableswapNG Factory
        13: TwocryptoNG Factory
        14: ---- empty ----
        15: ---- empty ----
        16: ---- empty ----
        17: LLAMMA Factory OneWayLending
        18: Rate Provider
        19: CRV Token
        20: Gauge Factory
        21: Ownership Admin
        22: Parameter Admin
        23: Emergency Admin
        24: CurveDAO Vault
        25: crvUSD Token
        26: MetaZap
        27: Deposit&StakeZap
"""

version: public(constant(String[8])) = "2.0.1"


event NewEntry:
    id: indexed(uint256)
    addr: address
    description: String[64]

event EntryModified:
    id: indexed(uint256)
    version: uint256

event EntryRemoved:
    id: indexed(uint256)

event CommitNewAdmin:
    admin: indexed(address)

event NewAdmin:
    admin: indexed(address)


struct AddressInfo:
    addr: address
    description: String[256]
    version: uint256
    last_modified: uint256


admin: public(address)
future_admin: public(address)

num_entries: public(uint256)
check_id_exists: public(HashMap[uint256, bool])
_ids: DynArray[uint256, 1000]
get_id_info: public(HashMap[uint256, AddressInfo])

deployer: immutable(address)


@deploy
def __init__():
    self.admin  = msg.sender
    deployer = msg.sender


@external
def set_owner(_owner: address):
    
    assert msg.sender == deployer
    assert self.admin == deployer
    assert _owner != deployer

    self.admin = _owner
    log NewAdmin(admin=_owner)


# ------------------------------ View Methods --------------------------------

@view
@external
def ids() -> DynArray[uint256, 1000]:
    """
    @notice returns IDs of active registry items in the AddressProvider.
    @return An array of IDs.
    """
    _ids: DynArray[uint256, 1000] = []
    for _id: uint256 in self._ids:
        if self.check_id_exists[_id]:
            _ids.append(_id)

    return _ids


@view
@external
def get_address(_id: uint256) -> address:
    """
    @notice Fetch the address associated with `_id`
    @dev Returns empty(address) if `_id` has not been defined, or has been unset
    @param _id Identifier to fetch an address for
    @return Current address associated to `_id`
    """
    return self.get_id_info[_id].addr


# -------------------------- State-Mutable Methods ---------------------------


@internal
def _update_entry_metadata(_id: uint256):

    _version: uint256 = self.get_id_info[_id].version + 1
    self.get_id_info[_id].version = _version
    self.get_id_info[_id].last_modified = block.timestamp

    log EntryModified(id=_id, version=_version)


@internal
def _remove_id(_id: uint256) -> bool:

    assert self.check_id_exists[_id]  # dev: id does not exist

    # Clear ID:
    self.get_id_info[_id].addr = empty(address)
    self.get_id_info[_id].last_modified = 0
    self.get_id_info[_id].description = ''
    self.get_id_info[_id].version = 0

    self.check_id_exists[_id] = False

    # Reduce num entries:
    self.num_entries -= 1

    # Emit 0 in version to notify removal of id:
    log EntryRemoved(id=_id)

    return True


@internal
def _add_new_id(
    _id: uint256,
    _address: address,
    _description: String[64]
):

    assert not self.check_id_exists[_id]  # dev: id exists

    self.check_id_exists[_id] = True
    self._ids.append(_id)

    # Add entry:
    self.get_id_info[_id] = AddressInfo(
        addr=_address,
        description=_description,
        version=1,
        last_modified=block.timestamp,
    )
    self.num_entries += 1

    log NewEntry(id=_id, addr=_address, description=_description)


@external
def add_new_id(
    _id: uint256,
    _address: address,
    _description: String[64],
):
    """
    @notice Enter a new registry item
    @param _id ID assigned to the address
    @param _address Address assigned to the ID
    @param _description Human-readable description of the ID
    """
    assert msg.sender == self.admin  # dev: admin-only function

    self._add_new_id(_id, _address, _description)


@external
def add_new_ids(
    _ids: DynArray[uint256, 25],
    _addresses: DynArray[address, 25],
    _descriptions: DynArray[String[64], 25],
):
    """
    @notice Enter new registry items
    @param _ids IDs assigned to addresses
    @param _addresses Addresses assigned to corresponding IDs
    @param _descriptions Human-readable description of each of the IDs
    """
    assert msg.sender == self.admin  # dev: admin-only function

    # Check lengths
    assert len(_ids) == len(_addresses)
    assert len(_addresses) == len(_descriptions)

    for i: uint256 in range(len(_ids), bound=20):
        self._add_new_id(
            _ids[i],
            _addresses[i],
            _descriptions[i]
        )


@external
def update_id(
    _id: uint256,
    _new_address: address,
    _new_description: String[64],
):
    """
    @notice Update entries at an ID
    @param _id Address assigned to the input _id
    @param _new_address Address assigned to the _id
    @param _new_description Human-readable description of the identifier
    """
    assert msg.sender == self.admin  # dev: admin-only function
    assert self.check_id_exists[_id]  # dev: id does not exist

    # Update entry at _id:
    self.get_id_info[_id].addr = _new_address
    self.get_id_info[_id].description = _new_description

    # Update metadata (version, update time):
    self._update_entry_metadata(_id)


@external
def update_address(_id: uint256, _address: address):
    """
    @notice Set a new address for an existing identifier
    @param _id Identifier to set the new address for
    @param _address Address to set
    """
    assert msg.sender == self.admin  # dev: admin-only function
    assert self.check_id_exists[_id]  # dev: id does not exist

    # Update address:
    self.get_id_info[_id].addr = _address

    # Update metadata (version, update time):
    self._update_entry_metadata(_id)


@external
def update_description(_id: uint256, _description: String[256]):
    """
    @notice Update description for an existing _id
    @param _id Identifier to set the new description for
    @param _description New description to set
    """
    assert msg.sender == self.admin  # dev: admin-only function
    assert self.check_id_exists[_id]  # dev: id does not exist

    # Update description:
    self.get_id_info[_id].description = _description

    # Update metadata (version, update time):
    self._update_entry_metadata(_id)


@external
def remove_id(_id: uint256) -> bool:
    """
    @notice Unset an existing identifier
    @param _id Identifier to unset
    @return bool success
    """
    assert msg.sender == self.admin  # dev: admin-only function

    return self._remove_id(_id)


@external
def remove_ids(_ids: DynArray[uint256, 20]) -> bool:
    """
    @notice Unset existing identifiers
    @param _ids DynArray of identifier to unset
    @return bool success
    """
    assert msg.sender == self.admin  # dev: admin-only function

    for _id: uint256 in _ids:
        assert self._remove_id(_id)

    return True


# ------------------------------ Admin Methods -------------------------------


@external
def commit_transfer_ownership(_new_admin: address) -> bool:
    """
    @notice Initiate a transfer of contract ownership
    @dev Once initiated, the actual transfer may be performed three days later
    @param _new_admin Address of the new owner account
    @return bool success
    """
    assert msg.sender == self.admin  # dev: admin-only function
    self.future_admin = _new_admin

    log CommitNewAdmin(admin=_new_admin)

    return True


@external
def apply_transfer_ownership() -> bool:
    """
    @notice Finalize a transfer of contract ownership
    @dev May only be called by the next owner
    @return bool success
    """
    assert msg.sender == self.future_admin  # dev: admin-only function

    new_admin: address = self.future_admin
    self.admin = new_admin

    log NewAdmin(admin=new_admin)

    return True


@external
def revert_transfer_ownership() -> bool:
    """
    @notice Revert a transfer of contract ownership
    @dev May only be called by the current owner
    @return bool success
    """
    assert msg.sender == self.admin  # dev: admin-only function
    self.future_admin = empty(address)

    return True
