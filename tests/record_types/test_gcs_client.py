# -*- coding: utf-8 -*-
#
# Copyright (C) 2025 Ubiquity Press.
#
# Invenio-Bulk-Importer is free software; you can redistribute it and/or
# modify it under the terms of the MIT License; see LICENSE file for more
# details.

"""GCS client selection tests.

``gcs_client`` is imported at module level so these tests exercise the real
function: the autouse ``fake_file_origins`` fixture replaces the module
attribute with a fake for every other test.
"""

from unittest import mock

import pytest
from google.auth.credentials import AnonymousCredentials, Credentials
from google.auth.exceptions import DefaultCredentialsError

from invenio_bulk_importer.record_types.base import (
    _authenticated_gcs_client,
    gcs_client,
)


@pytest.fixture(autouse=True)
def fresh_gcs_client():
    """Drop the cached client so each test resolves credentials anew."""
    _authenticated_gcs_client.cache_clear()
    yield
    _authenticated_gcs_client.cache_clear()


def _credentials():
    """Return fake Application Default Credentials."""
    return mock.Mock(spec=Credentials, universe_domain="googleapis.com")


def test_gcs_client_uses_default_credentials(app):
    """The client is authenticated with Application Default Credentials."""
    credentials = _credentials()
    with mock.patch("google.auth.default", return_value=(credentials, None)):
        client = gcs_client()

    assert client._credentials is credentials


def test_gcs_client_is_cached(app):
    """Credentials are resolved once per process, not per file."""
    with mock.patch(
        "google.auth.default", return_value=(_credentials(), None)
    ) as default:
        assert gcs_client() is gcs_client()

    default.assert_called_once()


def test_gcs_client_falls_back_to_anonymous(app, caplog):
    """Without credentials the client is anonymous, and says so."""
    with mock.patch("google.auth.default", side_effect=DefaultCredentialsError("none")):
        client = gcs_client()

    assert isinstance(client._credentials, AnonymousCredentials)
    assert "reading GCS files anonymously" in caplog.text


def test_gcs_client_retries_after_anonymous_fallback(app):
    """A credentials failure is not cached, so a later call can authenticate."""
    credentials = _credentials()
    with mock.patch(
        "google.auth.default",
        side_effect=[DefaultCredentialsError("not ready"), (credentials, None)],
    ):
        first = gcs_client()
        second = gcs_client()

    assert isinstance(first._credentials, AnonymousCredentials)
    assert second._credentials is credentials
