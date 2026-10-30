"""rtmo validate (overrides, --print) and the manifest lock file."""

import contextlib
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path

import yaml

import support
from dsl import lock
from dsl.convert import convert, dump

# Both tooling/builder and tooling/deploy-manager have a main.py: load rtmo's by path.
_spec = importlib.util.spec_from_file_location("rtmo_main", support.TOOLING / "builder" / "main.py")
rtmo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rtmo)

FIXTURE = support.TOOLING / "tests" / "fixtures" / "legacy_fifo_three_images.yaml"


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = rtmo.main(list(argv))
        except SystemExit as e:
            code = e.code
    return code, out.getvalue(), err.getvalue()


class RtmoCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.manifest = Path(self.tmp.name) / "scenario.yaml"
        self.manifest.write_text(dump(convert(yaml.safe_load(FIXTURE.read_text()), "orchestration", "mqueue")))

    def tearDown(self):
        self.tmp.cleanup()

    def test_validate_and_print_profile_with_overrides(self):
        code, out, _ = run("validate", str(self.manifest), "--print", "profile")
        self.assertEqual((code, out), (0, "orchestration-mqueue\n"))
        code, out, _ = run("validate", str(self.manifest), "--print", "profile",
                           "--coordination", "choreography", "--technology", "zeromq")
        self.assertEqual((code, out), (0, "choreography-zeromq\n"))

    def test_print_manifest_applies_iterations(self):
        code, out, _ = run("validate", str(self.manifest), "--print", "manifest", "--iterations", "21")
        self.assertEqual(code, 0)
        self.assertEqual(yaml.safe_load(out)["schedule"]["iterations"], 21)

    def test_invalid_override_is_reported(self):
        code, _, err = run("validate", str(self.manifest), "--technology", "zeromq")
        self.assertEqual(code, 1)
        self.assertIn("orchestration/zeromq is not supported", err)

    def test_legacy_manifest_points_to_the_converter(self):
        code, _, err = run("validate", str(FIXTURE))
        self.assertEqual(code, 1)
        self.assertIn("dsl.convert", err)

    def test_lock_roundtrip_and_stale_manifest(self):
        path = lock.write(str(self.manifest), "orchestration-mqueue", "0.1.0", {"img_a": "sha256:1"},
                          {"image": "rtmo/execution-manager:orchestration-mqueue", "id": "sha256:2"})
        self.assertEqual(path, self.manifest.parent / ".rtmo" / "scenario.orchestration-mqueue.lock.json")
        self.assertEqual(lock.read(str(self.manifest), "orchestration-mqueue")["images"], {"img_a": "sha256:1"})
        with self.assertRaises(lock.LockError):
            lock.read(str(self.manifest), "choreography-mqueue")          # not built for this one
        self.manifest.write_text(self.manifest.read_text() + "\n# edited\n")
        with self.assertRaises(lock.LockError):
            lock.read(str(self.manifest), "orchestration-mqueue")         # manifest changed since the build


if __name__ == "__main__":
    unittest.main()
