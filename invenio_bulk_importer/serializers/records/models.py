# -*- coding: utf-8 -*-
#
# Copyright (C) 2026 Ubiquity Press
#
# Invenio-Bulk-Importer is free software; you can redistribute it and/or modify
# it under the terms of the MIT License; see LICENSE file for more details.
#

"""Pydantic models shared by every record serializer.

These describe the shape of an InvenioRDM record payload, not the shape of any
particular input format. A serializer parses its own format into these, so the
payload is validated once here rather than once per format.

The format-specific halves, the newline-separated lists CSV uses, the element
trees ONIX uses, stay in their own modules.
"""

from typing import Literal

from flask import current_app
from invenio_base.utils import obj_or_import_string
from pydantic import BaseModel, Field, model_validator


class Geometry(BaseModel):
    """Schema for geometry location."""

    type: str
    coordinates: list[str]


class LocationFeature(BaseModel):
    """Schema for location feature."""

    description: str
    geometry: Geometry
    place: str


class Location(BaseModel):
    """Schema for locations."""

    features: list[LocationFeature] = Field(default_factory=list)


class BaseIdentifier(BaseModel):
    """Schema for identifiers."""

    scheme: str | None = Field(default=None)
    identifier: str | None = Field(default=None)


class FullIdentifier(BaseIdentifier):
    """Schema for full identifiers."""

    resource_type: dict[str, str | None] = Field(default_factory=dict)
    relation_type: dict[str, str | None] = Field(default_factory=dict)


class Role(BaseModel):
    """Schema for role."""

    id: str


class Affiliation(BaseModel):
    """Schema for affiliation."""

    id: str | None = Field(default=None)
    name: str | None = Field(default=None)

    @model_validator(mode="after")
    def _require_id_or_name(self) -> "Affiliation":
        if not self.id and not self.name:
            raise ValueError("Affiliation requires either 'id' or 'name'.")
        return self


class PersonOrOrg(BaseModel):
    """Schema for person or organization."""

    family_name: str | None = Field(default=None)
    given_name: str | None = Field(default=None)
    name: str | None = Field(default=None)
    type: Literal["personal", "organizational"]
    identifiers: list[BaseIdentifier] = Field(default_factory=list)


class Creator(BaseModel):
    """Schema for creator."""

    person_or_org: PersonOrOrg
    affiliations: list[Affiliation] = Field(default_factory=list)
    role: Role | None = Field(default=None)


class Contributor(BaseModel):
    """Schema for contributor."""

    person_or_org: PersonOrOrg
    affiliations: list[Affiliation] = Field(default_factory=list)
    role: Role


class Date(BaseModel):
    """Schema for dates."""

    date: str
    type: dict[str, str]
    description: str | None = Field(default=None)


class Funder(BaseModel):
    """Funder schema."""

    id: str | None = Field(default=None)
    name: str | None = Field(default=None)

    @model_validator(mode="after")
    def _require_id_or_name(self) -> "Funder":
        if not self.id and not self.name:
            raise ValueError("Funder requires either 'id' or 'name'.")
        return self


class Award(BaseModel):
    """Award schema."""

    id: str | None = Field(default=None)
    number: str | None = Field(default=None)
    title: dict[str, str] | None = Field(default=None)
    acronym: str | None = Field(default=None)
    program: str | None = Field(default=None)
    identifiers: list[BaseIdentifier] | None = Field(default=None)

    @model_validator(mode="after")
    def _require_id_or_number_or_title(self) -> "Award":
        if not self.id and not (self.number or self.title):
            raise ValueError(
                "Award requires either 'id' or either 'number' or 'title'."
            )
        return self


class Funding(BaseModel):
    """Schema for funding."""

    funder: Funder
    award: Award | None = Field(default=None)


def load_configured_custom_fields(config_key: str, values: dict) -> dict:
    """Run the custom-field transformers configured for a serializer.

    Each transformer is named in ``BULK_IMPORTER_CUSTOM_FIELDS`` under the
    serializer's key and receives the whole of one record's source data.

    A plain function rather than a shared validator: pydantic runs
    ``mode="before"`` validators in reverse -- a subclass's ahead of its
    parents', and within a class the last defined first -- so where a shared
    validator ran would depend on how each schema is laid out. Called
    explicitly, each serializer decides, and transformers get raw source data.

    :param config_key: Key the serializer's entries sit under in config.
    :param values: The raw source data for one record.
    :return: Custom field values by field name, only for transformers that
        returned something.
    """
    custom_fields = {}
    config = current_app.config.get("BULK_IMPORTER_CUSTOM_FIELDS", {}).get(
        config_key, []
    )
    for t in config:
        result = obj_or_import_string(t["transformer"])(values)
        # only add to custom fields if the transformer returns a value
        if result:
            custom_fields[t["field"]] = result
    return custom_fields
