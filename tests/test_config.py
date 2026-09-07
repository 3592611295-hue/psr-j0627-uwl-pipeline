import unittest
from pathlib import Path

from j0627_uwl.config import ConfigError, load_config, validate_config


ROOT = Path(__file__).resolve().parents[1]


class ConfigTests(unittest.TestCase):
    def test_example_config_is_valid(self):
        config = load_config(ROOT / "configs" / "j0627_uwl.example.json")
        self.assertEqual(config["phase_windows"]["mp"], [465, 525])

    def test_overlap_is_rejected(self):
        config = load_config(ROOT / "configs" / "j0627_uwl.example.json")
        config.pop("_config_path", None)
        config["phase_windows"]["off_control"] = [500, 600]
        with self.assertRaises(ConfigError):
            validate_config(config)


if __name__ == "__main__":
    unittest.main()
