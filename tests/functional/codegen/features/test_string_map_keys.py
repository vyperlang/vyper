def test_string_map_keys(get_contract):
    code = """
f:HashMap[String[1], bool]
@external
def test() -> bool:
    a:String[1] = "a"
    b:String[1] = "b"
    self.f[a] = True
    return self.f[b]  # should return False
    """
    c = get_contract(code)
    c.test()
    assert c.test() is False


def test_string_map_keys_literals(get_contract):
    code = """
f:HashMap[String[1], bool]
@external
def test() -> bool:
    self.f["a"] = True
    return self.f["b"]  # should return False
    """
    c = get_contract(code)
    assert c.test() is False
