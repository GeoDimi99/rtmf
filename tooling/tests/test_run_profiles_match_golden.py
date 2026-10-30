"""
The run profiles start the task-wrapper containers with exactly the options
the legacy deploy-managers used (recorded in golden/<manifest>/<impl>.json):
network, IPC, volumes, capabilities, environment, ulimits, cpuset, tmpfs and
container name; and the execution managers with the settings of the former
compose files (golden/implementations.json).

Two intended differences: every container carries the rtmo.* labels rtmod uses
to find it, and the choreography wrappers join the device network 'rtmo'
(where Redis is 'redis') instead of their former compose network.
"""

import json
import unittest

import yaml

import support
from dsl import load
from dsl.convert import convert
from run_profiles import DEVICE_NETWORK, PROFILES
from runner import PROFILE_LABEL, ROLE_LABEL, Runner

IMPLEMENTATIONS = json.loads((support.TOOLING / "tests" / "golden" / "implementations.json").read_text())


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
                        self.assertEqual(n.pop("labels"), {ROLE_LABEL: "task", PROFILE_LABEL: impl})
                        if impl.startswith("choreography"):
                            self.assertEqual(n.pop("network"), DEVICE_NETWORK)
                            o.pop("network")
                        self.assertEqual(o, n, f"containers.run() options of {o.get('name')}")

    def test_execution_manager_as_the_former_compose_files(self):
        for impl, profile in PROFILES.items():
            with self.subTest(implementation=impl):
                old = IMPLEMENTATIONS[impl]["execution_manager"]
                if old is None:
                    self.assertIsNone(profile.execution_manager)
                    continue
                client = support.FakeDocker()
                Runner(client).run_execution_manager(profile, "em-image")
                new = json.loads(json.dumps(client.containers.runs[0], default=dict))
                self.assertEqual(new.pop("labels"), {ROLE_LABEL: "execution-manager", PROFILE_LABEL: impl})
                self.assertEqual((new.pop("image"), new.pop("detach")), ("em-image", True))
                if impl == "orchestration-mqueue":
                    # the compose network gave it 'redis'; the device network does now
                    self.assertEqual(new.pop("network"), DEVICE_NETWORK)
                self.assertEqual(old, new)


if __name__ == "__main__":
    unittest.main()
