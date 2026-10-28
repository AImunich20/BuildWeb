"""Encryption of secrets stored in the database (site secrets, MySQL passwords, FTP passwords).

Values are stored as "enc:<Fernet token>" with a key derived from the app's secret_key (kept in config.json
in the data folder, outside the database). A copied database or a database backup alone does not reveal them.
Plain values written by older versions are still read and get encrypted the next time they are saved.
"""
import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings

PREFIX = "enc:"


def _fernet():
    key = hashlib.sha256(("buildweb-secrets:" + settings.SECRET_KEY).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt(value):
    if value in (None, "") or (isinstance(value, str) and value.startswith(PREFIX)):
        return value
    return PREFIX + _fernet().encrypt(str(value).encode()).decode()


def decrypt(value):
    if not isinstance(value, str) or not value.startswith(PREFIX):
        return value
    try:
        return _fernet().decrypt(value[len(PREFIX):].encode()).decode()
    except InvalidToken:
        return ""  # encrypted with another machine's key (e.g. a database copied without config.json)


def encrypt_dict(d):
    return {k: encrypt(v) for k, v in (d or {}).items()}


def decrypt_dict(d):
    return {k: decrypt(v) for k, v in (d or {}).items()}
