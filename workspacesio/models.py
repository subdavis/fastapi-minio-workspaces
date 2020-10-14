import datetime
import enum
import uuid
import secrets
import bcrypt
from typing import Tuple

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Table,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.declarative import AbstractConcreteBase
from sqlalchemy.orm import relationship
from sqlalchemy.schema import UniqueConstraint

from .database import Base
from .schemas import RootType, ShareType

# Many to Many
# https://docs.sqlalchemy.org/en/13/orm/basic_relationships.html#many-to-many
workspace_s3token_association_table = Table(
    "workspace_s3token_association_table",
    Base.metadata,
    Column(
        "workspace_id", UUID(as_uuid=True), ForeignKey("workspace.id"), nullable=False
    ),
    Column(
        "s3token_id", UUID(as_uuid=True), ForeignKey("minio_token.id"), nullable=False
    ),
)

root_s3token_association_table = Table(
    "root_s3token_association_table",
    Base.metadata,
    Column(
        "root_id", UUID(as_uuid=True), ForeignKey("workspace_root.id"), nullable=False
    ),
    Column(
        "s3token_id", UUID(as_uuid=True), ForeignKey("minio_token.id"), nullable=False
    ),
)


class BaseModel(AbstractConcreteBase, Base):
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created = Column(DateTime, default=datetime.datetime.utcnow)


class User(BaseModel):
    __tablename__ = "user"
    __table_args__ = (
        UniqueConstraint("username"),
        UniqueConstraint("email"),
        UniqueConstraint("sub"),
    )

    sub = Column(String, nullable=False)
    username = Column(String, nullable=False)
    email = Column(String, nullable=False)

    tokens = relationship("Token", back_populates="user")
    workspaces = relationship("Workspace", back_populates="owner")
    created_nodes = relationship("StorageNode", back_populates="creator")


class ApiKey(BaseModel):
    """
    API Key for command line
    """

    __tablename__ = "token"

    key_id = Column(String, nullable=False, default=secrets.token_urlsafe)
    secret_hash = Column(String, nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("user.id"), nullable=False)

    user = relationship(User, back_populates="tokens")

    @classmethod
    def create(cls, user: User) -> Tuple[str, "ApiKey"]:
        key_db = cls(user_id=user.id)
        key_str = secrets.token_urlsafe(32)
        key_hash = bcrypt.hashpw(key_str.encode("utf-8"), bcrypt.gensalt())
        key_db.key_hash = key_hash
        return (
            key_str,
            key_db,
        )

    @classmethod
    def verify(cls, apikey: "ApiKey", key: str):
        return bcrypt.checkpw(key.encode("utf-8"), apikey.token_hash)


class StorageNode(BaseModel):
    """
    An S3 instance operated by some user
    """

    __tablename__ = "storage_node"
    __table_args__ = (UniqueConstraint("name"),)

    name = Column(String, nullable=False)
    # The API url that Workspaces Server can reference it as.
    api_url = Column(String, nullable=False)
    # An optional separate STS api url.
    sts_api_url = Column(String, nullable=True, default=None)
    creator_id = Column(UUID(as_uuid=True), ForeignKey("user.id"), nullable=False)
    access_key_id = Column(String, nullable=False)
    secret_access_key = Column(String, nullable=False)
    region_name = Column(String, nullable=False, default="us-east-1")
    # ARN used for STS assume role for temporary credentials
    # You DEFINITELY want this role to be empty (no permissions)
    assume_role_arn = Column(String, nullable=True, default=None)

    creator: User = relationship(User, back_populates="created_nodes")
    roots = relationship("WorkspaceRoot", back_populates="storage_node")


