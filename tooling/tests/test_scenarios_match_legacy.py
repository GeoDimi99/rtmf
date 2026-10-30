"""
Each benchmark scenario (benchmarks/scenarios/<s>.yaml, schema 0.1) is the
conversion of its legacy version (benchmarks/golden/<s>/legacy.yaml), so the
golden files recorded from the legacy version still describe it.

Allowed differences: the deployment section (overridden by every campaign run)
and the image sources, which point to the shared task folder.
Runs on the benchmarks branch; there is nothing to check on the framework branch.
"""

import unittest

import yaml

import support
from dsl.convert import convert


class ScenariosMatchLegacy(unittest.TestCase):
    def test_every_scenario_is_its_legacy_version_converted(self):
        legacy_files = sorted((support.REPO / "benchmarks" / "golden").glob("*/legacy.yaml"))
        if not legacy_files:
            self.skipTest("no benchmark scenarios on this branch")
        scenarios = support.REPO / "benchmarks" / "scenarios"
        self.assertEqual(sorted(p.parent.name for p in legacy_files), sorted(p.stem for p in scenarios.glob("*.yaml")))
        for legacy_path in legacy_files:
            name = legacy_path.parent.name
            with self.subTest(scenario=name):
                scenario = yaml.safe_load((scenarios / f"{name}.yaml").read_text())
                expected = convert(yaml.safe_load(legacy_path.read_text()),
                                   scenario["deployment"]["coordination"], scenario["deployment"]["technology"])
                for img in expected["images"]:
                    img["src"] = f"../tasks/{img['src']}"
                expected["deployment"] = scenario["deployment"]
                self.assertEqual(scenario, expected)


if __name__ == "__main__":
    unittest.main()
