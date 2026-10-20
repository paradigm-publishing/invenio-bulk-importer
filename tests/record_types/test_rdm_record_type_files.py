# -*- coding: utf-8 -*-
#
# Copyright (C) 2025 Ubiquity Press.
#
# Invenio-Bulk-Importer is free software; you can redistribute it and/or
# modify it under the terms of the MIT License; see LICENSE file for more
# details.

"""File upload tests for the RDM record type."""

from io import BytesIO
from unittest import mock

import pytest

from invenio_bulk_importer.record_types import rdm
from invenio_bulk_importer.record_types.rdm import RDMRecord

FILES = [{"key": "article.pdf", "size": 3}]


def _add_files(file_service, stream):
    """Upload ``FILES`` through ``file_service``, reading from ``stream``."""
    record_type = RDMRecord(({}, None))
    rdm_service = mock.Mock(draft_files=file_service)
    with (
        mock.patch.object(rdm, "current_rdm_records_service", rdm_service),
        mock.patch.object(
            RDMRecord, "_get_stream_for_file_content", return_value=stream
        ),
    ):
        record_type._add_files_to_record(
            {"validated_record_files": FILES}, mock.Mock(id="abcd-1234")
        )


def test_add_files_closes_stream_after_upload(app):
    """The file stream is closed once its content is uploaded."""
    stream = BytesIO(b"pdf")
    file_service = mock.Mock()

    def read_content(identity, record_id, key, content, size, uow=None):
        assert not content.closed
        assert content.read() == b"pdf"

    file_service.set_file_content.side_effect = read_content

    _add_files(file_service, stream)

    file_service.set_file_content.assert_called_once()
    assert stream.closed


def test_add_files_closes_stream_when_upload_fails(app):
    """The file stream is closed even when uploading its content raises."""
    stream = BytesIO(b"pdf")
    file_service = mock.Mock()
    file_service.set_file_content.side_effect = OSError("upload failed")

    with pytest.raises(OSError):
        _add_files(file_service, stream)

    assert stream.closed
