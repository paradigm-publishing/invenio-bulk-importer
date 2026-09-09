# -*- coding: utf-8 -*-
#
# Copyright (C) 2025 Ubiquity Press
#
# Invenio-Bulk-Importer is free software; you can redistribute it and/or modify
# it under the terms of the MIT License; see LICENSE file for more details.
#

"""Importer Task Service Schema."""

from enum import Enum

import marshmallow as ma
from invenio_i18n import gettext as _
from invenio_records_resources.services.records.schema import (
    BaseRecordSchema as InvenioBaseRecordSchema,
)
from marshmallow_utils.fields import NestedAttribute, SanitizedUnicode

from .states import ImporterRecordState, ImporterTaskState


class FilesSchema(ma.Schema):
    """Basic files schema class."""

    enabled = ma.fields.Bool(missing=True)
    # allow unsetting
    default_preview = SanitizedUnicode(allow_none=True)

    def get_attribute(self, obj, attr, default):
        """Override how attributes are retrieved when dumping.

        NOTE: We have to access by attribute because although we are loading
              from an external pure dict, but we are dumping from a data-layer
              object whose fields should be accessed by attributes and not
              keys. Access by key runs into FilesManager key access protection
              and raises.
        """
        value = getattr(obj, attr, default)

        if attr == "default_preview" and not value:
            return default

        return value


def validate_mode(value):
    """Check if the value is a valid mode setting."""
    if value not in ["import", "delete"]:
        raise ma.ValidationError(
            message=str(_("Value must be either 'import' or 'delete'."))
        )


def _validate_status(value: str, enum_state: Enum):
    """Check if the value is within a enum as a value."""
    if value not in [state.value for state in enum_state]:
        raise ma.ValidationError(
            message=str(
                _(
                    f"Value '{value}' must be one of: "
                    + ", ".join(f"'{state.value}'" for state in enum_state)
                    + "."
                )
            )
        )


def validate_record_status(value):
    """Check if the value is a valid importer record status."""
    _validate_status(value, ImporterRecordState)


def validate_task_status(value):
    """Check if the value is a valid importer task status."""
    _validate_status(value, ImporterTaskState)


class UserSchema(ma.Schema):
    """User schema for the started_by field."""

    id = ma.fields.Integer(dump_only=True)
    username = ma.fields.String(dump_only=True)
    email = ma.fields.Email(dump_only=True)

    class Meta:
        """Meta class for User Schema."""

        unknown = ma.RAISE


class ImporterTaskSchema(InvenioBaseRecordSchema):
    """Importer Task Service Schema."""

    class Meta:
        """Meta class for Importer Task Schema."""

        unknown = ma.RAISE

    title = ma.fields.String(
        required=True,
        validate=ma.validate.Length(min=1, max=255),
    )
    description = ma.fields.String(
        allow_none=True,
        validate=ma.validate.Length(max=1000),
    )
    mode = ma.fields.String(validate=validate_mode, required=True)
    """The mode is the type of import to be performed, e.g., 'import' or 'delete'."""
    record_type = ma.fields.String(
        required=True,
        validate=ma.validate.Length(min=1, max=255),
    )
    """The record_type is the type of record to be imported, e.g., 'record'.
    See BULK_IMPORTER_RECORD_TYPES config."""
    serializer = ma.fields.String(
        required=True,
        validate=ma.validate.Length(min=1, max=255),
    )
    """The serializer is the name of the serializer type to be used to
    validate input data." See BULK_IMPORTER_RECORD_TYPES config."""
    start_time = ma.fields.DateTime(allow_none=True)
    end_time = ma.fields.DateTime(allow_none=True)
    records_status = ma.fields.Dict(allow_none=True)
    """The records_status is a dictionary containing the total number of
    importer records and sum of records in particular statuses
    that are associated n the importer task."""
    status = ma.fields.String(validate=validate_task_status, required=True)
    """The status of the complete importer task."""
    files = NestedAttribute(FilesSchema)
    started_by = ma.fields.Nested(UserSchema, dump_only=True)
    """The user who started the importer task."""
    options = ma.fields.Dict(
        allow_none=True,
        description="Configuration options for the importer task setup record_type selected.",
    )


class RelatedImporterTaskSchema(ma.Schema):
    """Related Importer Task Schema for Importer Record."""

    id = ma.fields.String(dump_only=True)


class ImportErrorSchema(ma.Schema):
    """Schema for Importer Record errors."""

    msg = ma.fields.String(
        required=True,
        description="Error message describing the issue encountered during import.",
    )
    loc = ma.fields.String(
        required=True,
        description="Location of the error.",
    )
    type = ma.fields.String(
        required=True,
        description="Type of error encountered during import (e.g., 'validation', 'processing').",
    )


class ImporterRecordSchema(InvenioBaseRecordSchema):
    """Importer Record Service Schema."""

    class Meta:
        """Meta class for Importer Record Schema."""

        unknown = ma.RAISE

    status = ma.fields.String(validate=validate_record_status, required=True)
    message = ma.fields.String(
        allow_none=True,
        validate=ma.validate.Length(max=1000),
    )
    src_data = ma.fields.Dict(
        allow_none=True,
        description="Source data dictionary before being validated by serializer.",
    )
    serializer_data = ma.fields.Dict(
        allow_none=True,
        description="Serialized data of a record, if applicable.",
    )
    transformed_data = ma.fields.Dict(
        allow_none=True,
        description="Transformed data of a record, if applicable.",
    )
    community_uuids = ma.fields.Dict(
        allow_none=True,
        description="Community uuids to link to the record.",
    )
    record_files = ma.fields.List(
        ma.fields.String(),
        allow_none=True,
        description="List of file name, urls and cloud bucket urls to be associated with the record.",
    )
    validated_record_files = ma.fields.List(
        ma.fields.Dict(),
        allow_none=True,
        description="List of validated files with key, size and origin.",
    )
    existing_record_id = ma.fields.String(
        allow_none=True,
        description="Existing record ID if the import is updating an existing record.",
    )
    generated_record_id = ma.fields.String(
        allow_none=True,
        description="Generated record ID after successful import.",
    )
    group_id = ma.fields.String(
        allow_none=True,
        description="Shared by the records that have to be imported together.",
    )
    group_key = ma.fields.String(
        allow_none=True,
        description="Identifies the record within its group, for siblings to refer to.",
    )
    group_role = ma.fields.String(
        allow_none=True,
        description="Role of the record within its group, e.g. parent or child.",
    )
    group_position = ma.fields.Integer(
        allow_none=True,
        description="Order of the record within its group.",
    )
    group_relations = ma.fields.List(
        ma.fields.Dict(),
        allow_none=True,
        description="Links to sibling records, resolved when the group is imported.",
    )
    errors = ma.fields.List(
        ma.fields.Nested(ImportErrorSchema),
    )
    task = ma.fields.Nested(RelatedImporterTaskSchema, dump_only=True)