class WorkspaceRoot(BaseModel):
    """
    A bucket and optional prefix that defines a boundary of control for this application.

    :param root_type: str defines the naming convention and access pattern for workspaces in this root.
        `public` allows read access by default, and workspaces are structured `{username}/{workspace_name}`
        `private` allows only the creator, and has the same structure as `public`
        `unmanaged` is intended for mapping local directories into minio, and
    """

    __tablename__ = "workspace_root"
    __table_args__ = (UniqueConstraint("bucket", "base_path", "node_id"),)

    node_id = Column(UUID(as_uuid=True), ForeignKey("storage_node.id"), nullable=False)
    root_type = Column(Enum(RootType), nullable=False)
    bucket = Column(String, nullable=False)
    base_path = Column(String, default="", nullable=False)

    storage_node: StorageNode = relationship(StorageNode, back_populates="roots")
    workspaces = relationship("Workspace", back_populates="root")
    tokens = relationship(
        "S3Token", secondary=root_s3token_association_table, back_populates="roots"
    )
    indexes = relationship("RootIndex", back_populates="root")


class Workspace(BaseModel):
    """
    A workspace is a directory-like prefix in s3.

    READ/WRITE privileges to public and private workspaces
    can be shared among users.  Default privileges are based on
    the root.root_type
    """

    __tablename__ = "workspace"
    # workspace names are unique per user
    __table_args__ = (UniqueConstraint("name", "owner_id"),)

    name = Column(String, nullable=False)
    owner_id = Column(UUID(as_uuid=True), ForeignKey("user.id"), nullable=False)
    root_id = Column(
        UUID(as_uuid=True), ForeignKey("workspace_root.id"), nullable=False
    )
    # base_path set only if they live in an unmanaged root.
    base_path = Column(String, default=None, nullable=True)

    root = relationship(WorkspaceRoot, back_populates="workspaces")
    owner = relationship(User, back_populates="workspaces")
    tokens = relationship(
        "S3Token",
        secondary=workspace_s3token_association_table,
        back_populates="workspaces",
    )
    shares = relationship("Share", back_populates="workspace")


class Share(BaseModel):
    """
    A share is a mechanism for workspaces to be shared
    among users.  Both public and private workspaces may be
    shared with other entities.
    """

    __tablename__ = "share"
    __table_args__ = (UniqueConstraint("workspace_id", "creator_id", "sharee_id"),)

    workspace_id = Column(
        UUID(as_uuid=True), ForeignKey("workspace.id"), nullable=False
    )
    creator_id = Column(UUID(as_uuid=True), ForeignKey("user.id"), nullable=False)
    sharee_id = Column(UUID(as_uuid=True), ForeignKey("user.id"), nullable=False)
    permission = Column(Enum(ShareType), nullable=False)
    expiration = Column(DateTime, nullable=True)

    sharee: User = relationship(User, foreign_keys=sharee_id, backref="shares")
    creator: User = relationship(
        User, foreign_keys=creator_id, backref="shares_created"
    )
    workspace: Workspace = relationship(Workspace, back_populates="shares")


class S3Token(BaseModel):
    """
    There are two kinds of tokens that users might request

    * A general purpose token to use anything they own.

    * A specific workspace token for a single shared workspace.
      If a user needs concurrent access to many shared workspaces,
      they must have many outstanding tokens.
    """

    __tablename__ = "minio_token"

    access_key_id = Column(String, nullable=False)
    secret_access_key = Column(String, nullable=False)
    session_token = Column(String, nullable=False)
    expiration = Column(
        DateTime,
        default=datetime.datetime.now() + datetime.timedelta(days=7),
        nullable=False,
    )
    policy = Column(JSONB, nullable=False)
    owner_id = Column(UUID(as_uuid=True), ForeignKey("user.id"), nullable=False)
    storage_node_id = Column(
        UUID(as_uuid=True), ForeignKey("storage_node.id"), nullable=False
    )

    owner = relationship(User, backref="s3_tokens")
    workspaces = relationship(
        "Workspace",
        secondary=workspace_s3token_association_table,
        back_populates="tokens",
        cascade=["all"],
    )
    roots = relationship(
        "WorkspaceRoot",
        secondary=root_s3token_association_table,
        cascade=["all"],
        back_populates="tokens",
    )
