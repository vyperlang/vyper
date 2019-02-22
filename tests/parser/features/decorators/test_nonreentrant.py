

def test_nonrentrant_decorator(get_contract, assert_tx_failed):
    calling_contract_code = """
contract SpecialContract:
    def unprotected_function(val: string[100], do_callback: bool): modifying
    def protected_function(val: string[100], do_callback: bool): modifying
    def special_value() -> string[100]: modifying

@public
def updated():
    SpecialContract(msg.sender).unprotected_function('surprise!', False)

@public
def updated_protected():
    SpecialContract(msg.sender).protected_function('surprise protected!', False)  # This should fail.  # noqa: E501
    """

    reentrant_code = """
contract Callback:
    def updated(): modifying
    def updated_protected(): modifying

special_value: public(string[100])
callback: public(address(Callback))

@public
def set_callback(c: address):
    self.callback = c

@public
@nonreentrant('protect_special_value')
def protected_function(val: string[100], do_callback: bool):
    self.special_value = val

    if do_callback:
        self.callback.updated_protected()

@public
def unprotected_function(val: string[100], do_callback: bool):
    self.special_value = val

    if do_callback:
        self.callback.updated()
    """

    reentrant_contract = get_contract(reentrant_code)
    calling_contract = get_contract(calling_contract_code)

    reentrant_contract.set_callback(calling_contract.address, transact={})
    assert reentrant_contract.callback() == calling_contract.address

    # Test unprotected function.
    reentrant_contract.unprotected_function('some value', True, transact={})
    assert reentrant_contract.special_value() == 'surprise!'

    # Test protected function.
    reentrant_contract.protected_function('some value', False, transact={})
    assert reentrant_contract.special_value() == 'some value'

    assert_tx_failed(lambda: reentrant_contract.protected_function('zzz value', True, transact={}))
