import json
import tempfile
import unittest
from pathlib import Path

from j0627_uwl.psrchive import CommandRunner, make_subbands, make_total_intensity


class CommandPlanTests(unittest.TestCase):
    def test_all_frequency_products_explicitly_dedisperse(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runner = CommandRunner(root / "commands.jsonl", dry_run=True)
            zap = root / "sample.zap"
            make_total_intensity(runner, zap, root / "I")
            _, subband_command = make_subbands(runner, zap, root / "I4D", 4)
            self.assertIn("-D", subband_command)
            self.assertNotIn("-T", subband_command)
            records = [
                json.loads(line)
                for line in (root / "commands.jsonl").read_text().splitlines()
            ]
            pam_commands = [
                record["command"] for record in records if record["command"][0] == "pam"
            ]
            self.assertTrue(pam_commands)
            self.assertTrue(all("-D" in command for command in pam_commands))
            self.assertTrue(all("-T" not in command for command in pam_commands))


if __name__ == "__main__":
    unittest.main()
