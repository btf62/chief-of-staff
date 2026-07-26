"""Non-secret runtime configuration boundary."""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final, Self

DATABASE_PATH_VARIABLE: Final = "CHIEF_OF_STAFF_DATABASE_PATH"
ENVIRONMENT_VARIABLE: Final = "CHIEF_OF_STAFF_ENVIRONMENT"
LOG_LEVEL_VARIABLE: Final = "CHIEF_OF_STAFF_LOG_LEVEL"

_ALLOWED_LOG_LEVELS: Final = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


class ConfigurationError(ValueError):
    """Raised when non-secret runtime configuration is invalid."""


class Environment(StrEnum):
    """Supported runtime environment labels."""

    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


@dataclass(frozen=True, slots=True)
class RuntimeSettings:
    """Validated non-secret settings used to start the local application."""

    environment: Environment = Environment.DEVELOPMENT
    log_level: int = logging.INFO
    database_path: Path | None = None

    @classmethod
    def from_environ(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> Self:
        """Create settings from an explicit environment mapping."""

        source: Mapping[str, str] = os.environ if environ is None else environ
        return cls(
            environment=_parse_environment(source.get(ENVIRONMENT_VARIABLE)),
            log_level=_parse_log_level(source.get(LOG_LEVEL_VARIABLE)),
            database_path=_parse_database_path(source.get(DATABASE_PATH_VARIABLE)),
        )


def _parse_environment(raw_value: str | None) -> Environment:
    if raw_value is None:
        return Environment.DEVELOPMENT

    try:
        return Environment(raw_value.strip().lower())
    except ValueError:
        allowed = ", ".join(environment.value for environment in Environment)
        message = f"{ENVIRONMENT_VARIABLE} must be one of: {allowed}"
        raise ConfigurationError(message) from None


def _parse_log_level(raw_value: str | None) -> int:
    if raw_value is None:
        return logging.INFO

    normalized = raw_value.strip().upper()
    try:
        return _ALLOWED_LOG_LEVELS[normalized]
    except KeyError:
        allowed = ", ".join(_ALLOWED_LOG_LEVELS)
        message = f"{LOG_LEVEL_VARIABLE} must be one of: {allowed}"
        raise ConfigurationError(message) from None


def _parse_database_path(raw_value: str | None) -> Path | None:
    if raw_value is None:
        return None
    if not raw_value.strip():
        raise ConfigurationError(f"{DATABASE_PATH_VARIABLE} must not be empty")
    return Path(raw_value).expanduser()
