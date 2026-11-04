"""Extra reference-solution checks, including complete command-line runs.

Read the small original checks first. These tests add unusual inputs, path safety,
non-mutation and integration checks. All output is isolated in temporary folders.
"""
import copy
import itertools
import json
import logging
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from analysis import explore_data, extended_summary, summarise_by_series
from calibration import calibrate_reading
from configuration import load_config, resolve_paths, validate_config
from logging_service import configure_logging
from processing import process_readings
from readers import read_csv, read_json, read_jsonl
from storage import save_csv, save_jsonl

ROOT = Path(__file__).resolve().parents[1]


def example_config():
    """Give each test a fresh configuration so changes never leak to another test."""
    return json.loads((ROOT / "config" / "example.json").read_text(encoding="utf-8"))


class ReaderAndAnalysisChecks(unittest.TestCase):
    """Exercise the common record boundary and pure scientific calculations."""

    def setUp(self):
        self.records = read_csv(ROOT / "data" / "readings.csv")

    def test_json_syntax_and_bad_item_have_context(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "readings.json"
            path.write_text('[{"value":', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, r"readings.json.*line 1"):
                read_json(path)
            path.write_text(json.dumps([self.records[0], {}]), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, r"readings.json.*item 2"):
                read_json(path)

    def test_json_rejects_all_non_array_containers(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "readings.json"
            for value in ({}, None, 1, True, "hello"):
                with self.subTest(value=value):
                    path.write_text(json.dumps(value), encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, "array"):
                        read_json(path)

    def test_jsonl_invalid_object_reports_physical_line(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "readings.jsonl"
            path.write_text("\n\n[]\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, r"readings.jsonl.*line 3"):
                read_jsonl(path)

    def test_missing_inputs_raise_instead_of_returning_empty_data(self):
        with tempfile.TemporaryDirectory() as directory:
            for reader in (read_csv, read_json, read_jsonl):
                with self.subTest(reader=reader.__name__), self.assertRaises(OSError):
                    reader(Path(directory) / "missing")

    def test_empty_jsonl_is_a_valid_empty_dataset(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "empty.jsonl"
            path.write_text(" \n\t\n", encoding="utf-8")
            self.assertEqual(read_jsonl(path), [])

    def test_identity_calibration_still_returns_a_new_record(self):
        original = self.records[0]
        result = calibrate_reading(original, 1.0, 0.0)
        self.assertEqual(result, original)
        self.assertIsNot(result, original)
        result["value"] = -999
        self.assertEqual(original["value"], 20.0)

    def test_nonfinite_calibration_result_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "non-finite"):
            calibrate_reading({**self.records[0], "value": 1e308}, 1e308, 0.0)

    def test_exploration_compares_instants_not_time_text(self):
        # These are aware timestamps but not in the canonical input UTC spelling.
        # Compare actual instants even for a direct caller supplying other offsets.
        early = {**self.records[0], "time": "2026-10-01T14:00:00+02:00"}
        late = {**self.records[0], "time": "2026-10-01T12:30:00+00:00"}
        result = explore_data([late, early])
        self.assertEqual(result["time_start"], early["time"])
        self.assertEqual(result["time_end"], late["time"])

    def test_even_median_and_sample_standard_deviation(self):
        values = [4.0, 1.0, 3.0, 2.0]
        before = values.copy()
        result = extended_summary(values)
        self.assertEqual(result["median"], 2.5)
        self.assertAlmostEqual(result["sample_sd"], (5.0 / 3.0) ** 0.5)
        self.assertEqual(values, before)

    def test_all_three_identity_parts_keep_groups_separate(self):
        record = self.records[0]
        readings = [record, {**record, "room": "office", "value": 10.0},
                    {**record, "sensor_id": "station-02", "value": 30.0},
                    {**record, "metric": "humidity", "unit": "%", "value": 50.0}]
        results = summarise_by_series(readings)
        self.assertEqual(len(results), 4)
        self.assertEqual(sorted(r["summary"]["mean"] for r in results), [10, 20, 30, 50])
        self.assertEqual([r["summary"]["count"] for r in results], [1, 1, 1, 1])

    def test_office_temperature_is_not_the_laboratory_average(self):
        summaries = summarise_by_series(self.records)
        office = next(r for r in summaries
                      if r["room"] == "office" and r["metric"] == "temperature")
        self.assertAlmostEqual(office["summary"]["mean"], 23.5)

    def test_grouping_rejects_inconsistent_units(self):
        rows = [self.records[0], {**self.records[0], "unit": "F"}]
        for function in (explore_data, summarise_by_series):
            with self.subTest(function=function.__name__), self.assertRaises(ValueError):
                function(rows)

    def test_analysis_and_processing_do_not_mutate_any_inputs(self):
        config = example_config()
        before = copy.deepcopy((self.records, config))
        explore_data(self.records)
        summarise_by_series(self.records)
        one = process_readings(self.records, config["selection"], config["calibration"])
        two = process_readings(self.records, config["selection"], config["calibration"])
        self.assertEqual(one, two)
        self.assertEqual((self.records, config), before)

    def test_pipeline_consumes_original_source_only_once(self):
        class OnePass:
            """Fail if a consumer tries to start the original iterable twice."""
            def __init__(self, records):
                self.records = records
                self.calls = 0

            def __iter__(self):
                self.calls += 1
                if self.calls > 1:
                    raise AssertionError("Source consumed twice")
                return iter(self.records)

        source = OnePass(self.records)
        config = example_config()
        result = process_readings(source, config["selection"], config["calibration"])
        self.assertEqual(source.calls, 1)
        self.assertAlmostEqual(result["summary"]["mean"], 21.02)

    def test_disabled_calibration_does_not_alias_raw_dictionaries(self):
        config = example_config()
        config["calibration"]["enabled"] = False
        result = process_readings(self.records, config["selection"], config["calibration"])
        self.assertEqual(result["readings"][0], self.records[0])
        self.assertIsNot(result["readings"][0], self.records[0])
        result["readings"][0]["value"] = -999
        self.assertEqual(self.records[0]["value"], 20.0)

    def test_empty_selection_keeps_requested_calibration_flag(self):
        config = example_config()
        config["selection"]["room"] = "missing"
        result = process_readings(self.records, config["selection"], config["calibration"])
        self.assertEqual(result["readings"], [])
        self.assertTrue(result["calibration_applied"])
        self.assertEqual(result["summary"]["count"], 0)
        self.assertTrue(all(value is None for key, value in result["summary"].items()
                            if key != "count"))


class StorageAndLoggingChecks(unittest.TestCase):
    """Ensure serialisation preserves data and logs retain earlier messages."""

    def test_both_record_writers_round_trip_calibrated_unicode_data(self):
        record = read_csv(ROOT / "data" / "tiny.csv")[0]
        rows = [calibrate_reading({**record, "room": 'Zażółć, "test"\nroom'}, 1.02, -0.4)]
        with tempfile.TemporaryDirectory() as directory:
            for name, writer, reader in (("x.csv", save_csv, read_csv),
                                         ("x.jsonl", save_jsonl, read_jsonl)):
                with self.subTest(name=name):
                    path = Path(directory) / "nested" / name
                    writer(path, rows)
                    writer(path, rows)  # Replacement must not double the data.
                    self.assertEqual(reader(path), rows)

    def test_bad_jsonl_value_does_not_truncate_old_snapshot(self):
        record = read_csv(ROOT / "data" / "tiny.csv")[0]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.jsonl"
            save_jsonl(path, [record])
            before = path.read_bytes()
            with self.assertRaises(ValueError):
                save_jsonl(path, [{**record, "value": float("nan")}])
            self.assertEqual(path.read_bytes(), before)

    def test_logging_reconfiguration_has_one_console_and_one_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run.log"
            try:
                configure_logging("INFO", path)
                logging.getLogger("check").info("Zażółć-one")
                configure_logging("INFO", path)
                logging.getLogger("check").info("Zażółć-two")
                logging.shutdown()
                text = path.read_text(encoding="utf-8")
                self.assertEqual(text.count("Zażółć-one"), 1)
                self.assertEqual(text.count("Zażółć-two"), 1)
                self.assertEqual(len(logging.getLogger().handlers), 2)
            finally:
                logging.basicConfig(handlers=[logging.NullHandler()], force=True)

    def test_invalid_log_levels_do_not_create_output(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "new" / "run.log"
            for level in ("info", "INF0", None, [], 0):
                with self.subTest(level=level), self.assertRaises(ValueError):
                    configure_logging(level, path)
            self.assertFalse(path.parent.exists())


class ConfigurationChecks(unittest.TestCase):
    """Check the exact schema and path-copy/collision rules from Extension 1."""

    def test_each_section_rejects_missing_and_unknown_keys(self):
        for section, values in example_config().items():
            for key in values:
                config = example_config()
                del config[section][key]
                with self.subTest(section=section, missing=key), self.assertRaises(ValueError):
                    validate_config(config)
            config = example_config()
            config[section]["misspelled_setting"] = 1
            with self.subTest(section=section), self.assertRaises(ValueError):
                validate_config(config)

    def test_each_section_must_be_an_object(self):
        for section in example_config():
            for replacement in (None, [], "text", 1):
                config = example_config()
                config[section] = replacement
                with self.subTest(section=section, value=replacement), self.assertRaises(ValueError):
                    validate_config(config)

    def test_no_implicit_numeric_or_boolean_conversion(self):
        cases = [("enabled", value) for value in ("false", 0, 1, None)]
        cases += [(key, value) for key in ("scale", "offset")
                  for value in (True, False, "1.0", None, float("inf"), -float("inf"),
                                float("nan"), 10 ** 1000)]
        for key, value in cases:
            config = example_config()
            config["calibration"][key] = value
            with self.subTest(key=key, value=value), self.assertRaisesRegex(ValueError, key):
                validate_config(config)

    def test_disabled_calibration_still_requires_valid_coefficients(self):
        config = example_config()
        config["calibration"].update(enabled=False, scale="not-a-number")
        with self.assertRaisesRegex(ValueError, "scale"):
            validate_config(config)

    def test_whitespace_only_text_and_non_text_paths_are_rejected(self):
        for section, key in (("input", "path"), ("selection", "room"),
                             ("selection", "sensor_id"), ("output", "readings_path"),
                             ("output", "summary_path"), ("logging", "path")):
            for value in (" \t ", 0, [], {}):
                config = example_config()
                config[section][key] = value
                with self.subTest(field=f"{section}.{key}", value=value), self.assertRaises(ValueError):
                    validate_config(config)

    def test_valid_strings_keep_their_spelling(self):
        config = example_config()
        config["input"]["path"] = "  data with spaces.csv  "
        config["selection"]["room"] = " laboratory "
        before = copy.deepcopy(config)
        validate_config(config)
        self.assertEqual(config, before)

    def test_exact_choices_reject_wrong_case_and_containers(self):
        for section, key, value in (("input", "format", "CSV"),
                                    ("selection", "metric", "Temperature"),
                                    ("logging", "level", "info"),
                                    ("input", "format", []),
                                    ("selection", "metric", {})):
            config = example_config()
            config[section][key] = value
            with self.subTest(field=f"{section}.{key}"), self.assertRaises(ValueError):
                validate_config(config)

    def test_paths_are_absolute_independent_copies_without_output_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory) / "config"
            config = example_config()
            before = copy.deepcopy(config)
            result = resolve_paths(config, base)
            self.assertEqual(result["input"]["path"], (base / "../data/readings.csv").resolve())
            result["selection"]["room"] = "changed"
            self.assertEqual(config, before)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_absolute_paths_and_null_logging(self):
        with tempfile.TemporaryDirectory() as directory:
            config = example_config()
            path = (Path(directory) / "readings.csv").resolve()
            config["input"]["path"] = str(path)
            config["logging"]["path"] = None
            result = resolve_paths(config, Path(directory) / "config")
            self.assertEqual(result["input"]["path"], path)
            self.assertIsNone(result["logging"]["path"])

    def test_all_six_pairs_of_destinations_are_checked(self):
        fields = [("input", "path"), ("output", "readings_path"),
                  ("output", "summary_path"), ("logging", "path")]
        with tempfile.TemporaryDirectory() as directory:
            for one, two in itertools.combinations(fields, 2):
                config = example_config()
                config[one[0]][one[1]] = "../shared"
                config[two[0]][two[1]] = "../unused/../shared"
                with self.subTest(one=one, two=two), self.assertRaisesRegex(ValueError, "collision"):
                    resolve_paths(config, Path(directory) / "config")

    def test_all_outputs_are_prevented_from_overwriting_config(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            for section, key in (("output", "readings_path"), ("output", "summary_path"),
                                 ("logging", "path")):
                config = example_config()
                config[section][key] = path.name
                text = json.dumps(config)
                path.write_text(text, encoding="utf-8")
                with self.subTest(field=f"{section}.{key}"), self.assertRaisesRegex(ValueError, "configuration"):
                    load_config(path)
                self.assertEqual(path.read_text(encoding="utf-8"), text)

    def test_bad_config_json_reports_filename(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"
            path.write_text("{invalid", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, r"bad.json.*line 1"):
                load_config(path)


class ApplicationChecks(unittest.TestCase):
    """Run the actual scripts, using disposable copies rather than your data folder."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.base = Path(self.directory.name)
        self.project = self.base / "project"
        self.project.mkdir()
        # Only runtime files are needed, keeping integration tests transparent.
        for path in ROOT.glob("*.py"):
            shutil.copy2(path, self.project / path.name)
        shutil.copytree(ROOT / "data", self.project / "data")
        shutil.copytree(ROOT / "config", self.project / "config")
        self.config_path = self.project / "config" / "example.json"

    def run_script(self, script="run.py", *args):
        # Deliberately start outside the project to test path anchoring.
        return subprocess.run([sys.executable, "-B", str(self.project / script), *args],
                              cwd=self.base, text=True, capture_output=True, timeout=15)

    def save_config(self, config):
        self.config_path.write_text(json.dumps(config), encoding="utf-8")

    def report(self):
        return json.loads((self.project / "output" / "summary.json").read_text(encoding="utf-8"))

    def test_default_run_from_another_directory(self):
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Calibrated summary:", result.stdout)
        report = self.report()
        rows = read_csv(self.project / "output" / "calibrated.csv")
        self.assertEqual(report["summary"]["count"], 6)
        self.assertAlmostEqual(report["summary"]["mean"], 21.02)
        self.assertEqual(extended_summary([r["value"] for r in rows]), report["summary"])
        self.assertEqual(report["raw_exploration"]["record_count"], 36)
        self.assertEqual(len(report["raw_series_summaries"]), 6)
        self.assertEqual(report["series"]["unit"], "C")
        self.assertTrue(report["calibration_applied"])
        self.assertFalse((self.base / "output").exists())

    def test_all_three_formats_produce_identical_calculations(self):
        summaries = []
        for file_format in ("csv", "json", "jsonl"):
            config = example_config()
            config["input"] = {"path": f"../data/readings.{file_format}", "format": file_format}
            self.save_config(config)
            result = self.run_script()
            self.assertEqual(result.returncode, 0, result.stderr)
            summaries.append(self.report()["summary"])
        self.assertEqual(summaries[0], summaries[1])
        self.assertEqual(summaries[0], summaries[2])

    def test_explicit_config_argument_is_relative_to_calling_directory(self):
        result = self.run_script("run.py", "project/config/example.json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertAlmostEqual(self.report()["summary"]["mean"], 21.02)

    def test_disabled_calibration_and_console_only_logging(self):
        config = example_config()
        config["calibration"]["enabled"] = False
        config["logging"]["path"] = None
        self.save_config(config)
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Uncalibrated summary:", result.stdout)
        self.assertFalse(self.report()["calibration_applied"])
        self.assertAlmostEqual(self.report()["summary"]["mean"], 21.0)
        self.assertFalse((self.project / "output" / "run.log").exists())

    def test_missing_selection_is_successfully_saved_as_empty(self):
        config = example_config()
        config["selection"]["room"] = "no-such-room"
        self.save_config(config)
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Selection is empty", result.stderr)
        self.assertEqual(self.report()["summary"]["count"], 0)
        self.assertIsNone(self.report()["summary"]["mean"])
        self.assertEqual(read_csv(self.project / "output" / "calibrated.csv"), [])

    def test_bad_config_has_nonzero_exit_and_no_outputs(self):
        config = example_config()
        config["input"]["format"] = "xml"
        self.save_config(config)
        result = self.run_script()
        self.assertEqual(result.returncode, 1)
        self.assertIn("input.format", result.stderr)
        self.assertFalse((self.project / "output").exists())

    def test_missing_input_and_invalid_measurement_fail_visibly(self):
        for name in ("missing.csv", "broken.csv"):
            config = example_config()
            config["input"]["path"] = "../data/" + name
            self.save_config(config)
            result = self.run_script()
            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertIn("Run stopped", result.stderr)
            self.assertFalse((self.project / "output" / "summary.json").exists())
            self.assertFalse((self.project / "output" / "calibrated.csv").exists())

    def test_collision_failure_keeps_raw_input_intact(self):
        input_path = self.project / "data" / "readings.csv"
        before = input_path.read_bytes()
        config = example_config()
        config["output"]["readings_path"] = config["input"]["path"]
        self.save_config(config)
        result = self.run_script()
        self.assertEqual(result.returncode, 1)
        self.assertIn("collision", result.stderr)
        self.assertEqual(input_path.read_bytes(), before)
        self.assertFalse((self.project / "output").exists())

    def test_successful_runs_preserve_input_and_append_log_once(self):
        before = {p.name: p.read_bytes() for p in (self.project / "data").iterdir()}
        for _ in range(2):
            result = self.run_script()
            self.assertEqual(result.returncode, 0, result.stderr)
        after = {p.name: p.read_bytes() for p in (self.project / "data").iterdir()}
        self.assertEqual(before, after)
        text = (self.project / "output" / "run.log").read_text(encoding="utf-8")
        self.assertEqual(text.count("Loaded configuration:"), 2)
        self.assertEqual(len(read_csv(self.project / "output" / "calibrated.csv")), 6)

    def test_finite_assignment_entry_point(self):
        result = self.run_script("run_finite.py")
        self.assertEqual(result.returncode, 0, result.stderr)
        folder = self.project / "output" / "finite"
        csv_rows = read_csv(folder / "calibrated.csv")
        self.assertEqual(csv_rows, read_jsonl(folder / "calibrated.jsonl"))
        report = json.loads((folder / "summary.json").read_text(encoding="utf-8"))
        self.assertAlmostEqual(report["summary"]["mean"], 21.02)
        self.assertEqual(report["raw_exploration"]["record_count"], 36)

    def test_importing_both_entry_points_does_not_create_outputs(self):
        code = "import sys; sys.path.insert(0, " + repr(str(self.project)) + "); import run, run_finite"
        result = subprocess.run([sys.executable, "-B", "-c", code], cwd=self.base,
                                text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "")
        self.assertFalse((self.project / "output").exists())

    def test_missing_config_and_extra_arguments_are_not_silently_ignored(self):
        result = self.run_script("run.py", "does-not-exist.json")
        self.assertEqual(result.returncode, 1)
        self.assertIn("Run stopped", result.stderr)
        result = self.run_script("run.py", "one.json", "two.json")
        self.assertEqual(result.returncode, 2)
        self.assertFalse((self.project / "output").exists())


if __name__ == "__main__":
    unittest.main()
