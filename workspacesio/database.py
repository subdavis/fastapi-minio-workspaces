import posixpath

import databases
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

from .settings import settings
from .schemas import UserDB

database = databases.Database(settings.database_uri)
engine = create_engine(settings.database_uri)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()
