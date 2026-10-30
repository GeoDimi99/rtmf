"""
The encoders write the Redis plan the legacy deploy-managers wrote (recorded
in golden/<manifest>/<impl>.json by record_golden.py), for every test manifest
on every implementation.

New side: dsl.convert -> dsl.load -> encoders.write.
Allowed differences: the new `plan:format` key, and `schedule:images`, whose
order the legacy loader took from a Python set (compared as a set; the new
encoder writes it sorted).
"""

import json
import unittest

import yaml

import support
from dsl import load
from dsl.convert import convert
import encoders


def golden(path, impl):
    return json.loads((support.golden_dir(path) / f"{impl}.json").read_text())


def new_plan(impl, path):
    coordination, technology = support.IMPLEMENTATIONS[impl]
    with open(path) as f:
        manifest, _ = load(convert(yaml.safe_load(f), coordination, technology))
    client = support.FakeRedis()
    encoders.write(client, manifest)
    return client.data


class EncodersMatchGolden(unittest.TestCase):
    def test_every_manifest_on_every_implementation(self):
        files = support.manifests()
        self.assertTrue(files)
        for path in files:
            for impl in support.IMPLEMENTATIONS:
                with self.subTest(manifest=path.name, implementation=impl):
                    old, new = golden(path, impl)["redis"], new_plan(impl, path)

                    self.assertEqual(new.pop(encoders.PLAN_FORMAT_KEY), f"{impl}/{encoders.PLAN_FORMAT_VERSION}")

                    if impl.startswith("choreography"):
                        old_images = json.loads(old["schedule_data"].pop("schedule:images"))
                        new_images = json.loads(new["schedule_data"].pop("schedule:images"))
                        self.assertEqual(sorted(old_images), new_images, "images: same set, written sorted")

                    self.assertEqual(sorted(old), sorted(new), "same Redis keys")
                    for key in old:
                        self.assertEqual(old[key], new[key], f"Redis key {key}")


if __name__ == "__main__":
    unittest.main()
