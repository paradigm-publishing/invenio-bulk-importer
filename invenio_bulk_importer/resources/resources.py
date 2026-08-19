# -*- coding: utf-8 -*-
#
# Copyright (C) 2025 Ubiquity Press.
#
# Invenio-Faculty-Profiles is free software; you can redistribute it and/or
# modify it under the terms of the MIT License; see LICENSE file for more
# details.

"""Resource for Faculty Profiles."""

from flask import g
from flask_resources import (
    request_body_parser,
    resource_requestctx,
    response_handler,
    route,
)
from invenio_records_resources.resources.records.resource import (
    RecordResource,
    request_view_args,
)

from .parser import RequestFileNameAndStreamParser

request_stream = request_body_parser(
    parsers={"application/octet-stream": RequestFileNameAndStreamParser()},
    default_content_type="application/octet-stream",
)

#
# Resource
#


class ImporterTaskResource(RecordResource):
    """Faculty Profile Resource class."""

    def create_url_rules(self):
        """Create the URL rules for the record resource."""
        routes = self.config.routes
        return [
            route("GET", routes["list"], self.search),
            route("POST", routes["list"], self.create),
            route("GET", routes["item"], self.read),
            route("PUT", routes["item"], self.update),
            route("DELETE", routes["item"], self.delete),
            route("GET", routes["metadata-file"], self.read_metadata_file),
            route("PUT", routes["metadata-file"], self.update_metadata_file),
            route("DELETE", routes["metadata-file"], self.delete_metadata_file),
            route("GET", routes["config"], self.get_record_types),
            route("GET", routes["config-item"], self.get_record_type_configs),
            route("POST", routes["item-validate"], self.start_validation),
            route("POST", routes["item-load"], self.start_loading_records),
            route("PUT", routes["item-status"], self.get_status_update),
        ]

    @response_handler(many=True)
    def get_record_types(self):
        """Get the available record types."""
        list_items = self.service.get_record_types(g.identity)
        return list_items, 200

    @request_view_args
    @response_handler()
    def get_record_type_configs(self):
        """Get the available record types."""
        record_type_str = resource_requestctx.view_args["record_type"]
        config_dict = self.service.get_record_type_config(g.identity, record_type_str)
        return config_dict, 200

    @request_view_args
    def read_metadata_file(self):
        """Read metadata's content."""
        ep_pid = resource_requestctx.view_args["pid_value"]
        item = self.service.read_metadata_file(
            g.identity,
            ep_pid,
        )
        # The metadata file is user-uploaded and admin-only: keep it out of
        # shared caches and make the browser download it rather than render it.
        return item.send_file(restricted=True, as_attachment=True)

    @request_view_args
    @request_stream
    @response_handler()
    def update_metadata_file(self):
        """Upload metadata content."""
        item = self.service.update_metadata_file(
            g.identity,
            resource_requestctx.view_args["pid_value"],
            resource_requestctx.data["request_filename"],
            resource_requestctx.data["request_stream"],
            content_length=resource_requestctx.data["request_content_length"],
        )
        return item.to_dict(), 200

    @request_view_args
    def delete_metadata_file(self):
        """Delete metadata."""
        self.service.delete_metadata_file(
            g.identity,
            resource_requestctx.view_args["pid_value"],
        )
        return "", 204

    @request_view_args
    @response_handler()
    def start_validation(self):
        """Trigger validation for the current task."""
        task_id = resource_requestctx.view_args["pid_value"]
        item = self.service.start_validation(
            g.identity,
            task_id,
        )
        return item.to_dict(), 200

    @request_view_args
    @response_handler()
    def start_loading_records(self):
        """Trigger validation for the current task."""
        task_id = resource_requestctx.view_args["pid_value"]
        item = self.service.start_loading_records(
            g.identity,
            task_id,
        )
        return item.to_dict(), 200

    @request_view_args
    @response_handler()
    def get_status_update(self):
        """Trigger task status update based on associated records."""
        task_id = resource_requestctx.view_args["pid_value"]
        item = self.service.status_update(
            g.identity,
            task_id,
        )
        return item.to_dict(), 200


class ImporterRecordResource(RecordResource):
    """Importer Record Resource class."""

    def create_url_rules(self):
        """Create the URL rules for the record resource."""
        routes = self.config.routes
        return [
            route("GET", routes["list"], self.search),
            route("GET", routes["item"], self.read),
            route("POST", routes["run-item"], self.start_run),
        ]

    @request_view_args
    @response_handler()
    def start_run(self):
        """Trigger a create run for the current importer record."""
        record_id = resource_requestctx.view_args["pid_value"]
        item = self.service.start_run(
            g.identity,
            record_id,
        )
        return item.to_dict(), 200
