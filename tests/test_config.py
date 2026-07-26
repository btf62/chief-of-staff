"""Tests for the non-secret configuration boundary."""

import logging

import pytest

from chief_of_staff.config import (
    ENVIRONMENT_VARIABLE,
    LOG_LEVEL_VARIABLE,
    ConfigurationError,
    Environment,
    RuntimeSettings,
)


def test_settings_use_safe_defaults() -> None:
    settings = RuntimeSettings.from_environ({})

    assert settings.environment is Environment.DEVELOPMENT
    assert settings.log_level == logging.INFO


def test_settings_parse_explicit_values() -> None:
    settings = RuntimeSettings.from_environ(
        {
            ENVIRONMENT_VARIABLE: "test",
            LOG_LEVEL_VARIABLE: "warning",
        }
    )

    assert settings.environment is Environment.TEST
    assert settings.log_level == logging.WARNING


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        (ENVIRONMENT_VARIABLE, "private@example.com"),
        (LOG_LEVEL_VARIABLE, "secret-value"),
    ],
)
def test_configuration_errors_never_echo_invalid_values(
    variable: str,
    value: str,
) -> None:
    with pytest.raises(ConfigurationError) as error:
        RuntimeSettings.from_environ({variable: value})

    assert variable in str(error.value)
    assert value not in str(error.value)
