# -*- coding: utf-8 -*-
#
# Copyright (C) 2025 Ubiquity Press
#
# Invenio-Bulk-Importer is free software; you can redistribute it and/or modify
# it under the terms of the MIT License; see LICENSE file for more details.
#

"""Base resource."""

from abc import ABC, abstractmethod
from urllib.parse import urlparse

import boto3
import requests
from botocore import UNSIGNED
from botocore.client import Config
from flask import current_app
from google.cloud import storage
from invenio_communities.proxies import current_communities
from invenio_db import db
from invenio_files_rest.models import ObjectVersion
from invenio_pidstore.errors import PIDDoesNotExistError
from invenio_rdm_records.proxies import current_rdm_records_service
from invenio_rdm_records.records import RDMDraft
from invenio_records_resources.tasks import system_identity

from ..proxies import current_importer_tasks_service as tasks_service
from .uow import rollabck_unit_of_work


class RecordType(ABC):
    """Base record type class."""

    def __init__(self, serializer_data: tuple[dict | None, list[dict]]):
        """Initialize the record type."""
        self.id: str | None = (
            serializer_data[0].pop("id", None)
            if serializer_data and serializer_data[0]
            else None
        )
        self._serializer_record_data: dict | None = (
            serializer_data[0] if serializer_data[0] else None
        )
        self._errors: list[dict] = (
            serializer_data[1] if serializer_data and serializer_data[1] else []
        )
        self._record: dict | None = None
        self.is_successful = True

    @abstractmethod
    def validate(self) -> bool:
        """Load the stream object by object."""

    @abstractmethod
    def run(self) -> dict:
        """Transform a given object into something Invenio understands."""

    @property
    def errors(self) -> list[dict]:
        """Return the list of errors."""
        return self._errors

    def _add_error(self, error: dict) -> None:
        """Add an error to the errors list."""
        self._errors.append(error)
        self.is_successful = False

    @property
    def validated_record_dict(self) -> dict | None:
        """Return the validated record dictionary."""
        return self._record


class PermissionsMixin:
    """Mising to handle community/record permissions."""

    def _validate_permissions(self, serializer_data):
        """Validate that public record cannot be added to restricted community.

        This code mimics
        `invenio_rdm_records.requests.community_inclusion.is_access_restriction_valid`.
        """
        is_record_public = serializer_data["access"]["record"] == "public"

        for community_id in self._community_uuids["ids"]:
            community = current_communities.service.read(
                id_=community_id,
                identity=system_identity,
            )
            is_community_restricted = (
                community.data["access"]["visibility"] == "restricted"
            )
            if is_record_public and is_community_restricted:
                self._add_error(
                    dict(
                        type="invalid_access_restriction",
                        loc="access.record",
                        msg="A public record cannot be added to a restricted community",
                    )
                )


class CommunityMixin:
    """Mixin to handle community-related operations."""

    def _add_community_vars(self, serializer_data: tuple[dict | None, list[dict]]):
        """Initialize the mixin with serializer data."""
        self._serializer_communities: list[str] = (
            serializer_data[0].pop("communities", [])
            if serializer_data and serializer_data[0]
            else []
        )
        self._is_community_required = current_app.config.get(
            "RDM_COMMUNITY_REQUIRED_TO_PUBLISH", False
        )
        self._community_uuids: dict[str, str | list[str]] = dict(default=None, ids=[])

    def _verify_communities_exist(self, communities: list):
        """Verify that the listed communities exist."""
        if not communities and self._is_community_required:
            self._add_error(
                dict(
                    type="community_not_provided",
                    loc="communities",
                    msg="At least one community is required to publish the record.",
                )
            )
            return
        for idx, community_slug in enumerate(communities):
            try:
                community = current_communities.service.read(
                    id_=community_slug,
                    identity=system_identity,
                )
                if idx == 0:
                    self._community_uuids["default"] = community.id
                self._community_uuids["ids"].append(community.id)
            except PIDDoesNotExistError:
                self._add_error(
                    dict(
                        type="community_not_found",
                        loc="communities",
                        msg=f"Community '{community_slug}' not found.",
                    )
                )

    @property
    def community_uuids_dict(self) -> dict | None:
        """Return the validated record dictionary."""
        return self._community_uuids


