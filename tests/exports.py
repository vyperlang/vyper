class TestExporter:
    def __init__(self, output_path):
        pass

    def set_testitem(self, item):
        self.testcases += 1

    def record_testitem(self, item):
        self.current_itemtrace = []

    def record_contract_call(calldata, output):
        self.current_itemtrace.append[(calldata, output)]
