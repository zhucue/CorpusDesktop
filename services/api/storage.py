"""Server-only S3 access; uploads are create-only and reads pin a version."""

import os
from functools import lru_cache

import boto3
from botocore.config import Config


@lru_cache
def client():
    return boto3.client(
        "s3", endpoint_url=os.environ["S3_ENDPOINT_URL"],
        aws_access_key_id=os.environ["S3_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["S3_SECRET_ACCESS_KEY"],
        region_name="us-east-1",
        config=Config(connect_timeout=5, read_timeout=30, retries={"total_max_attempts": 1},
                      s3={"addressing_style": "path"}, signature_version="s3v4"),
    )


def bucket():
    return os.environ.get("S3_BUCKET", "corpus-private")


def put_private(key, stream, size, media_type):
    response = client().put_object(
        Bucket=bucket(), Key=key, Body=stream, ContentLength=size,
        ContentType=media_type, IfNoneMatch="*",
    )
    version = response.get("VersionId")
    if not version or version == "null":
        raise ValueError("STORAGE_VERSIONING_REQUIRED")
    return version, response["ETag"]


def read_private(key, version, etag):
    return client().get_object(Bucket=bucket(), Key=key, VersionId=version, IfMatch=etag)["Body"]
