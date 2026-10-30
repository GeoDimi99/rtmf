"""
The new encoders write the same Redis plan as the legacy deploy-managers, for
every test manifest on every implementation.

Legacy side: the legacy parser and RedisLoader of the implementation.
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
from encoders.orchestration_grpc import BASE_PORT


def legacy_plan(impl, path):
    leg = support.legacy(impl)
    manifest = leg.parser.ManifestParser(str(path)).parse()
    loader = leg.loader.RedisLoader()
    if impl == "orchestration-grpc":
        # as the legacy main.py: one port per declared image, in order
        ports = {img.alias: BASE_PORT + n for n, img in enumerate(manifest.images.tasks)}
        loader.load_schedule(manifest.schedule, image_to_port=ports)
    else:
        loader.load_schedule(manifest.schedule)
    return loader.client.data


def new_plan(impl, path):
    coordination, technology = support.IMPLEMENTATIONS[impl]
    with open(path) as f:
        manifest, _ = load(convert(yaml.safe_load(f), coordination, technology))
    client = support.FakeRedis()
    encoders.write(client, manifest)
    return client.data


class EncodersMatchLegacy(unittest.TestCase):
    def test_every_manifest_on_every_implementation(self):
        files = support.manifests()
        self.assertTrue(files)
        for path in files:
            for impl in support.IMPLEMENTATIONS:
                with self.subTest(manifest=path.name, implementation=impl):
                    old, new = legacy_plan(impl, path), new_plan(impl, path)

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
