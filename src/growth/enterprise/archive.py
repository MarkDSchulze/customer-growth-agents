import base64
import hashlib
import json
from datetime import timedelta
from typing import Any

from growth.db import now
from growth.enterprise.storage import digest


def verify(records: list[dict[str, Any]]) -> str:
    previous = "0" * 64
    for sequence, record in enumerate(records, start=1):
        if record["sequence"] != sequence or record["previous_hash"] != previous:
            raise ValueError("AUDIT_CHAIN_GAP")
        computed = digest({key: value for key, value in record.items() if key != "record_hash"})
        if computed != record["record_hash"]:
            raise ValueError("AUDIT_CHAIN_TAMPERED")
        previous = computed
    return previous


class S3AuditArchive:
    def __init__(self, bucket: str, kms_key: str, account: str, client: Any):
        if (
            not bucket
            or not kms_key.startswith("arn:aws:kms:")
            or not account.isdigit()
            or len(account) != 12
        ):
            raise ValueError("ARCHIVE_CONFIGURATION_INVALID")
        self.bucket, self.kms_key, self.account, self.client = bucket, kms_key, account, client

    def write(self, tenant: str, region: str, records: list[dict[str, Any]]) -> dict[str, str]:
        last = verify(records)
        if any(r["tenant"] != tenant or r["region"] != region for r in records):
            raise ValueError("ARCHIVE_SCOPE_MISMATCH")
        payload = "".join(json.dumps(r, sort_keys=True) + "\n" for r in records).encode()
        checksum = base64.b64encode(hashlib.sha256(payload).digest()).decode()
        key = f"{region}/{tenant}/{len(records):012}-{last}.ndjson"
        # Executed only by the explicit archive command after the operator configures an AWS role.
        try:
            self.client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=payload,
                ContentType="application/x-ndjson",
                ServerSideEncryption="aws:kms",
                SSEKMSKeyId=self.kms_key,
                ExpectedBucketOwner=self.account,
                ObjectLockMode="COMPLIANCE",
                ObjectLockRetainUntilDate=now() + timedelta(days=365),
                ChecksumSHA256=checksum,
                Metadata={"sha256": hashlib.sha256(payload).hexdigest()},
                IfNoneMatch="*",
            )
        except Exception as error:
            response = getattr(error, "response", {})
            code = response.get("Error", {}).get("Code") if isinstance(response, dict) else None
            if code not in ("PreconditionFailed", "412"):
                raise
            existing = self.client.head_object(
                Bucket=self.bucket,
                Key=key,
                ExpectedBucketOwner=self.account,
                ChecksumMode="ENABLED",
            )
            if existing.get("ChecksumSHA256") != checksum:
                raise ValueError("ARCHIVE_CONFLICT") from None
        return {"uri": f"s3://{self.bucket}/{key}", "sha256": hashlib.sha256(payload).hexdigest()}
