"""
The run profiles start the task-wrapper containers with exactly the options
the legacy deploy-managers used (network, IPC, volumes, capabilities,
environment, ulimits, cpuset, tmpfs, ...), container name included.
"""

import unittest
from unittest import mock

import yaml

import support
from dsl import load
from dsl.convert import convert
from encoders.orchestration_grpc import BASE_PORT
from run_profiles import PROFILES
from runner import Runner


def legacy_runs(impl, path):
    leg = support.legacy(impl)
    manifest = leg.parser.ManifestParser(str(path)).parse()
    client = support.FakeDocker()
    with mock.patch("docker.from_env", return_value=client):
        runner = leg.runner.DockerContainerRunner()
    # as each legacy main.py: one container per declared image
    for n, img in enumerate(manifest.images.tasks):
        if impl == "orchestration-grpc":
            runner.run_task_service(image_tag=img.alias, container_name=f"task-service-{img.alias}",
                                    grpc_port=BASE_PORT + n)
        else:
            runner.run_task_service(image_tag=img.alias, container_name=img.alias)
    return client.containers.runs


def new_runs(impl, path):
    coordination, technology = support.IMPLEMENTATIONS[impl]
    with open(path) as f:
        manifest, _ = load(convert(yaml.safe_load(f), coordination, technology))
    client = support.FakeDocker()
    Runner(client).run_all(PROFILES[impl], manifest)
    return client.containers.runs


class RunProfilesMatchLegacy(unittest.TestCase):
    def test_same_container_options(self):
        for path in support.manifests():
            for impl in support.IMPLEMENTATIONS:
                with self.subTest(manifest=path.name, implementation=impl):
                    old, new = legacy_runs(impl, path), new_runs(impl, path)
                    self.assertTrue(old, "the legacy runner started no container")
                    self.assertEqual(len(old), len(new))
                    for o, n in zip(old, new):
                        self.assertEqual(o, n, f"containers.run() options of {o.get('name')}")

    def test_redis_host(self):
        # legacy main.py: grpc reaches Redis on the host network, the others by service name
        self.assertEqual(PROFILES["orchestration-grpc"].redis_host, "localhost")
        for impl in ("orchestration-mqueue", "choreography-mqueue", "choreography-zeromq"):
            self.assertEqual(PROFILES[impl].redis_host, "redis")


if __name__ == "__main__":
    unittest.main()
