"""Optional, public acceptance examples for your tasks, not a complete grading suite.

Run from the project folder:
    python -m unittest discover -s checks -p "exercise_*.py" -v
An unimplemented task is SKIPPED with its task ID. A skip does not mean a pass.
Once you replace its NotImplementedError, the relevant check starts checking it.
"""
import copy
import json
import logging
from pathlib import Path
import tempfile
import unittest

from analysis import explore_data, extended_summary, summarise_by_series
from calibration import calibrate_reading
from configuration import load_config, resolve_paths, validate_config
from logging_service import configure_logging
from processing import process_readings
from readers import read_csv, read_json, read_jsonl
from records import FIELDS
from storage import save_csv, save_jsonl

ROOT = Path(__file__).resolve().parents[1]


class TaskChecks(unittest.TestCase):
    """Read a check to see a concrete input and its expected behaviour."""

    def task(self, function, *args, **kwargs):
        """Leave unfinished exercises visible without claiming they already work."""
        try:
            return function(*args, **kwargs)
        except NotImplementedError as error:
            self.skipTest(str(error))

    def setUp(self):
        """Give each check fresh data and settings so checks cannot affect each other."""
        self.records = read_csv(ROOT / "data" / "readings.csv")
        self.config = json.loads((ROOT / "config" / "example.json").read_text())

    def test_R1_json_matches_csv(self):
        """Different serialisation must not change the measurements."""
        self.assertEqual(self.task(read_json, ROOT / "data" / "readings.json"), self.records)

    def test_R1_empty_and_wrong_container(self):
        """An empty array is valid; an object is not the agreed array format."""
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "input.json"
            path.write_text("[]", encoding="utf-8")
            self.assertEqual(self.task(read_json, path), [])
            path.write_text('{"readings": []}', encoding="utf-8")
            with self.assertRaises(ValueError):
                self.task(read_json, path)

    def test_R2_jsonl_matches_csv(self):
        """The line-based reader obeys the same record contract."""
        self.assertEqual(self.task(read_jsonl, ROOT / "data" / "readings.jsonl"), self.records)

    def test_R2_blank_lines_and_bad_line(self):
        """Skip blank lines; do not silently skip a damaged measurement."""
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "input.jsonl"
            path.write_text("\n" + json.dumps(self.records[0]) + "\n\n", encoding="utf-8")
            self.assertEqual(self.task(read_jsonl, path), self.records[:1])
            path.write_text(json.dumps(self.records[0]) + "\nnot JSON\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, r"[Ll]ine 2"):
                self.task(read_jsonl, path)

    def test_C1_new_record_and_formula(self):
        """Calibration changes only value and leaves the original record untouched."""
        reading = self.records[0]
        before = copy.deepcopy(reading)
        calibrated = self.task(calibrate_reading, reading, 2.0, -1.0)
        self.assertEqual(calibrated, {**reading, "value": 39.0})
        self.assertEqual(reading, before)
        self.assertIsNot(calibrated, reading)

    def test_E1_inventory(self):
        """The full file contains six series, not one mixed stream of comparable values."""
        before = copy.deepcopy(self.records)
        info = self.task(explore_data, list(reversed(self.records)))
        self.assertEqual(info["record_count"], 36)
        self.assertEqual(info["rooms"], ["laboratory", "office"])
        self.assertEqual(info["sensor_ids"], ["station-01", "station-02"])
        self.assertEqual(info["metrics"], ["humidity", "pressure", "temperature"])
        self.assertEqual(info["time_start"], "2026-10-01T12:00:00+00:00")
        self.assertEqual(info["time_end"], "2026-10-01T12:05:00+00:00")
        self.assertEqual(len(info["series"]), 6)
        self.assertEqual({s["count"] for s in info["series"]}, {6})
        self.assertEqual(info["series"], sorted(info["series"],
                         key=lambda s: (s["room"], s["sensor_id"], s["metric"])))
        self.assertEqual(self.records, before)

    def test_E1_empty_inventory(self):
        """An empty file has no start time, rooms or measurement series."""
        self.assertEqual(self.task(explore_data, []),
                         {"record_count": 0, "rooms": [], "sensor_ids": [], "metrics": [],
                          "time_start": None, "time_end": None, "series": []})

    def test_S1_statistics_and_small_samples(self):
        """Check sample, not population, standard deviation and both warm-up cases."""
        result = self.task(extended_summary, [20.0, 21.0, 22.0])
        self.assertEqual(result, {"count": 3, "mean": 21.0, "minimum": 20.0,
                                 "maximum": 22.0, "median": 21.0, "sample_sd": 1.0})
        self.assertIsNone(self.task(extended_summary, [20.0])["sample_sd"])
        empty = self.task(extended_summary, [])
        self.assertIsNone(empty["sample_sd"])
        self.assertIsNone(empty["median"])

    def test_S2_grouped_statistics(self):
        """A single output file may contain separate summaries, never a mixed-unit mean."""
        result = self.task(summarise_by_series, self.records)
        self.assertEqual(len(result), 6)
        lab = next(s for s in result if (s["room"], s["sensor_id"], s["metric"]) ==
                   ("laboratory", "station-01", "temperature"))
        self.assertAlmostEqual(lab["summary"]["mean"], 21.0)
        self.assertEqual(lab["unit"], "C")
        self.assertEqual(self.task(summarise_by_series, []), [])

    def test_W1_csv_round_trip(self):
        """Your CSV output must remain input to the same project."""
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "new" / "readings.csv"
            self.task(save_csv, path, self.records)
            self.assertEqual(read_csv(path), self.records)
            self.task(save_csv, path, [])
            self.assertEqual(read_csv(path), [])
            self.assertEqual(path.read_text(encoding="utf-8").splitlines(), [",".join(FIELDS)])

    def test_W2_jsonl_round_trip(self):
        """Replace a snapshot rather than appending duplicate old readings."""
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "new" / "readings.jsonl"
            self.task(save_jsonl, path, self.records)
            self.assertEqual([json.loads(line) for line in path.read_text().splitlines()],
                             self.records)
            self.task(save_jsonl, path, [])
            self.assertEqual(path.read_text(), "")

    def test_L1_append_log_without_duplicate_handlers(self):
        """Two setups produce two messages, not lost history or duplicated handlers."""
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "new" / "run.log"
            try:
                for message in ("first-marker", "second-marker"):
                    self.task(configure_logging, "INFO", path)
                    logging.getLogger("exercise").info(message)
                    logging.shutdown()
                text = path.read_text(encoding="utf-8")
                self.assertEqual(text.count("first-marker"), 1)
                self.assertEqual(text.count("second-marker"), 1)
            finally:
                # Close test-owned handlers before the temporary folder is removed.
                logging.shutdown()
                logging.basicConfig(handlers=[logging.NullHandler()], force=True)

    def test_X1_valid_config_unchanged(self):
        """Checking configuration is a pure operation; it must not rewrite your input."""
        before = copy.deepcopy(self.config)
        self.assertIsNone(self.task(validate_config, self.config))
        self.assertEqual(self.config, before)

    def test_X1_invalid_choices(self):
        """Reject typos and wrong value types before any output is opened."""
        self.task(validate_config, self.config)  # One skip if X1 is not started yet.
        changes = [("input", "format", "xml"), ("selection", "room", ""),
                   ("selection", "metric", "voltage"), ("calibration", "enabled", "false"),
                   ("calibration", "scale", True), ("calibration", "offset", float("nan")),
                   ("logging", "level", "INF0"), ("output", "summary_path", "")]
        for section, key, value in changes:
            with self.subTest(section=section, key=key):
                config = copy.deepcopy(self.config)
                config[section][key] = value
                with self.assertRaises(ValueError):
                    self.task(validate_config, config)

    def test_X1_missing_and_unknown_keys(self):
        """A misspelled field must not be silently ignored."""
        self.task(validate_config, self.config)  # One skip if X1 is not started yet.
        configs = [[], {**self.config, "unexpected": 1}]
        missing = copy.deepcopy(self.config)
        del missing["input"]["path"]
        configs.append(missing)
        for config in configs:
            with self.subTest(config=config), self.assertRaises(ValueError):
                self.task(validate_config, config)

    def test_X2_paths_and_original(self):
        """Resolve paths beside the config file, without changing the settings dictionary."""
        before = copy.deepcopy(self.config)
        base = ROOT / "config"
        result = self.task(resolve_paths, self.config, base)
        self.assertEqual(result["input"]["path"], (ROOT / "data" / "readings.csv").resolve())
        self.assertEqual(self.config, before)
        self.config["logging"]["path"] = None
        result = self.task(resolve_paths, self.config, base)
        self.assertIsNone(result["logging"]["path"])

    def test_X2_reject_path_collisions(self):
        """Prevent a simple filename mistake from overwriting raw data."""
        self.config["output"]["readings_path"] = self.config["input"]["path"]
        with self.assertRaises(ValueError):
            self.task(resolve_paths, self.config, ROOT / "config")

    def test_X2_load_config(self):
        """The supplied assembly should work as soon as X1 and X2 work."""
        result = self.task(load_config, ROOT / "config" / "example.json")
        self.assertEqual(result["selection"], self.config["selection"])
        self.assertTrue(result["input"]["path"].is_absolute())

    def test_X3_pure_pipeline(self):
        """Pass a one-use iterator; select first, calibrate once, then summarise."""
        before = copy.deepcopy(self.records)
        settings_before = copy.deepcopy(self.config)
        result = self.task(process_readings, iter(self.records), self.config["selection"],
                           self.config["calibration"])
        self.assertEqual(len(result["readings"]), 6)
        self.assertAlmostEqual(result["summary"]["mean"], 21.02)
        self.assertTrue(result["calibration_applied"])
        self.assertEqual(self.records, before)
        self.assertEqual(self.config, settings_before)

    def test_X3_disabled_and_empty(self):
        """Disabling calibration is explicit; an empty selection remains empty."""
        calibration = {"enabled": False, "scale": 100.0, "offset": 200.0}
        result = self.task(process_readings, iter(self.records), self.config["selection"], calibration)
        self.assertAlmostEqual(result["summary"]["mean"], 21.0)
        self.assertFalse(result["calibration_applied"])
        empty = self.task(process_readings, iter([]), self.config["selection"], calibration)
        self.assertEqual(empty["readings"], [])
        self.assertEqual(empty["summary"]["count"], 0)
        self.assertIsNone(empty["summary"]["mean"])


if __name__ == "__main__":
    unittest.main()
