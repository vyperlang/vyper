#pragma version >0.3.10

registry: HashMap[Bytes[100], address]

@external
def register(name: Bytes[100], owner: address):
    assert self.registry[name] == empty(address)  # check name has not been set yet.
    self.registry[name] = owner


@view
@external
def lookup(name: Bytes[100]) -> address:
    return self.registry[name]
