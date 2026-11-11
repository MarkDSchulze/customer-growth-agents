"""Explicit operator export; optional immutable S3 archive requires a configured AWS role."""

import argparse
import json
from pathlib import Path

import httpx

from growth.enterprise.archive import S3AuditArchive, verify

parser = argparse.ArgumentParser()
parser.add_argument("--api-url", default="http://localhost:8000")
parser.add_argument("--token-file", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--bucket")
parser.add_argument("--kms-key")
parser.add_argument("--account")
args = parser.parse_args()
with httpx.Client(
    base_url=args.api_url,
    headers={"Authorization": "Bearer " + args.token_file.read_text().strip()},
    timeout=30,
    follow_redirects=False,
) as client:
    tenant_response = client.get("/v2/tenant")
    tenant_response.raise_for_status()
    tenant = tenant_response.json()
    response = client.get("/v2/audit/export")
    response.raise_for_status()
records = [json.loads(line) for line in response.text.splitlines()]
verify(records)
args.output.write_text(response.text)
if args.bucket:
    import boto3

    archive = S3AuditArchive(
        args.bucket,
        args.kms_key or "",
        args.account or "",
        boto3.client("s3", region_name=tenant["region"]),
    )
    print(json.dumps(archive.write(tenant["tenantId"], tenant["region"], records)))
else:
    print("Verified audit export saved.")
