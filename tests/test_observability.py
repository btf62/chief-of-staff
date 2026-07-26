"""Tests for structured and redacted application logging."""

import json
import logging
from io import StringIO
from typing import Any, cast

import pytest

from chief_of_staff.observability import REDACTED, configure_logging, log_event


def _read_record(stream: StringIO) -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads(stream.getvalue()))


def test_structured_event_emits_only_allow_listed_operational_context() -> None:
    stream = StringIO()
    logger = configure_logging(stream=stream)

    log_event(
        logger,
        logging.INFO,
        "foundation.ready",
        component="runtime",
        environment="test",
        record_count=3,
        email_body="Private correspondence",
        access_token="top-secret-token",
    )

    record = _read_record(stream)

    assert record["event"] == "foundation.ready"
    assert record["component"] == "runtime"
    assert record["environment"] == "test"
    assert record["record_count"] == 3
    assert record["redacted_field_count"] == 2
    assert "email_body" not in record
    assert "access_token" not in record
    assert "Private correspondence" not in stream.getvalue()
    assert "top-secret-token" not in stream.getvalue()


@pytest.mark.parametrize(
    "secret_shaped_value",
    [
        "Authorization: Bearer abcdefghijklmnop",
        "api_key=" + "sk-" + "example123456789",
        "password=correct-horse-battery-staple",
        "ghp_" + "abcdefghijklmnopqrstuvwxyz",
    ],
)
def test_allow_listed_strings_are_scrubbed_for_secret_patterns(
    secret_shaped_value: str,
) -> None:
    stream = StringIO()
    logger = configure_logging(stream=stream)

    log_event(
        logger,
        logging.WARNING,
        "foundation.warning",
        status=secret_shaped_value,
    )

    assert secret_shaped_value not in stream.getvalue()
    assert REDACTED in stream.getvalue()


def test_unstructured_messages_are_not_emitted() -> None:
    stream = StringIO()
    logger = configure_logging(stream=stream)
    private_message = "A private email body that must not reach logs"

    logger.warning(private_message)

    record = _read_record(stream)
    assert record["event"] == "unstructured_log"
    assert private_message not in stream.getvalue()


def test_exception_messages_are_not_emitted() -> None:
    stream = StringIO()
    logger = configure_logging(stream=stream)
    private_message = "private source content"

    try:
        raise RuntimeError(private_message)
    except RuntimeError:
        logger.exception("processing failed")

    record = _read_record(stream)
    assert record["exception_type"] == "RuntimeError"
    assert private_message not in stream.getvalue()
    assert "processing failed" not in stream.getvalue()


def test_invalid_event_names_are_rejected_without_echoing_the_value() -> None:
    stream = StringIO()
    logger = configure_logging(stream=stream)
    private_event = "Private Event Name"

    with pytest.raises(ValueError) as error:
        log_event(logger, logging.INFO, private_event)

    assert private_event not in str(error.value)
    assert stream.getvalue() == ""
