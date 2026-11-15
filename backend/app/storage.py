from __future__ import annotations

import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Protocol
from uuid import uuid4

import boto3
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError, PartialCredentialsError
from flask import current_app
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename


class UploadValidationError(ValueError):
    pass


class StorageUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class StoredUpload:
    key: str
    mime_type: str
    size: int


class StorageBackend(Protocol):
    def store(
        self, stream: BinaryIO, key: str, mime_type: str, size: int
    ) -> None: ...

    def local_path(self, key: str) -> Path | None: ...

    def presigned_url(
        self, key: str, as_attachment: bool = False, download_name: str | None = None
    ) -> str | None: ...

    def delete(self, key: str) -> None: ...


_UPLOADS = {
    "poster": {
        ".jpg": ("image/jpeg", lambda header: header.startswith(b"\xff\xd8\xff")),
        ".jpeg": ("image/jpeg", lambda header: header.startswith(b"\xff\xd8\xff")),
        ".png": ("image/png", lambda header: header.startswith(b"\x89PNG\r\n\x1a\n")),
        ".webp": (
            "image/webp",
            lambda header: header.startswith(b"RIFF") and header[8:12] == b"WEBP",
        ),
    },
    "video": {
        ".mp4": ("video/mp4", lambda header: len(header) >= 12 and header[4:8] == b"ftyp"),
        ".webm": ("video/webm", lambda header: header.startswith(b"\x1a\x45\xdf\xa3")),
    },
    "trailer": {
        ".mp4": ("video/mp4", lambda header: len(header) >= 12 and header[4:8] == b"ftyp"),
        ".webm": ("video/webm", lambda header: header.startswith(b"\x1a\x45\xdf\xa3")),
    },
}
_ALLOWED_KEY_PREFIXES = {"posters", "trailers", "videos"}


class LocalStorage:
    def __init__(self) -> None:
        self.root = Path(current_app.config["MEDIA_STORAGE_PATH"]).expanduser().resolve()

    def store(self, stream: BinaryIO, key: str, _mime_type: str, _size: int) -> None:
        destination = self._destination(key)
        if destination is None:
            raise StorageUnavailable("The generated local storage key is invalid.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as temporary:
                temporary_path = temporary.name
                shutil.copyfileobj(stream, temporary)
            os.replace(temporary_path, destination)
        finally:
            if temporary_path and os.path.exists(temporary_path):
                os.unlink(temporary_path)

    def local_path(self, key: str) -> Path | None:
        path = self._destination(key)
        if path is None or not path.is_file():
            return None
        return path

    def _destination(self, key: str) -> Path | None:
        if not _is_safe_key(key):
            return None
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root):
            return None
        return path

    def presigned_url(
        self, _key: str, _as_attachment: bool = False, _download_name: str | None = None
    ) -> str | None:
        return None

    def delete(self, key: str) -> None:
        path = self.local_path(key)
        if path:
            path.unlink(missing_ok=True)


class S3Storage:
    def __init__(self) -> None:
        self.bucket = current_app.config.get("S3_BUCKET")
        if not self.bucket:
            raise StorageUnavailable("Configure S3_BUCKET before selecting S3 storage.")
        self.client = boto3.client(
            "s3",
            region_name=current_app.config.get("S3_REGION") or None,
            endpoint_url=current_app.config.get("S3_ENDPOINT_URL") or None,
        )

    def store(self, stream: BinaryIO, key: str, mime_type: str, _size: int) -> None:
        if not _is_safe_key(key):
            raise StorageUnavailable("The generated object-storage key is invalid.")
        stream.seek(0)
        try:
            self.client.upload_fileobj(
                stream,
                self.bucket,
                key,
                ExtraArgs={"ContentType": mime_type},
            )
        except (NoCredentialsError, PartialCredentialsError) as error:
            raise StorageUnavailable(
                "Object storage credentials are not configured."
            ) from error
        except (BotoCoreError, ClientError) as error:
            current_app.logger.error("Object-storage upload failed: %s", _error_code(error))
            raise StorageUnavailable("Object storage upload failed.") from error

    def local_path(self, _key: str) -> Path | None:
        return None

    def presigned_url(
        self, key: str, as_attachment: bool = False, download_name: str | None = None
    ) -> str:
        if not _is_safe_key(key):
            raise StorageUnavailable("The stored object key is invalid.")
        params = {"Bucket": self.bucket, "Key": key}
        if as_attachment and download_name:
            params["ResponseContentDisposition"] = (
                f'attachment; filename="{secure_filename(download_name) or "movie"}"'
            )
        try:
            return self.client.generate_presigned_url(
                "get_object", Params=params, ExpiresIn=60
            )
        except (NoCredentialsError, PartialCredentialsError) as error:
            raise StorageUnavailable(
                "Object storage credentials are not configured."
            ) from error
        except (BotoCoreError, ClientError) as error:
            current_app.logger.error("Object-storage URL signing failed: %s", _error_code(error))
            raise StorageUnavailable("Object storage could not authorize this file.") from error

    def delete(self, key: str) -> None:
        if not _is_safe_key(key):
            raise StorageUnavailable("The stored object key is invalid.")
        try:
            self.client.delete_object(Bucket=self.bucket, Key=key)
        except (NoCredentialsError, PartialCredentialsError) as error:
            raise StorageUnavailable(
                "Object storage credentials are not configured."
            ) from error
        except (BotoCoreError, ClientError) as error:
            current_app.logger.error("Object-storage deletion failed: %s", _error_code(error))
            raise StorageUnavailable("Object storage could not remove the file.") from error