class FileMixin:
    """Mixin to handle file-related operations."""

    def _add_file_vars(
        self, serializer_data: tuple[dict | None, list[dict]], bucket_id: str
    ):
        """Initialize the mixin with serializer data."""
        self._validated_files: list[dict] = []
        self._files: list[str] = (
            serializer_data[0].pop("files", [])
            if serializer_data and serializer_data[0]
            else []
        )
        self.bucket_id = bucket_id

    def _get_file_name(self, file_name: str) -> tuple[str, str]:
        """Extract the file name and origin of file.

        Args:
            file_name: The name of the file, which can be a URL, S3 path, GCS path, or local file path.

        Returns:
            A tuple containing the file name and its origin type (url, s3, gs, or local).
        """
        if file_name.startswith(("http://", "https://")):
            return file_name.split("/")[-1], "url"
        elif file_name.startswith("s3:"):
            return file_name.split("/")[-1], "s3"
        elif file_name.startswith("gs:"):
            return file_name.split("/")[-1], "gs"
        else:
            return file_name, "local"

    def _add_validated_file(self, file: str, size: int | None):
        """Add a validated file to the list of files."""
        file_name, file_origin = self._get_file_name(file)
        self._validated_files.append(
            {
                "key": file_name,
                "full_path": file,
                "size": int(size) if size else None,
                "origin": file_origin,
            }
        )

    def _check_url_file_accessibility(self, file: str):
        """Check if the URL file is accessible."""
        try:
            response = requests.head(file, timeout=10)
            response.raise_for_status()
        except requests.HTTPError as e:
            # Reported separately from the transport errors below, so the
            # status code is stated plainly rather than through requests'
            # own wording.
            self._add_error(
                dict(
                    type="file_not_accessible",
                    loc="files",
                    msg=f"Error accessing URL file '{file}' returned status code {e.response.status_code}.",
                )
            )
            return
        except Exception as e:
            self._add_error(
                dict(
                    type="file_not_accessible",
                    loc="files",
                    msg=f"Error accessing URL file '{file}': {str(e)}",
                )
            )
            return
        # Get file size from Content-Length header
        self._add_validated_file(file, response.headers.get("Content-Length"))

    def _check_gs_file_accessibility(self, file: str):
        """Check if the Google Cloud Storage file is accessible."""
        try:
            parsed_url = urlparse(file)
            bucket_name = parsed_url.netloc
            blob_name = parsed_url.path.lstrip("/")

            storage_client = storage.Client.create_anonymous_client()
            bucket = storage_client.bucket(bucket_name)
            blob = bucket.blob(blob_name)
            if not blob.exists():
                self._add_error(
                    dict(
                        type="file_not_accessible",
                        loc="files",
                        msg=f"Error accessing GCS file '{file}' does not exist.",
                    )
                )
                return
            # Get file size from blob metadata
            blob.reload()  # Ensure metadata is loaded
            self._add_validated_file(file, blob.size)
        except Exception as e:
            self._add_error(
                dict(
                    type="file_not_accessible",
                    loc="files",
                    msg=f"Error accessing GCS file '{file}': {str(e)}",
                )
            )

    def _check_s3_file_accessibility(self, file: str):
        """Check if the S3 file is accessible."""
        try:
            parsed_url = urlparse(file)
            bucket_name = parsed_url.netloc
            key = parsed_url.path.lstrip("/")

            s3_client = boto3.client(
                "s3",
                config=Config(signature_version=UNSIGNED),
            )
            response = s3_client.head_object(Bucket=bucket_name, Key=key)
            self._add_validated_file(file, response.get("ContentLength"))
        except Exception as e:
            self._add_error(
                dict(
                    type="file_not_accessible",
                    loc="files",
                    msg=f"Error accessing S3 file '{file}': {str(e)}",
                )
            )

    def _check_invenio_file_accessibility(self, file: str):
        """Check if the Invenio files are accessible."""
        object_versions_obj = ObjectVersion.get_by_bucket(self.bucket_id)
        object_versions = {
            obj_ver.basename: obj_ver.file.size for obj_ver in object_versions_obj
        }
        if not object_versions or file not in object_versions.keys():
            self._add_error(
                dict(
                    type="file_not_found",
                    loc="files",
                    msg=f"File '{file}' not found in invenio bucket.",
                )
            )
        else:
            # If the file is in the Invenio bucket, we can assume it's accessible
            self._add_validated_file(file, object_versions[file])

    def _verify_files_accessible(self, files: list) -> bool:
        """Verify that the listed files are accessible."""
        for file in files:
            # HTTP/HTTPS URL
            if file.startswith(("http://", "https://")):
                self._check_url_file_accessibility(file)
            # S3 cloud storage
            elif file.startswith("s3:"):
                self._check_s3_file_accessibility(file)
            # Google Cloud Storage
            elif file.startswith("gs:"):
                self._check_gs_file_accessibility(file)
            # Local file in bucket
            else:
                self._check_invenio_file_accessibility(file)

    def _get_stream_for_file_content(self, file: dict):
        """Get appropriate stream based on file origin."""
        origin = file.get("origin", "local")
        if origin not in ["url", "s3", "gs", "local"]:
            raise ValueError(f"Unsupported file origin: {origin}")

        stream_method = getattr(self, f"_get_stream_from_{origin}", None)
        if not stream_method:
            raise NotImplementedError(f"Streaming from {origin} not implemented")

        return stream_method(file["full_path"])

    def _get_stream_from_gs(self, url: str):
        """Get a stream from a Google Cloud Storage URL."""
        parsed_url = urlparse(url)
        bucket_name = parsed_url.netloc
        blob_name = parsed_url.path.lstrip("/")

        storage_client = storage.Client.create_anonymous_client()
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(blob_name)

        # Open a streaming reader on the blob
        stream = blob.open("rb")
        return stream

    def _get_stream_from_s3(self, url: str):
        """Get a stream from an S3 URL."""
        parsed_url = urlparse(url)
        bucket_name = parsed_url.netloc
        key = parsed_url.path.lstrip("/")

        s3_client = boto3.client("s3", config=Config(signature_version=UNSIGNED))
        response = s3_client.get_object(Bucket=bucket_name, Key=key)

        # Return the streaming body directly - it's already file-like
        # This is more memory efficient than reading it all into BytesIO
        return response["Body"]

    def _get_stream_from_url(self, url: str):
        """
        Get a stream from an HTTPS URL.

        Args:
            url: The URL to stream from
            chunk_size: Size of chunks to yield (bytes)

        Yields:
            Chunks of file data
        """
        try:
            response = requests.get(url, stream=True, timeout=30)
            response.raise_for_status()  # Raise exception for 4XX/5XX responses

            # Return the raw response which is file-like and has read() method
            return response.raw
        except Exception as e:
            raise ValueError(f"Error streaming file from '{url}': {str(e)}")

    def _get_stream_from_local(self, file: str):
        """Get a stream from a local file path."""
        file_service = tasks_service.files
        pid_value = self._importer_record.task_id
        if not pid_value:
            raise ValueError("Missing 'pid_value' for local file streaming.")
        try:
            item = file_service.get_file_content(system_identity, pid_value, file)
            return item.get_stream("rb")
        except FileNotFoundError:
            raise ValueError(f"Local file '{file}' not found.")
        except Exception as e:
            raise ValueError(f"Error opening local file '{file}': {str(e)}")

    @property
    def record_file_list(self) -> list | None:
        """Return the validated record dictionary."""
        return self._files

    @property
    def validated_record_file_list(self) -> list | None:
        """Return the validated record dictionary."""
        return self._validated_files


