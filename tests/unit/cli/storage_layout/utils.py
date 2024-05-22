from vyper.evm.opcodes import version_check


def adjust_storage_layout_for_cancun(layout):
    def _go(layout):
        for _varname, item in layout.items():
            if "slot" in item and isinstance(item["slot"], int):
                item["slot"] -= 1
            else:
                # recurse to submodule
                _go(item)

    if version_check(begin="cancun"):
        nonreentrant = layout["storage_layout"].pop("$.nonreentrant_key", None)
        if nonreentrant is not None:
            layout["transient_storage_layout"] = {"$.nonreentrant_key": nonreentrant}
        _go(layout["storage_layout"])