def _error_code(error: BotoCoreError | ClientError) -> str:
    if isinstance(error, ClientError):
        return str(error.response.get("Error", {}).get("Code", "unknown"))
    return type(error).__name__


def _is_safe_key(key: str) -> bool:
    path = PurePosixPath(key)
    if path.is_absolute() or len(path.parts) != 2 or path.parts[0] not in _ALLOWED_KEY_PREFIXES:
        return False
    if path.as_posix() != key or "\\" in key:
        return False
    return bool(
        re.fullmatch(
            r"(?:posters|trailers|videos)/[0-9a-f]{32}\.(?:jpg|jpeg|png|webp|mp4|webm)",
            key,
        )
    )


def _storage_backend() -> StorageBackend:
    backend = current_app.extensions.get("cinezone_storage_backend")
    if backend is None:
        backend_name = current_app.config["STORAGE_BACKEND"]
        if backend_name == "local":
            backend = LocalStorage()
        elif backend_name == "s3":
            backend = S3Storage()
        else:
            raise StorageUnavailable("STORAGE_BACKEND must be 'local' or 's3'.")
        current_app.extensions["cinezone_storage_backend"] = backend
    return backend


def save_upload(upload: FileStorage, kind: str) -> StoredUpload:
    if kind not in _UPLOADS:
        raise ValueError(f"Unsupported upload category: {kind}")
    if not upload.filename:
        raise UploadValidationError("Choose a file to upload.")

    original_name = secure_filename(upload.filename)
    extension = Path(original_name).suffix.lower()
    accepted = _UPLOADS[kind].get(extension)
    if accepted is None:
        raise UploadValidationError(f"Unsupported {kind} file extension.")
    mime_type, signature_check = accepted
    if upload.mimetype.lower() != mime_type:
        raise UploadValidationError(f"The {kind} file MIME type does not match its extension.")

    stream = upload.stream
    stream.seek(0, os.SEEK_END)
    size = stream.tell()
    stream.seek(0)
    max_size = (
        current_app.config["MAX_POSTER_UPLOAD_BYTES"]
        if kind == "poster"
        else current_app.config["MAX_VIDEO_UPLOAD_BYTES"]
        if kind == "video"
        else current_app.config["MAX_TRAILER_UPLOAD_BYTES"]
    )
    if size <= 0 or size > max_size:
        raise UploadValidationError(f"The {kind} file exceeds the allowed size.")
    header = stream.read(16)
    stream.seek(0)
    if not signature_check(header):
        raise UploadValidationError(f"The {kind} file contents do not match its declared type.")

    key = f"{kind}s/{uuid4().hex}{extension}"
    _storage_backend().store(stream, key, mime_type, size)
    return StoredUpload(key=key, mime_type=mime_type, size=size)


def storage_local_path(key: str | None) -> Path | None:
    if not key:
        return None
    return _storage_backend().local_path(key)


def storage_has_key(key: str | None) -> bool:
    if not key:
        return False
    if current_app.config["STORAGE_BACKEND"] == "s3":
        return bool(current_app.config.get("S3_BUCKET")) and _is_safe_key(key)
    backend = _storage_backend()
    return backend.local_path(key) is not None


def storage_url(
    key: str,
    as_attachment: bool = False,
    download_name: str | None = None,
) -> str | None:
    return _storage_backend().presigned_url(key, as_attachment, download_name)


def delete_storage_key(key: str | None) -> None:
    if key:
        _storage_backend().delete(key)
