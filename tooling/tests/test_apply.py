"""apply(): order of the steps, lock file checks, cleanup between applies."""

import unittest

import yaml

import support
import encoders
import state
from apply import ApplyError, apply
from dsl import load
from dsl.convert import convert
from runner import ROLE_LABEL

FIXTURE = support.TOOLING / "tests" / "fixtures" / "legacy_fifo_three_images.yaml"


def manifest_for(impl):
    coordination, technology = support.IMPLEMENTATIONS[impl]
    m, _ = load(convert(yaml.safe_load(FIXTURE.read_text()), coordination, technology))
    m.path = "/srv/rtmo/apps/test/manifest.yaml"
    return m


def lock_for(manifest, client, em=True):
    images = {img.name: client.images.get(img.name).id for img in manifest.images}
    em_tag = f"rtmo/execution-manager:{manifest.deployment.profile}"
    return {"images": images, "manifest_digest": "sha256:test",
            "execution_manager": {"image": em_tag, "id": client.images.get(em_tag).id} if em else None}


class Apply(unittest.TestCase):
    def setUp(self):
        self.docker, self.redis, self.events = support.FakeDocker(), support.FakeRedis(), []

    def apply(self, manifest, locked=None, ready=True):
        def wait_ready(path):
            self.events.append(("ready", path))
            return ready
        apply(manifest, self.docker, self.redis, locked, version="9.9.9", log=lambda m: None, wait_ready=wait_ready)

    def test_orchestration_grpc_order(self):
        m = manifest_for("orchestration-grpc")
        locked = lock_for(m, self.docker)
        self.apply(m, locked)
        runs = self.docker.containers.runs
        # one task service per image, by locked ID, then the execution manager last, by locked ID
        self.assertEqual([r["name"] for r in runs[:-1]], [f"task-service-{i.name}" for i in m.images])
        self.assertEqual([r["image"] for r in runs[:-1]], [locked["images"][i.name] for i in m.images])
        self.assertEqual((runs[-1]["name"], runs[-1]["image"]),
                         ("execution-manager-grpc", locked["execution_manager"]["id"]))
        self.assertEqual(runs[-1]["labels"][ROLE_LABEL], "execution-manager")
        # every service waited for, the plan written, the apply recorded, the lock released
        self.assertEqual([e[1] for e in self.events], [f"/ipc/task_{50051 + n}.sock" for n in range(len(m.images))])
        self.assertEqual(self.redis.data[encoders.PLAN_FORMAT_KEY], "orchestration-grpc/1")
        self.assertEqual(self.redis.data["schedule"]["length"], str(len(m.schedule.tasks)))
        applied = state.read(self.redis)
        self.assertEqual((applied["profile"], applied["status"], applied["rtmo_version"]),
                         ("orchestration-grpc", "running", "9.9.9"))
        self.assertNotIn(state.LOCK_KEY, self.redis.data)

    def test_choreography_zeromq_resets_volume_and_has_no_execution_manager(self):
        m = manifest_for("choreography-zeromq")
        self.apply(m, lock_for(m, self.docker, em=False))
        self.assertEqual(self.docker.volumes.events, [("remove", "zmq_ipc"), ("create", "zmq_ipc")])
        runs = self.docker.containers.runs
        self.assertEqual([r["name"] for r in runs], [i.name for i in m.images])
        self.assertTrue(all(r["network"] == "rtmo" for r in runs))
        self.assertEqual(self.events, [])                       # no readiness check
        self.assertIn("schedule_data", self.redis.data)

    def test_reapply_replaces_containers_and_plan(self):
        grpc = manifest_for("orchestration-grpc")
        self.apply(grpc, lock_for(grpc, self.docker))
        mq = manifest_for("choreography-mqueue")
        self.apply(mq, lock_for(mq, self.docker, em=False))
        alive = sorted(self.docker.containers.alive)
        self.assertEqual(alive, sorted(i.name for i in mq.images))          # grpc containers gone
        self.assertNotIn("schedule", self.redis.data)                         # grpc plan gone
        self.assertNotIn("scheduletask:1", self.redis.data)
        self.assertEqual(self.redis.data[encoders.PLAN_FORMAT_KEY], "choreography-mqueue/1")

    def test_changed_image_is_refused_before_anything_starts(self):
        m = manifest_for("orchestration-mqueue")
        locked = lock_for(m, self.docker)
        self.docker.images.ids[m.images[0].name] = "sha256:rebuilt"
        with self.assertRaises(ApplyError):
            self.apply(m, locked)
        self.assertEqual(self.docker.containers.runs, [])

    def test_busy_lock_is_refused(self):
        self.redis.set(state.LOCK_KEY, "someone else")
        with self.assertRaises(state.LockedError):
            self.apply(manifest_for("choreography-mqueue"))
        self.assertEqual(self.docker.containers.runs, [])

    def test_service_not_ready_stops_before_the_plan(self):
        m = manifest_for("orchestration-grpc")
        with self.assertRaises(ApplyError):
            self.apply(m, lock_for(m, self.docker), ready=False)
        self.assertNotIn("schedule", self.redis.data)
        self.assertNotIn(state.LOCK_KEY, self.redis.data)             # released on failure too

    def test_without_lock_images_run_by_tag(self):
        m = manifest_for("orchestration-mqueue")
        self.apply(m)
        runs = self.docker.containers.runs
        self.assertEqual([r["image"] for r in runs[:-1]], [i.name for i in m.images])
        self.assertEqual(runs[-1]["image"], "rtmo/execution-manager:orchestration-mqueue")


if __name__ == "__main__":
    unittest.main()
