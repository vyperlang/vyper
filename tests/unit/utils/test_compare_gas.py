import importlib.util
import json
from pathlib import Path


def load_compare_gas():
    script_path = Path(__file__).parents[3] / ".github" / "scripts" / "compare_gas.py"
    spec = importlib.util.spec_from_file_location("compare_gas", script_path)
    compare_gas = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(compare_gas)
    return compare_gas


def write_gas_report(tmp_path, name, tests):
    path = tmp_path / name
    path.write_text(json.dumps({"tests": tests}))
    return path


def test_generate_report_puts_gas_deltas_before_test_names(tmp_path):
    compare_gas = load_compare_gas()
    long_test = "test_very_long_name_" * 8
    base_path = write_gas_report(
        tmp_path,
        "base.json",
        {
            long_test: {"gas": 100, "status": "Success"},
            "test_saves_gas": {"gas": 200, "status": "Success"},
            "test_unchanged": {"gas": 10, "status": "Success"},
        },
    )
    head_path = write_gas_report(
        tmp_path,
        "head.json",
        {
            long_test: {"gas": 125, "status": "Success"},
            "test_saves_gas": {"gas": 150, "status": "Success"},
            "test_unchanged": {"gas": 10, "status": "Success"},
        },
    )

    report = compare_gas.generate_report(base_path, head_path)

    assert "| Delta | Delta % | Base Gas | Head Gas | Test |" in report
    assert f"| 🔴+25 | +25.00% | **100** | **125** | {long_test} |" in report
    assert "| 🟢-50 | -25.00% | **200** | **150** | test_saves_gas |" in report


def test_generate_report_keeps_status_rows_in_compact_column_order(tmp_path):
    compare_gas = load_compare_gas()
    base_path = write_gas_report(
        tmp_path,
        "base.json",
        {
            "test_deleted": {"gas": 100, "status": "Success"},
            "test_broke": {"gas": 50, "status": "Success"},
            "test_fixed": {"gas": None, "status": "Failure"},
        },
    )
    head_path = write_gas_report(
        tmp_path,
        "head.json",
        {
            "test_new": {"gas": 10, "status": "Success"},
            "test_new_failing": {"gas": None, "status": "Failure"},
            "test_broke": {"gas": None, "status": "Failure"},
            "test_fixed": {"gas": 40, "status": "Success"},
        },
    )

    report = compare_gas.generate_report(base_path, head_path)

    assert "| deleted | - | **100** | - | test_deleted |" in report
    assert "| failing (Failure) | - | **50** | 💥 | test_broke |" in report
    assert "| fixed | - | ❌ | 🔧 **40** | test_fixed |" in report
    assert "| new | - | - | ➕ **10** | test_new |" in report
    assert "| new failing (Failure) | - | - | 💥 | test_new_failing |" in report
