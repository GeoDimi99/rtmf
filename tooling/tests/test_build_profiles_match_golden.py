"""
The build profiles produce the task images the legacy tooling produced, as
recorded in golden/implementations.json: same Dockerfile instructions, same
base image and Dockerfile, same use of the Docker cache.
"""

import json
import unittest

import support
from build import render_task_dockerfile
from build_profiles import PROFILES

GOLDEN = json.loads((support.TOOLING / "tests" / "golden" / "implementations.json").read_text())


def instructions(dockerfile: str):
    """Dockerfile lines that change the image (comments and blank lines dropped)."""
    return [line.strip() for line in dockerfile.splitlines() if line.strip() and not line.lstrip().startswith("#")]


class BuildProfilesMatchGolden(unittest.TestCase):
    def test_every_implementation_has_a_profile(self):
        self.assertEqual(sorted(PROFILES), sorted(GOLDEN))

    def test_task_dockerfile(self):
        for impl, profile in PROFILES.items():
            with self.subTest(implementation=impl):
                self.assertEqual(GOLDEN[impl]["task_dockerfile"],
                                 instructions(render_task_dockerfile(profile, "stress_task_1")))

    def test_base_image_and_cache(self):
        for impl, profile in PROFILES.items():
            with self.subTest(implementation=impl):
                self.assertEqual(profile.base_image, GOLDEN[impl]["base_image"])
                self.assertEqual(profile.base_dockerfile, GOLDEN[impl]["base_dockerfile"])
                self.assertEqual(profile.no_cache, GOLDEN[impl]["no_cache"])
                self.assertTrue((support.REPO / profile.base_dockerfile).is_file())

    def test_execution_manager_only_for_orchestration(self):
        for impl, profile in PROFILES.items():
            with self.subTest(implementation=impl):
                self.assertEqual(profile.needs_execution_manager, GOLDEN[impl]["execution_manager"] is not None)
                if profile.needs_execution_manager:
                    self.assertTrue((support.REPO / profile.execution_manager_dockerfile).is_file())


if __name__ == "__main__":
    unittest.main()
