"""Narrow macOS Keychain secret-storage boundary."""

from __future__ import annotations

import ctypes
import subprocess
from dataclasses import dataclass, field
from functools import cache
from typing import Protocol

ERR_SEC_DUPLICATE_ITEM = -25299
ERR_SEC_ITEM_NOT_FOUND = -25300
ERR_SEC_SUCCESS = 0


class KeychainError(RuntimeError):
    """Raised when macOS Keychain cannot complete a safe operation."""


class KeychainSecretNotFound(KeychainError):
    """Raised when an expected Keychain item is missing."""


@dataclass(frozen=True, slots=True)
class KeychainSecretReference:
    """Non-secret lookup identity safe to persist in SQLite."""

    service: str
    account: str

    def __post_init__(self) -> None:
        if not self.service.strip() or not self.account.strip():
            raise ValueError("Keychain service and account must not be empty")

    @property
    def identifier(self) -> str:
        """Return a non-secret stable lookup reference."""

        return f"{self.service}/{self.account}"


@dataclass(frozen=True, slots=True)
class SecurityCommandResult:
    """Minimal subprocess result that never includes stderr."""

    returncode: int
    stdout: str = field(default="", repr=False)


class SecurityCommandRunner(Protocol):
    """Injectable runner used to test Keychain behavior without live secrets."""

    def __call__(
        self,
        arguments: tuple[str, ...],
        *,
        input_text: str | None,
        capture_output: bool,
    ) -> SecurityCommandResult:
        """Run `/usr/bin/security` without a shell."""


