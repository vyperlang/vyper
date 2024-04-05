from vyper.evm.opcodes import version_check


def adjust_storage_layout_for_cancun(layout, do_adjust_slots=True):
    def _go(layout):
        for _varname, item in layout.items():
            if "slot" in item and isinstance(item["slot"], int):
                if do_adjust_slots:
                    item["slot"] -= 1
            else:
                # recurse to submodule
                _go(item)

    if version_check(begin="cancun"):
        nonreentrant = layout["storage_layout"].pop("$.nonreentrant_key", None)
        if nonreentrant is not None:
            layout["transient_storage_layout"] = {"$.nonreentrant_key": nonreentrant}
        _go(layout["storage_layout"])
