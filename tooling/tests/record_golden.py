"""
Records what the legacy tooling produces, so the tests can compare the new
code against it once tooling/legacy/ is gone (plan P4).

    python3 tooling/tests/record_golden.py

Writes, for every test manifest (support.manifests()) and implementation:
    golden/<manifest>/<impl>.json   {"redis": legacy Redis plan, "containers": legacy containers.run() options}
fixtures into tooling/tests/golden/, benchmark scenarios into benchmarks/golden/.
And once, from today's compose files, Dockerfile template and start scripts:
    tooling/tests/golden/implementations.json
"""

import json
import re
import sys
from string import Template

import yaml

from unittest import mock

import support
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



def golden_dir(manifest):
    return support.golden_dir(manifest)


def jsonable(value):
    return json.loads(json.dumps(value, default=dict))   # docker Ulimit objects are dicts


def execution_manager_from_compose(impl):
    """containers.run() options equivalent to the execution-manager service of the compose file."""
    compose = yaml.safe_load((support.REPO / "docker" / impl / "compose.yaml").read_text())
    svc = compose["services"].get("execution-manager")
    if svc is None:
        return None
    opts = {"name": svc["container_name"], "cpuset_cpus": str(svc["cpuset"]), "cap_add": svc["cap_add"]}
    if "ipc" in svc:
        opts["ipc_mode"] = svc["ipc"]
    if "network_mode" in svc:
        opts["network_mode"] = svc["network_mode"]
    if "volumes" in svc:
        opts["volumes"] = {v.split(":")[0]: {"bind": v.split(":")[1], "mode": "rw"} for v in svc["volumes"]}
    if "ulimits" in svc:
        ul = []
        for name, value in svc["ulimits"].items():
            soft, hard = (value, value) if isinstance(value, int) else (value["soft"], value["hard"])
            ul.append({"Name": name, "Soft": soft, "Hard": hard})
        opts["ulimits"] = ul
    return opts


def implementation_facts(impl):
    script = (support.REPO / "tests" / "start-test" / f"{impl}.sh").read_text()
    template = (support.TOOLING / "legacy" / impl / "image-builder" / "src" / "builder" / "template" / "Dockerfile.j2").read_text()
    base_image = re.search(r"rtmo/task-wrapper:[a-z-]+", script).group(0)
    dockerfile = Template(template).substitute(base_image=base_image, source_dir="stress_task_1")
    return {
        "base_image": base_image,
        "base_dockerfile": re.search(r"docker/[a-z-]+/task-wrapper\.Dockerfile", script).group(0),
        "no_cache": "--no-cache" in script,
        "task_dockerfile": [l.strip() for l in dockerfile.splitlines() if l.strip() and not l.lstrip().startswith("#")],
        "execution_manager": execution_manager_from_compose(impl),
    }


def main():
    written = 0
    for path in support.manifests():
        out = golden_dir(path)
        out.mkdir(parents=True, exist_ok=True)
        for impl in support.IMPLEMENTATIONS:
            data = {"redis": legacy_plan(impl, path), "containers": jsonable(legacy_runs(impl, path))}
            (out / f"{impl}.json").write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")
            written += 1
    facts = {impl: implementation_facts(impl) for impl in support.IMPLEMENTATIONS}
    (support.TOOLING / "tests" / "golden" / "implementations.json").write_text(
        json.dumps(facts, indent=1, sort_keys=True) + "\n")
    print(f"wrote {written} manifest goldens and implementations.json", file=sys.stderr)


if __name__ == "__main__":
    main()