def _run_security(
    arguments: tuple[str, ...],
    *,
    input_text: str | None,
    capture_output: bool,
) -> SecurityCommandResult:
    completed = subprocess.run(  # noqa: S603 - fixed security executable
        ("/usr/bin/security", *arguments),
        check=False,
        input=input_text,
        text=True,
        stdout=subprocess.PIPE if capture_output else subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return SecurityCommandResult(
        returncode=completed.returncode,
        stdout=completed.stdout if capture_output else "",
    )


@dataclass(frozen=True, slots=True)
class MacOSKeychain:
    """Store and retrieve secrets without placing values in command arguments."""

    command_runner: SecurityCommandRunner | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    def store(self, reference: KeychainSecretReference, secret: str) -> None:
        """Create or update one Keychain item using a prompted stdin value."""

        if not secret:
            raise ValueError("Keychain secret must not be empty")
        if self.command_runner is None:
            _native_store(reference, secret)
            return
        result = self.command_runner(
            (
                "add-generic-password",
                "-U",
                "-a",
                reference.account,
                "-s",
                reference.service,
                "-l",
                reference.identifier,
                "-w",
            ),
            input_text=f"{secret}\n",
            capture_output=False,
        )
        if result.returncode != 0:
            raise KeychainError("macOS Keychain rejected a secret update")

    def read(self, reference: KeychainSecretReference) -> str:
        """Read one secret into memory without emitting it."""

        if self.command_runner is None:
            return _native_read(reference)
        result = self.command_runner(
            (
                "find-generic-password",
                "-a",
                reference.account,
                "-s",
                reference.service,
                "-w",
            ),
            input_text=None,
            capture_output=True,
        )
        if result.returncode != 0:
            raise KeychainSecretNotFound("required macOS Keychain item is missing")
        secret = result.stdout.rstrip("\r\n")
        if not secret:
            raise KeychainSecretNotFound("required macOS Keychain item is empty")
        return secret

    def exists(self, reference: KeychainSecretReference) -> bool:
        """Check item presence without reading its value."""

        if self.command_runner is None:
            return _native_exists(reference)
        result = self.command_runner(
            (
                "find-generic-password",
                "-a",
                reference.account,
                "-s",
                reference.service,
            ),
            input_text=None,
            capture_output=False,
        )
        return result.returncode == 0

    def delete(self, reference: KeychainSecretReference) -> bool:
        """Delete one exact Keychain item."""

        if self.command_runner is None:
            return _native_delete(reference)
        result = self.command_runner(
            (
                "delete-generic-password",
                "-a",
                reference.account,
                "-s",
                reference.service,
            ),
            input_text=None,
            capture_output=False,
        )
        return result.returncode == 0


class _NativeSecurityAPI:
    """Typed subset of the macOS Security and CoreFoundation frameworks."""

    def __init__(self) -> None:
        security = ctypes.CDLL("/System/Library/Frameworks/Security.framework/Security")
        core_foundation = ctypes.CDLL(
            "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
        )

        security.SecKeychainFindGenericPassword.argtypes = (
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_char_p,
            ctypes.c_uint32,
            ctypes.c_char_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
        )
        security.SecKeychainFindGenericPassword.restype = ctypes.c_int32
        security.SecKeychainAddGenericPassword.argtypes = (
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_char_p,
            ctypes.c_uint32,
            ctypes.c_char_p,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
        )
        security.SecKeychainAddGenericPassword.restype = ctypes.c_int32
        security.SecKeychainItemModifyAttributesAndData.argtypes = (
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_void_p,
        )
        security.SecKeychainItemModifyAttributesAndData.restype = ctypes.c_int32
        security.SecKeychainItemDelete.argtypes = (ctypes.c_void_p,)
        security.SecKeychainItemDelete.restype = ctypes.c_int32
        security.SecKeychainItemFreeContent.argtypes = (
            ctypes.c_void_p,
            ctypes.c_void_p,
        )
        security.SecKeychainItemFreeContent.restype = ctypes.c_int32
        core_foundation.CFRelease.argtypes = (ctypes.c_void_p,)
        core_foundation.CFRelease.restype = None

        self.security = security
        self.core_foundation = core_foundation


@cache
def _native_api() -> _NativeSecurityAPI:
    return _NativeSecurityAPI()


def _native_store(reference: KeychainSecretReference, secret: str) -> None:
    api = _native_api()
    service = reference.service.encode()
    account = reference.account.encode()
    item = ctypes.c_void_p()
    status = api.security.SecKeychainFindGenericPassword(
        None,
        len(service),
        service,
        len(account),
        account,
        None,
        None,
        ctypes.byref(item),
    )

    secret_bytes = bytearray(secret.encode())
    secret_buffer = (ctypes.c_ubyte * len(secret_bytes)).from_buffer(secret_bytes)
    secret_pointer = ctypes.cast(secret_buffer, ctypes.c_void_p)
    try:
        if status == ERR_SEC_SUCCESS:
            update_status = api.security.SecKeychainItemModifyAttributesAndData(
                item,
                None,
                len(secret_bytes),
                secret_pointer,
            )
            if update_status != ERR_SEC_SUCCESS:
                raise KeychainError("macOS Keychain rejected a secret update")
            return
        if status != ERR_SEC_ITEM_NOT_FOUND:
            raise KeychainError("macOS Keychain could not inspect a secret item")

        add_status = api.security.SecKeychainAddGenericPassword(
            None,
            len(service),
            service,
            len(account),
            account,
            len(secret_bytes),
            secret_pointer,
            ctypes.byref(item),
        )
        if add_status == ERR_SEC_DUPLICATE_ITEM:
            _native_store(reference, secret)
            return
        if add_status != ERR_SEC_SUCCESS:
            raise KeychainError("macOS Keychain rejected a secret update")
    finally:
        secret_bytes[:] = b"\x00" * len(secret_bytes)
        _release_item(api, item)


def _native_read(reference: KeychainSecretReference) -> str:
    api = _native_api()
    service = reference.service.encode()
    account = reference.account.encode()
    password_length = ctypes.c_uint32()
    password_data = ctypes.c_void_p()
    item = ctypes.c_void_p()
    status = api.security.SecKeychainFindGenericPassword(
        None,
        len(service),
        service,
        len(account),
        account,
        ctypes.byref(password_length),
        ctypes.byref(password_data),
        ctypes.byref(item),
    )
    if status == ERR_SEC_ITEM_NOT_FOUND:
        raise KeychainSecretNotFound("required macOS Keychain item is missing")
    if status != ERR_SEC_SUCCESS:
        raise KeychainError("macOS Keychain could not read a secret item")
    try:
        secret = ctypes.string_at(password_data, password_length.value).decode()
    except UnicodeDecodeError:
        raise KeychainError("macOS Keychain item was not valid text") from None
    finally:
        api.security.SecKeychainItemFreeContent(None, password_data)
        _release_item(api, item)
    if not secret:
        raise KeychainSecretNotFound("required macOS Keychain item is empty")
    return secret


def _native_exists(reference: KeychainSecretReference) -> bool:
    api = _native_api()
    service = reference.service.encode()
    account = reference.account.encode()
    item = ctypes.c_void_p()
    status = api.security.SecKeychainFindGenericPassword(
        None,
        len(service),
        service,
        len(account),
        account,
        None,
        None,
        ctypes.byref(item),
    )
    _release_item(api, item)
    return bool(status == ERR_SEC_SUCCESS)


def _native_delete(reference: KeychainSecretReference) -> bool:
    api = _native_api()
    service = reference.service.encode()
    account = reference.account.encode()
    item = ctypes.c_void_p()
    status = api.security.SecKeychainFindGenericPassword(
        None,
        len(service),
        service,
        len(account),
        account,
        None,
        None,
        ctypes.byref(item),
    )
    if status == ERR_SEC_ITEM_NOT_FOUND:
        return False
    if status != ERR_SEC_SUCCESS:
        raise KeychainError("macOS Keychain could not inspect a secret item")
    try:
        delete_status = api.security.SecKeychainItemDelete(item)
        if delete_status != ERR_SEC_SUCCESS:
            raise KeychainError("macOS Keychain rejected a secret deletion")
    finally:
        _release_item(api, item)
    return True


def _release_item(api: _NativeSecurityAPI, item: ctypes.c_void_p) -> None:
    if item.value is not None:
        api.core_foundation.CFRelease(item)
