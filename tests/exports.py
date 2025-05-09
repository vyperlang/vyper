import json
from pathlib import Path


class TestExporter:
    def __init__(self, output_file_path: Path, test_root: Path):
        self.output_file: Path = output_file_path
        # {"module_name": ["test_name_1", "test_name_2", ...]}
        self.data: dict[str, list[str]] = {}
        self.test_root: Path = test_root

    def set_item(self, item: 'pytest.Item'):
        module_file_path = Path(item.module.__file__).resolve()
        relative_module_path = module_file_path.relative_to(self.test_root)
        module_path = str(relative_module_path)
        test_name = item.name  # eg "test_abi_decode"

        if module_path not in self.data:
            self.data[module_path] = []

        if test_name not in self.data[module_path]:
            self.data[module_path].append(test_name)

    def finalize_export(self):
        if not self.data:
            print("No test data recorded.")
            return

        self.output_file.parent.mkdir(parents=True, exist_ok=True)

        with open(self.output_file, "w") as f:
            json.dump(self.data, f, indent=2)