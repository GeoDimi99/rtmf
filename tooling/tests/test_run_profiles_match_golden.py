"""
The run profiles start the task-wrapper containers with exactly the options
the legacy deploy-managers used (recorded in golden/<manifest>/<impl>.json):
network, IPC, volumes, capabilities, environment, ulimits, cpuset, tmpfs and
container name.
"""

import json
import unittest

import yaml

import support
from dsl import load
from dsl.convert import convert
from run_profiles import PROFILES
from runner import Runner


def golden_runs(path, impl):
    return json.loads((support.golden_dir(path) / f"{impl}.json").read_text())["containers"]


def new_runs(impl, path):
    coordination, technology = support.IMPLEMENTATIONS[impl]
    with open(path) as f:
        manifest, _ = load(convert(yaml.safe_load(f), coordination, technology))
    client = support.FakeDocker()
    Runner(client).run_all(PROFILES[impl], manifest)
    return json.loads(json.dumps(client.containers.runs, default=dict))


class RunProfilesMatchGolden(unittest.TestCase):
    def test_same_container_options(self):
        for path in support.manifests():
            for impl in support.IMPLEMENTATIONS:
                with self.subTest(manifest=path.name, implementation=impl):
                    old, new = golden_runs(path, impl), new_runs(impl, path)
                    self.assertTrue(old, "the golden file holds no container")
                    self.assertEqual(len(old), len(new))
                    for o, n in zip(old, new):
                        self.assertEqual(o, n, f"containers.run() options of {o.get('name')}")


if __name__ == "__main__":
    unittest.main()
