"""
FastAPI endpoint dependencies
"""
import hashlib
import posixpath
import urllib.parse
from typing import Union

import boto3
import minio
from botocore.client import Config
from elasticsearch import Elasticsearch

from . import database, dbutils, models, schemas, settings


class Boto3ClientCache:
    """
    There may be many s3 nodes in the cluser.  Once a client has been established,
    cache it for future use.  This class works for sts and s3 type clients.
    """

    def __init__(self):
        self.cache: Dict[str, boto3.Session] = {}

    @staticmethod
    def _get_primary_key(
        client_type: str, node: Union[models.StorageNode, schemas.StorageNodeOperator]
    ) -> str:
        if not client_type in ["s3", "sts"]:
            raise ValueError(f"{client_type} unsupported by cache")
        primary_key = (
            (
                f"{client_type}{node.region_name}{node.api_url}"
                f"{node.access_key_id}{node.secret_access_key}"
            )
            .lower()
            .encode("utf-8")
        )
        return hashlib.sha256(primary_key).hexdigest()

    def get_client(
        self,
        client_type: str,
        node: Union[models.StorageNode, schemas.StorageNodeOperator],
    ) -> boto3.Session:
        primary_key_short_sha256 = Boto3ClientCache._get_primary_key(client_type, node)
        client = self.cache.get(primary_key_short_sha256, None)
        if client is None:
            config = Config()
            if client_type == "s3":
                config = Config(signature_version="s3v4")
                client = boto3.client(
                    client_type,
                    region_name=node.region_name,
                    endpoint_url=node.api_url,
                    aws_access_key_id=node.access_key_id,
                    aws_secret_access_key=node.secret_access_key,
                    config=config,
                )
            elif client_type == "sts":
                is_aws = node.assume_role_arn is not None
                api_url = node.api_url
                if node.sts_api_url:
                    api_url = node.sts_api_url
                elif is_aws:
                    api_url = f"https://sts.{node.region_name}.amazonaws.com"
                client = boto3.client(
                    client_type,
                    region_name=node.region_name,
                    endpoint_url=api_url,
                    aws_access_key_id=node.access_key_id,
                    aws_secret_access_key=node.secret_access_key,
                )
            else:
                raise NotImplementedError("Client type not implemented")
            self.cache[primary_key_short_sha256] = client
        return client

    def get_minio_sdk_client(
        self, node: Union[models.StorageNode, schemas.StorageNodeOperator]
    ) -> minio.Minio:
        primary_key_short_sha256 = (
            Boto3ClientCache._get_primary_key("s3", node) + "minio"
        )
        client = self.cache.get(primary_key_short_sha256, None)
        url = urllib.parse.urlparse(node.api_url)
        if client is None:
            client = minio.Minio(
                url.netloc,
                access_key=node.access_key_id,
                secret_key=node.secret_access_key,
                secure=False,
            )
            self.cache[primary_key_short_sha256] = client
        return client


def get_db():
    db = database.SessionLocal(query_cls=dbutils.Query)
    try:
        yield db
    finally:
        db.close()


def get_boto():
    yield Boto3ClientCache()


def get_elastic_client():
    client = Elasticsearch(settings.ES_NODES)
    try:
        yield client
    finally:
        client.close()
