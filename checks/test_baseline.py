"""Optional checks for the worked examples. Run them after your first normal run.

From the project folder:
    python -m unittest discover -s checks -p "test_*.py" -v
These checks do not call unfinished student functions.
"""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from analysis import basic_summary, select_series
from calibration import calibrate_value
from readers import read_csv, read_data
from records import parse_record
from storage import save_json

ROOT = Path(__file__).resolve().parents[1]


class BaselineChecks(unittest.TestCase):
    """Each check asks one small question about the supplied working path."""

    def test_three_values(self):
        """The first dataset is small enough for you to inspect by hand."""
        records = read_csv(ROOT / "data" / "tiny.csv")
        self.assertEqual([r["value"] for r in records], [20.0, 21.0, 22.0])

    def test_basic_statistics(self):
        """Check the numbers that the first run displays."""
        self.assertEqual(basic_summary([20.0, 21.0, 22.0]),
                         {"count": 3, "mean": 21.0, "minimum": 20.0, "maximum": 22.0})

    def test_empty_selection(self):
        """Missing observations must not become invented zero measurements."""
        self.assertEqual(basic_summary([]),
                         {"count": 0, "mean": None, "minimum": None, "maximum": None})

    def test_series_selection(self):
        """Use the complete identity and consume a one-use iterator correctly."""
        records = read_csv(ROOT / "data" / "readings.csv")
        selected = select_series(iter(records), "laboratory", "station-01", "temperature")
        self.assertEqual(len(selected), 6)
        self.assertEqual({r["unit"] for r in selected}, {"C"})
        self.assertEqual(select_series(records, "office", "station-01", "temperature"), [])

    def test_calibration_formula(self):
        """The worked scalar example applies scale before adding offset."""
        self.assertAlmostEqual(calibrate_value(20.0, 1.02, -0.4), 20.0)
        self.assertAlmostEqual(calibrate_value(22.0, 1.02, -0.4), 22.04)

    def test_parser_does_not_mutate(self):
        """Parsing creates a fresh dictionary instead of changing the source row."""
        record = read_csv(ROOT / "data" / "tiny.csv")[0]
        raw = {**record, "value": "20.0", "time": "2026-10-01T14:00:00+02:00"}
        before = copy.deepcopy(raw)
        parsed = parse_record(raw)
        self.assertEqual(raw, before)
        self.assertEqual(parsed["time"], record["time"])
        self.assertIsInstance(parsed["value"], float)

    def test_invalid_values(self):
        """Reject absent, boolean and non-finite measurements at the input boundary."""
        record = read_csv(ROOT / "data" / "tiny.csv")[0]
        for value in (None, True, "NaN", float("inf"), "not-a-number"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_record({**record, "value": value})

    def test_invalid_time_and_units(self):
        """There is no implicit timezone or unit-conversion policy in this stage."""
        record = read_csv(ROOT / "data" / "tiny.csv")[0]
        for change in ({"time": "2026-10-01T12:00:00"}, {"unit": "F"}, {"room": ""}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                parse_record({**record, **change})

    def test_bad_csv_reports_line(self):
        """Fail-fast means the error identifies the first bad row, not every bad row."""
        with self.assertRaisesRegex(ValueError, "CSV line 3"):
            read_csv(ROOT / "data" / "broken.csv")

    def test_unknown_format(self):
        """An unsupported format is an error, not an empty dataset."""
        with self.assertRaises(ValueError):
            read_data(ROOT / "data" / "tiny.csv", "xml")

    def test_json_writer(self):
        """Save and reload a result; reject NaN without truncating an old snapshot."""
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "new" / "summary.json"
            expected = basic_summary([20.0, 21.0, 22.0])
            save_json(path, expected)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), expected)
            before = path.read_text(encoding="utf-8")
            with self.assertRaises(ValueError):
                save_json(path, {"mean": float("nan")})
            self.assertEqual(path.read_text(encoding="utf-8"), before)

    def test_imports_are_quiet(self):
        """Importing modules must not start a run or create files."""
        code = ("import sys; sys.path.insert(0, " + repr(str(ROOT)) + "); "
                "import run, readers, calibration, analysis, storage, logging_service; "
                "import configuration, processing")
        with tempfile.TemporaryDirectory() as folder:
            result = subprocess.run([sys.executable, "-B", "-c", code], cwd=folder,
                                    text=True, capture_output=True, check=True)
            self.assertEqual(result.stdout, "")
            self.assertEqual(result.stderr, "")
            self.assertEqual(list(Path(folder).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
