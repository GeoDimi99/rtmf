"""
The build profiles produce the task images the legacy image-builders produced:
same Dockerfile instructions, same base image as the implementation's start
script builds, same use of the Docker cache.
"""

import unittest
from string import Template

import support
from build import render_task_dockerfile
from build_profiles import PROFILES


def instructions(dockerfile: str):
    """Dockerfile lines that change the image (comments and blank lines dropped)."""
    return [line.strip() for line in dockerfile.splitlines() if line.strip() and not line.lstrip().startswith("#")]


class BuildProfilesMatchLegacy(unittest.TestCase):
    def test_task_dockerfile(self):
        for impl, profile in PROFILES.items():
            with self.subTest(implementation=impl):
                legacy = support.TOOLING / "legacy" / impl / "image-builder" / "src" / "builder" / "template" / "Dockerfile.j2"
                old = Template(legacy.read_text()).substitute(base_image=profile.base_image, source_dir="stress_task_1")
                new = render_task_dockerfile(profile, "stress_task_1")
                self.assertEqual(instructions(old), instructions(new))

    def test_base_image_and_cache_as_the_start_script(self):
        for impl, profile in PROFILES.items():
            with self.subTest(implementation=impl):
                script = (support.REPO / "tests" / "start-test" / f"{impl}.sh").read_text()
                self.assertIn(profile.base_image, script)
                self.assertIn(profile.base_dockerfile, script)
                self.assertEqual(profile.no_cache, "--no-cache" in script)

    def test_execution_manager_only_for_orchestration(self):
        for impl, profile in PROFILES.items():
            with self.subTest(implementation=impl):
                self.assertEqual(profile.needs_execution_manager, impl.startswith("orchestration"))
                if profile.needs_execution_manager:
                    self.assertTrue((support.REPO / profile.execution_manager_dockerfile).is_file())
                self.assertTrue((support.REPO / profile.base_dockerfile).is_file())


if __name__ == "__main__":
    unittest.main()
