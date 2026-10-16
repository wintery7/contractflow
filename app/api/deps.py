from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.storage.file_storage import FileStorage, LocalFileStorage

SettingsDep = Annotated[Settings, Depends(get_settings)]
DbSession = Annotated[Session, Depends(get_db)]


def get_storage(settings: SettingsDep) -> FileStorage:
    return LocalFileStorage(settings.storage_dir)


StorageDep = Annotated[FileStorage, Depends(get_storage)]
