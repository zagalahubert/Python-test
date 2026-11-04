"""Load one JSON configuration without introducing a configuration framework.

Validation is pure. Path resolution creates no files. load_config owns the one
configuration-file read; numerical functions receive their settings as arguments.
"""
from copy import deepcopy
import json
from math import isfinite
from pathlib import Path

from logging_service import LEVELS
from records import UNITS

# This is the small schema from Extension 1, not a plugin registry or manifest.
SECTION_KEYS = {
    "input": {"path", "format"},
    "selection": {"room", "sensor_id", "metric"},
    "calibration": {"enabled", "scale", "offset"},
    "output": {"readings_path", "summary_path"},
    "logging": {"level", "path"},
}


def _check_keys(value: dict, expected: set, label: str) -> None:
    """Reject non-objects, missing keys and misspelled/unknown keys."""
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object/dictionary.")
    missing = expected - value.keys()
    unknown = value.keys() - expected
    if missing or unknown:
        raise ValueError(f"{label}: missing keys {sorted(missing, key=str)}; "
                         f"unknown keys {sorted(unknown, key=str)}.")


def _require_text(value, label: str) -> None:
    """Check text without stripping or otherwise rewriting an accepted value."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be non-empty text.")


def validate_config(config: dict) -> None:
    """SOLUTION X1: check the complete raw schema without changing it or doing I/O."""
    _check_keys(config, set(SECTION_KEYS), "config")
    for section, keys in SECTION_KEYS.items():
        _check_keys(config[section], keys, section)

    # General text fields keep the spelling the user supplied, including spaces.
    for section, key in (("input", "path"), ("selection", "room"),
                         ("selection", "sensor_id"), ("output", "readings_path"),
                         ("output", "summary_path")):
        _require_text(config[section][key], f"{section}.{key}")

    # Choice fields deliberately require an exact match, not fuzzy correction.
    for section, key, choices in (("input", "format", {"csv", "json", "jsonl"}),
                                   ("selection", "metric", set(UNITS)),
                                   ("logging", "level", LEVELS)):
        value = config[section][key]
        if not isinstance(value, str) or value not in choices:
            raise ValueError(f"{section}.{key} must be one of {sorted(choices)}.")

    if not isinstance(config["calibration"]["enabled"], bool):
        raise ValueError("calibration.enabled must be a boolean (true or false).")
    for key in ("scale", "offset"):
        value = config["calibration"][key]
        # bool is an int subclass, so reject it before accepting numerical types.
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"calibration.{key} must be a finite number.")
        try:
            finite = isfinite(value)
        except OverflowError:
            finite = False  # An enormous integer is unusable in our float pipeline.
        if not finite:
            raise ValueError(f"calibration.{key} must be a finite number.")

    if config["logging"]["path"] is not None:
        _require_text(config["logging"]["path"], "logging.path")
    # Reaching the end returns None. No defaults or type coercions were applied.


def resolve_paths(config: dict, base_dir: Path) -> dict:
    """SOLUTION X2: copy validated settings and resolve paths beside the config file."""
    result = deepcopy(config)  # A top-level copy would still share nested sections.
    base_dir = Path(base_dir).resolve()
    seen = {}
    for section, key in (("input", "path"), ("output", "readings_path"),
                         ("output", "summary_path"), ("logging", "path")):
        value = config[section][key]
        if value is None:  # Only logging.path may be null after validation.
            continue
        # Path's / joins components; an absolute right-hand path stays absolute.
        resolved = (base_dir / value).resolve()
        label = f"{section}.{key}"
        if resolved in seen:
            raise ValueError(f"Path collision: {label} and {seen[resolved]} both use {resolved}.")
        seen[resolved] = label
        result[section][key] = resolved
    # resolve() may inspect symlinks; it does not create or write these files.
    return result


def load_config(path: Path) -> dict:
    """Read once, validate, resolve, and protect the configuration file itself."""
    path = Path(path).resolve()
    with path.open(encoding="utf-8") as stream:
        try:
            config = json.load(stream)
        except json.JSONDecodeError as error:
            raise ValueError(f"{path}: JSON line {error.lineno}: {error.msg}") from error
    validate_config(config)
    result = resolve_paths(config, path.parent)
    targets = [result["output"]["readings_path"], result["output"]["summary_path"],
               result["logging"]["path"]]
    if path in targets:
        raise ValueError("An output/log path must not overwrite the configuration file.")
    return result
