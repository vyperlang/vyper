from vyper.codegen.ir_node import IRnode


def build_gas_estimates(ir_runtime: IRnode) -> dict:
    gas_estimates: dict = {}

    external_sub = next((i for i in ir_runtime.args if i.value == "with"), None)
    if external_sub:
        for func_ir in external_sub.args[-1].args:
            if func_ir.func_name is not None:
                gas_estimates[func_ir.func_name] = func_ir.total_gas

    return gas_estimates


def expand_source_map(compressed_map: str) -> list:
    """
    Expand a compressed source map string.

    Arguments
    ---------
    compressed_map : str
        `sourceMap` as generated by the compiler, i.e. "1:1:0;;;;3::2;;;4;"

    Returns
    -------
    List
        Expanded source map as `[[start, length, jump, source id], .. ]`
    """
    source_map: list = [_expand_row(i) if i else None for i in compressed_map.split(";")[:-1]]

    for i, value in enumerate(source_map[1:], 1):
        if value is None:
            source_map[i] = source_map[i - 1][:3] + [None]
            continue
        for x in range(3):
            if source_map[i][x] is None:
                source_map[i][x] = source_map[i - 1][x]

    return source_map


def _expand_row(row):
    result = [None] * 4
    for i, value in enumerate(row.split(":")):
        if value:
            result[i] = value if i == 3 else int(value)
    return result
