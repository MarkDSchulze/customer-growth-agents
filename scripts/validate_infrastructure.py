"""Assert deployable manifest security invariants, not production readiness."""

import argparse
from pathlib import Path

import yaml

parser = argparse.ArgumentParser()
parser.add_argument("manifest", type=Path)
args = parser.parse_args()
objects = list(yaml.safe_load_all(args.manifest.read_text()))
errors = []
for obj in objects:
    if not obj:
        continue
    kind = obj["kind"]
    if kind == "Deployment":
        spec = obj["spec"]["template"]["spec"]
        if not spec.get("securityContext", {}).get("runAsNonRoot"):
            errors.append("NON_ROOT_REQUIRED")
        if spec.get("automountServiceAccountToken") is not False:
            errors.append("DEFAULT_TOKEN_MOUNT_DENIED")
        if not spec.get("topologySpreadConstraints"):
            errors.append("AZ_DISTRIBUTION_REQUIRED")
        for container in spec["containers"]:
            security = container.get("securityContext", {})
            if (
                not security.get("readOnlyRootFilesystem")
                or security.get("allowPrivilegeEscalation") is not False
            ):
                errors.append("CONTAINER_SECURITY_REQUIRED")
            if "ALL" not in security.get("capabilities", {}).get("drop", []):
                errors.append("CAPABILITIES_MUST_BE_DROPPED")
            if container["image"].endswith(":latest"):
                errors.append("PINNED_IMAGE_REQUIRED")
    if kind == "NetworkPolicy":
        for rule in obj["spec"].get("egress", []):
            for destination in rule.get("to", []):
                if destination.get("ipBlock", {}).get("cidr") in ("0.0.0.0/0", "::/0"):
                    errors.append("UNRESTRICTED_EGRESS_DENIED")
if errors:
    raise SystemExit(", ".join(errors))
print("Rendered workload security and regional network invariants passed.")