class InvenioRecordMixin:
    """Mixin to handle Invenio record-related operations."""

    def _verify_record_exists(self, record_id: str, required: bool = False) -> bool:
        """Verify that the draft or published record exist."""
        if not record_id and not required:
            return True  # No record ID provided, nothing to verify

        try:
            current_rdm_records_service.read(system_identity, record_id)
        except Exception:
            try:
                current_rdm_records_service.read_draft(system_identity, record_id)
            except Exception:
                self._add_error(
                    dict(
                        type="existing_record_not_found",
                        loc="record",
                        msg=f"Record '{record_id}' not found.",
                    )
                )
                return False
        return True

    @rollabck_unit_of_work()
    def _verify_pre_commit_correctness(
        self, record_data, record_id: str = None, uow=None
    ) -> bool:
        """Check pre-create validations for the record."""
        data = record_data
        with db.session.begin_nested():
            # Create the record and the model so we can checkpre-commit validations for relations
            record = RDMDraft(data, model=RDMDraft.model_cls(id=record_id, data=data))
            # Run pre create extensions
            for e in RDMDraft._extensions:
                # This requires to get all systemfields in api record schema.
                # So we can get the MultiRelationsField which holds a RelationsMapping that  has a list of fields
                # We will validate each, if we use the MultiRelationsField.pre_commit() it will excpetion on the first failure
                # instead of running through all the fields.
                try:
                    e.pre_create(record)
                except Exception as e:
                    self._add_error(
                        dict(
                            type="pre_create_validation_error",
                            loc="record",
                            msg=str(e),
                        )
                    )
                try:
                    e.post_create(record)
                except Exception as e:
                    self._add_error(
                        dict(
                            type="post_create_validation_error",
                            loc="record",
                            msg=str(e),
                        )
                    )
                if "relations" in e.declared_fields:
                    field = e.declared_fields["relations"]
                    mapping = field.obj(record)
                    for name in mapping._fields:
                        try:
                            getattr(mapping, name).validate()
                        except Exception as e:
                            self._add_error(
                                dict(
                                    type="pre_commit_validation_error",
                                    loc=f"relations.{name}",
                                    msg=str(e),
                                )
                            )
                else:
                    try:
                        e.pre_commit(record)
                    except Exception as e:
                        self._add_error(
                            dict(
                                type="pre_commit_validation_error",
                                loc="record",
                                msg=str(e),
                            )
                        )
