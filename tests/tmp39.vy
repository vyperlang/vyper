
s_var: decimal

@external
def test(a: decimal) -> decimal:
    self.s_var = a + 1.0
    return sqrt(self.s_var)

@external
def test2() -> decimal:
    self.s_var = 444.44
    return sqrt(self.s_var)
