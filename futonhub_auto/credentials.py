from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from typing import Protocol

from .errors import AuthenticationError


class CredentialStore(Protocol):
    def read(self, target: str) -> str | None: ...
    def write(self, target: str, secret: str) -> None: ...
    def delete(self, target: str) -> None: ...


class MemoryCredentialStore:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def read(self, target: str) -> str | None:
        return self.values.get(target)

    def write(self, target: str, secret: str) -> None:
        self.values[target] = secret

    def delete(self, target: str) -> None:
        self.values.pop(target, None)


class FILETIME(ctypes.Structure):
    _fields_ = [
        ("dwLowDateTime", wintypes.DWORD),
        ("dwHighDateTime", wintypes.DWORD),
    ]


class CREDENTIALW(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", wintypes.LPVOID),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


PCREDENTIALW = ctypes.POINTER(CREDENTIALW)
CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2
ERROR_NOT_FOUND = 1168


class WindowsCredentialStore:
    def __init__(self) -> None:
        if os.name != "nt":
            raise AuthenticationError(
                "Windows Credential Manager solo está disponible en Windows"
            )
        self.advapi32 = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
        self.advapi32.CredWriteW.argtypes = [
            ctypes.POINTER(CREDENTIALW),
            wintypes.DWORD,
        ]
        self.advapi32.CredWriteW.restype = wintypes.BOOL
        self.advapi32.CredReadW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(PCREDENTIALW),
        ]
        self.advapi32.CredReadW.restype = wintypes.BOOL
        self.advapi32.CredDeleteW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
        ]
        self.advapi32.CredDeleteW.restype = wintypes.BOOL
        self.advapi32.CredFree.argtypes = [wintypes.LPVOID]

    def read(self, target: str) -> str | None:
        pointer = PCREDENTIALW()
        if not self.advapi32.CredReadW(
            target, CRED_TYPE_GENERIC, 0, ctypes.byref(pointer)
        ):
            error = ctypes.get_last_error()
            if error == ERROR_NOT_FOUND:
                return None
            raise AuthenticationError(
                f"No se pudo leer la credencial de Windows: {error}"
            )
        try:
            credential = pointer.contents
            if not credential.CredentialBlob or credential.CredentialBlobSize == 0:
                return ""
            raw = ctypes.string_at(
                credential.CredentialBlob, credential.CredentialBlobSize
            )
            return raw.decode("utf-16-le")
        finally:
            self.advapi32.CredFree(pointer)

    def write(self, target: str, secret: str) -> None:
        value = secret.strip()
        if not value:
            raise AuthenticationError("El token no puede estar vacío")
        raw = value.encode("utf-16-le")
        buffer = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
        credential = CREDENTIALW()
        credential.Type = CRED_TYPE_GENERIC
        credential.TargetName = target
        credential.CredentialBlobSize = len(raw)
        credential.CredentialBlob = ctypes.cast(
            buffer, ctypes.POINTER(ctypes.c_ubyte)
        )
        credential.Persist = CRED_PERSIST_LOCAL_MACHINE
        credential.UserName = "github-read-only"
        if not self.advapi32.CredWriteW(ctypes.byref(credential), 0):
            raise AuthenticationError(
                f"No se pudo guardar la credencial de Windows: "
                f"{ctypes.get_last_error()}"
            )

    def delete(self, target: str) -> None:
        if not self.advapi32.CredDeleteW(target, CRED_TYPE_GENERIC, 0):
            error = ctypes.get_last_error()
            if error != ERROR_NOT_FOUND:
                raise AuthenticationError(
                    f"No se pudo borrar la credencial de Windows: {error}"
                )
