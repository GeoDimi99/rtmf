"""Parser, validation rules and converter of the DSL."""

import copy
import unittest

import support  # noqa: F401  (sets sys.path)
from dsl import LegacyManifestError, ManifestError, InvalidManifestError, load, parse, parse_cpus, validate
from dsl.convert import convert, dump, format_cpus
import encoders

import yaml

GOOD = {
    "version": "0.1",
    "deployment": {"coordination": "choreography", "technology": "zeromq",
                   "control_cpu": 4, "task_cpus": "5-7"},
    "images": [{"name": "a", "src": "a"}, {"name": "b", "src": "b"}],
    "schedule": {
        "name": "s", "description": "d", "iterations": 3, "time_unit": "ms",
        "tasks": [
            {"id": 1, "image": "a", "start": 0, "deadline": 100, "cpu_affinity": 5, "policy": "fifo",
             "priority": 50, "depends_on": [], "inputs": {"n": {"type": "int", "value": 1}},
             "outputs": {"r": {"type": "int"}}},
            {"id": 2, "image": "b", "start": 10, "deadline": 200, "cpu_affinity": 6, "policy": "normal",
             "priority": -5, "depends_on": [1], "inputs": {}, "outputs": {}},
        ],
    },
}


def manifest(**changes):
    """GOOD with changes given as dotted paths: manifest(**{"schedule.tasks.0.start": 5})."""
    data = copy.deepcopy(GOOD)
    for path, value in changes.items():
        *parents, last = path.split(".")
        node = data
        for p in parents:
            node = node[int(p)] if isinstance(node, list) else node[p]
        if isinstance(node, list):
            node[int(last)] = value
        elif value is ...:
            del node[last]
        else:
            node[last] = value
    return data


def errors_of(data):
    return validate(parse(data))[0]


class Parse(unittest.TestCase):
    def test_good_manifest(self):
        m, warnings = load(GOOD)
        self.assertEqual(m.deployment.profile, "choreography-zeromq")
        self.assertEqual(m.deployment.task_cpus, [5, 6, 7])
        self.assertEqual(list(m.schedule.tasks[0].inputs), ["n"])
        self.assertEqual(warnings, [])

    def test_legacy_manifest_is_recognised(self):
        with self.assertRaises(LegacyManifestError):
            parse({"version": "1.0", "images": {}, "schedule": {}})

    def test_missing_and_mistyped_fields(self):
        for path, value in [("schedule.tasks.0.deadline", ...), ("deployment.control_cpu", "4"),
                            ("schedule.iterations", True), ("schedule.tasks.0.inputs", None),
                            ("deployment.task_cpus", "5-"), ("images.0", {"name": "a"})]:
            with self.subTest(path=path), self.assertRaises(ManifestError):
                parse(manifest(**{path: value}))

    def test_cpu_lists(self):
        self.assertEqual(parse_cpus("4,6-7", "x"), [4, 6, 7])
        self.assertEqual(parse_cpus(3, "x"), [3])
        self.assertEqual(format_cpus([7, 4, 5, 6]), "4-7")
        self.assertEqual(format_cpus([4, 6, 7]), "4,6-7")


class Validation(unittest.TestCase):
    def assertRejected(self, data, fragment):
        errs = errors_of(data)
        self.assertTrue(any(fragment in e for e in errs), f"no error containing {fragment!r} in {errs}")

    def test_rules(self):
        cases = [
            ({"version": "1.0"}, "not supported by this RTMO"),
            ({"deployment.technology": "grpc"}, "not supported (valid:"),
            ({"images.1": {"name": "a", "src": "x"}}, "used more than once"),
            ({"schedule.tasks.1.id": 1}, "id 1 is used more than once"),
            ({"schedule.tasks.0.id": 0}, "positive integer"),
            ({"schedule.tasks.0.image": "zzz"}, "not declared in images"),
            ({"schedule.tasks.0.start": 100}, "start < deadline"),
            ({"schedule.iterations": 0}, "at least 1"),
            ({"schedule.time_unit": "s"}, "time_unit"),
            ({"schedule.tasks.0.cpu_affinity": 3}, "not in task_cpus"),
            ({"schedule.tasks.0.policy": "deadline"}, "policy 'deadline'"),
            ({"schedule.tasks.0.priority": 0}, "outside 1..99"),
            ({"schedule.tasks.1.priority": 20}, "outside -20..19"),
            ({"schedule.tasks.0.inputs": {"n": {"type": "float", "value": 1.5}}}, "has type 'float'"),
            ({"schedule.tasks.0.inputs": {"n": {"type": "int", "value": "1"}}}, "is not of type int"),
            ({"schedule.tasks.1.depends_on": [9]}, "not a task id"),
            ({"schedule.tasks.0.depends_on": [2]}, "cycle"),
        ]
        for changes, fragment in cases:
            with self.subTest(changes=changes):
                self.assertRejected(manifest(**changes), fragment)

    def test_us_must_be_whole_ms(self):
        self.assertRejected(manifest(**{"schedule.time_unit": "us"}), "not a whole number of ms")
        ok = manifest(**{"schedule.time_unit": "us", "schedule.tasks.0.start": 0,
                         "schedule.tasks.0.deadline": 100000, "schedule.tasks.1.start": 10000,
                         "schedule.tasks.1.deadline": 200000})
        self.assertEqual(errors_of(ok), [])

    def test_control_cpu_among_task_cpus_is_a_warning(self):
        m, warnings = load(manifest(**{"deployment.task_cpus": "4-7"}))
        self.assertEqual(len(warnings), 1)

    def test_load_raises_with_every_error(self):
        with self.assertRaises(InvalidManifestError) as ctx:
            load(manifest(**{"schedule.iterations": 0, "schedule.tasks.0.priority": 0}))
        self.assertEqual(len(ctx.exception.errors), 2)


class Convert(unittest.TestCase):
    def test_fixtures_convert_and_validate_on_every_implementation(self):
        for path in support.manifests():
            legacy = yaml.safe_load(path.read_text())
            for impl, (coordination, technology) in support.IMPLEMENTATIONS.items():
                with self.subTest(manifest=path.name, implementation=impl):
                    data = yaml.safe_load(dump(convert(legacy, coordination, technology)))
                    m, _ = load(data)
                    self.assertEqual(m.deployment.profile, impl)
                    self.assertEqual(m.deployment.control_cpu, 4)
                    self.assertEqual(set(m.deployment.task_cpus),
                                     {t["cpu_affinity"] for t in legacy["schedule"]["tasks"]})

    def test_rejects_invalid_combination_and_new_manifests(self):
        legacy = yaml.safe_load(support.manifests()[0].read_text())
        with self.assertRaises(ValueError):
            convert(legacy, "choreography", "grpc")
        with self.assertRaises(ValueError):
            convert(GOOD, "choreography", "zeromq")


class Encoders(unittest.TestCase):
    def test_us_manifest_encodes_like_its_ms_twin(self):
        ms = load(GOOD)[0]
        us = load(manifest(**{"schedule.time_unit": "us", "schedule.tasks.0.start": 0,
                              "schedule.tasks.0.deadline": 100000, "schedule.tasks.1.start": 10000,
                              "schedule.tasks.1.deadline": 200000}))[0]
        for impl in support.IMPLEMENTATIONS:
            coordination, technology = support.IMPLEMENTATIONS[impl]
            for m in (ms, us):
                m.deployment.coordination, m.deployment.technology = coordination, technology
            with self.subTest(implementation=impl):
                self.assertEqual(encoders.encode(ms), encoders.encode(us))


if __name__ == "__main__":
    unittest.main()
