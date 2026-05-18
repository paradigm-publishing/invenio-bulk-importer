# -*- coding: utf-8 -*-
#
# Copyright (C) 2026 Paradigm Repositories.
#
# Invenio-Bulk-Importer is free software; you can redistribute it and/or
# modify it under the terms of the MIT License; see LICENSE file for more
# details.

"""CSV serializer compatible with the bulk importer.

To use it, update the current serializers from
``invenio_rdm_records.resources.config.record_serializers`` adding an instance of
``CSVRDMRecordExportSerializer`` properly configured to your needs. The content type can be
something like ``application/vnd.inveniordm.v1.bulk+csv``.

Example::

    from flask_resources import ResponseHandler
    from invenio_rdm_records.resources.config import record_serializers

    RDM_RECORDS_SERIALIZERS = {
        **record_serializers,
        "application/vnd.inveniordm.v1.bulk+csv": ResponseHandler(
            CSVRDMRecordExportSerializer()
        ),
    }
"""

from functools import partial

from flask import current_app
from flask_resources.serializers import CSVSerializer
from invenio_base.utils import obj_or_import_string

from .utils import flatten_grouped_fields_to_column_title


class CSVRDMRecordExportSerializer(CSVSerializer):
    """CSV serializer compatible with the bulk importer.

    It differs from the RDM one just in how it treats list fields. In this case it always
    collapses a set of fields into one column using newlines to separate values.
    It also simplifies the path on some instances like `metadata.creators.person_or_org.type`
    is replaced by `creators.type`

    Note: This serializer is not suitable for serializing large number of
    records.
    """

    def __init__(self, *args, **kwargs):
        """Set base class default values."""
        super().__init__(*args, **kwargs)
        self.collapse_lists = True
        self.header_separator = "."
        self.csv_excluded_fields.extend(
            (
                "access.status",
                "resource_type.title",
                "role.title",
                "languages.title",
                "rights.props",
            )
        )

    def is_field_included(self, key):
        """Determines if a key should be included or not."""
        if key in self.csv_excluded_fields or self.field_in_key(
            key, self.csv_excluded_fields
        ):
            return False
        if self.csv_included_fields and not self.key_in_field(
            key, self.csv_included_fields
        ):
            return False
        return True

    def field_in_key(self, key, fields):
        """Checks if a field from the list is included in the key."""
        return any(field in key for field in fields)

    def _flatten_list_dict_dict(self, value, parent_key=""):
        """Override upstream to accumulate string-valued sub-keys per row.

        The upstream implementation overwrites instead of appending in the
        ``isinstance(v1, str)`` branch, so list entries whose only differing
        fields are scalars (e.g. ``languages.id``, ``rights.title``) collapse
        to the last entry's value. This override mirrors the accumulator
        logic the dict branch already uses.

        TODO: remove once
        https://github.com/inveniosoftware/flask-resources/blob/master/flask_resources/serializers/csv.py
        is fixed upstream.
        """
        combined_dict = {}
        iterator = 0
        keys = set()
        for item in value:
            current_keys = set()
            for k1, v1 in item.items():
                if isinstance(v1, str):
                    new_key = f"{parent_key}.{k1}" if parent_key else k1
                    if self.is_field_included(new_key):
                        current_keys.add(new_key)
                        if new_key in keys:
                            combined_dict[new_key].append(v1)
                        else:
                            keys.add(new_key)
                            combined_dict[new_key] = [""] * iterator + [v1]
                else:
                    if not isinstance(v1, dict):
                        continue
                    for k2, v2 in v1.items():
                        if not isinstance(v2, str):
                            continue
                        new_key = (
                            f"{parent_key}.{k1}.{k2}" if parent_key else f"{k1}.{k2}"
                        )
                        if self.is_field_included(new_key):
                            current_keys.add(new_key)
                            if new_key in keys:
                                combined_dict[new_key].append(v2)
                            else:
                                keys.add(new_key)
                                combined_dict[new_key] = [""] * iterator + [v2]

            for missing_key in keys - current_keys:
                combined_dict[missing_key].append("")
            iterator += 1

        return {key: "\n".join(values) for key, values in combined_dict.items()}

    def _preprocess_access(self, access):
        """Preprocess the access dictionary.

        Remove the status key, we don't want it in the export.
        """
        if not access.get("embargo", {}).get("active", False):
            # If embargo is not active there is no point in having it there
            access.pop("embargo", None)
        return access

    def _preprocess_metadata(self, metadata):
        """Preprocess the metadata dictionary.

        - Flatten creatibutors by removing the ``person_or_org`` wrapper and
          inlining identifiers as ``identifiers.<scheme>`` keys.
        - Convert location features from GeoJSON ``Point`` geometries to
          flat ``lat``/``lon`` keys.
        - Split ``subjects`` into vocabulary-backed ``subjects`` and
          free-text ``keywords``.
        - Unwrap i18n ``{"en": ...}`` strings in funding award titles,
          rights titles, and rights descriptions.
        """

        def parse_creatibutors(creatibutors):
            res = []
            for c in creatibutors:
                person_or_org = c.get("person_or_org", {})
                flatten_creator = {**person_or_org}

                identifiers = flatten_creator.pop("identifiers", [])
                for identifier in identifiers:
                    flatten_creator[f"identifiers.{identifier['scheme']}"] = identifier[
                        "identifier"
                    ]

                if role := person_or_org.get("role"):
                    flatten_creator["role"] = {"id": role["id"]}

                if affiliations := person_or_org.get("affiliations"):
                    flatten_creator["affiliations"] = affiliations

                res.append(flatten_creator)

            return res

        def parse_locations(features):
            res = []
            for f in features:
                if geometry := f.pop("geometry", None):
                    if geometry["type"] != "Point":
                        # TODO:: should we raise something or at least log a warning?
                        continue
                    f["lat"], f["lon"] = geometry["coordinates"]
                f.pop("identifiers", None)  # FIXME: find a way to work around these
                res.append(f)
            return res

        def parse_subjects(values):
            """Parse the subjects field to turn it into subjects (vocab) and keywords (free)."""
            res = {"keywords": [], "subjects": []}
            for value in values:
                if value.pop("id", None):  # This is vocabulary subject
                    res["subjects"].append(value)
                else:
                    res["keywords"].append(value["subject"])
            return res

        metadata["creators"] = parse_creatibutors(metadata["creators"])
        if contributors := metadata.get("contributors"):
            metadata["contributors"] = parse_creatibutors(contributors)

        if features := metadata.pop("locations", {}).get("features"):
            metadata["locations"] = parse_locations(features)

        if subjects := metadata.pop("subjects", []):
            metadata.update(parse_subjects(subjects))

        # Flatten funding.award.title, rights.description|title
        # This is an i18n string, but it is always set to 'en'
        for f in metadata.get("funding", []):
            if award_title := f.get("award", {}).get("title", {}).get("en"):
                f["award"]["title"] = award_title

        for r in metadata.get("rights", []):
            if title := r.get("title", {}).get("en"):
                r["title"] = title
            if desc := r.get("description", {}).get("en"):
                r["description"] = desc

        return metadata

    def _process_files(self, files):
        """Return the list of file names separated by a line break."""
        return "\n".join(files.get("entries", {}).keys())

    def _process_custom_fields(self, custom_fields):
        """Flatten custom fields into CSV columns.

        For each entry in ``custom_fields``, the matching configuration in
        ``BULK_IMPORTER_CUSTOM_FIELDS['csv_rdm_record_serializer']`` is
        consulted: if an ``exporter`` callable is registered it is invoked
        on the value, otherwise the value is flattened with ``_flatten``
        using ``export_field`` (or the field name itself) as the column
        prefix. Fields without a matching configuration entry fall back to
        ``_flatten`` with the raw field name as the prefix.

        :param custom_fields: Mapping of custom-field names (e.g.
            ``"imprint:imprint"``) to their stored values.
        :return: A flat mapping of CSV column names to string values,
            ready to be merged into the row dictionary.
        """
        look_up = {
            d["field"]: d
            for d in current_app.config["BULK_IMPORTER_CUSTOM_FIELDS"].get(
                "csv_rdm_record_serializer", []
            )
        }

        output = {}
        for field, value in custom_fields.items():
            config = look_up.get(field, {})
            field_prefix = config.get("export_field", field)
            func = obj_or_import_string(
                config.get("exporter"),
                default=partial(self._flatten, parent_key=field_prefix),
            )
            output.update(func(value))

        return output

    def process_dict(self, dictionary):
        """Flatten an RDM record into a single CSV row.

        Overrides the base flattener to handle the bulk-importer column
        conventions: ``additional_descriptions`` and ``additional_titles``
        collapse to discriminator columns (one per ``type[.lang]``),
        ``access`` is preprocessed to drop status and inactive embargo
        blocks, ``files`` becomes a newline-separated list of filenames,
        and custom fields are dispatched through ``_process_custom_fields``.

        :param dictionary: The record's ``to_dict()`` representation, as
            produced by the RDM record service. Expected keys: ``id``,
            ``access``, ``metadata``, ``files``, ``custom_fields``.
        :return: A flat ``dict[str, str]`` mapping CSV column names to
            their cell values for this record.
        """
        access = self._flatten(
            self._preprocess_access(dictionary.get("access", {})),
            parent_key="access",
        )
        metadata = dictionary.get("metadata")
        # Process special fields that are collapsed into one column
        additional_descriptions = flatten_grouped_fields_to_column_title(
            metadata.pop("additional_descriptions", []),
            "additional_descriptions",
            "description",
        )
        additional_titles = flatten_grouped_fields_to_column_title(
            metadata.pop("additional_titles", []), "additional_titles", "title"
        )
        # Process the rest of the metadata
        metadata = self._flatten(self._preprocess_metadata(metadata))

        files = self._process_files(dictionary.get("files", {}))

        custom_fields = self._process_custom_fields(dictionary.get("custom_fields", {}))

        return {
            "id": dictionary["id"],
            "files": files,
            **access,
            **metadata,
            **additional_descriptions,
            **additional_titles,
            **custom_fields,
        }
