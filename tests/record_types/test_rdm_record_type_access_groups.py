# -*- coding: utf-8 -*-
#
# Copyright (C) 2025 Ubiquity Press.
#
# Invenio-Bulk-Importer is free software; you can redistribute it and/or
# modify it under the terms of the MIT License; see LICENSE file for more
# details.

"""Tests for giving groups access to restricted records."""

from invenio_accounts.proxies import current_datastore
from invenio_db import db as invenio_db
from invenio_rdm_records.proxies import current_rdm_records_service
from invenio_rdm_records.records import RDMRecord
from invenio_records_resources.services.uow import UnitOfWork
from invenio_records_resources.tasks import system_identity

RESTRICTED_FILES = {"record": "public", "files": "restricted"}
RESTRICTED_RECORD = {"record": "restricted", "files": "restricted"}
PUBLIC = {"record": "public", "files": "public"}


def _group_grants(record_id):
    """List the group grants on a record's parent.

    :param record_id: Id of the published record.
    :return: ``(group id, permission)`` pairs, sorted.
    """
    record = RDMRecord.pid.resolve(record_id)
    return sorted(
        (grant.subject_id, grant.permission)
        for grant in record.parent.access.grants
        if grant.subject_type == "role"
    )


def _import(instance, access, set_app_config_fn_scoped, groups):
    """Import a record with the given access and configured groups.

    :param instance: A validated RDM record type instance.
    :param access: Access to give the record.
    :param set_app_config_fn_scoped: Config override fixture.
    :param groups: Value for ``BULK_IMPORTER_RESTRICTED_ACCESS_GROUPS``.
    :return: The imported record.
    """
    set_app_config_fn_scoped(
        {
            "RDM_COMMUNITY_REQUIRED_TO_PUBLISH": False,
            "BULK_IMPORTER_RESTRICTED_ACCESS_GROUPS": groups,
        }
    )
    instance._importer_record["transformed_data"]["access"] = access
    record = instance.run()
    assert record, instance.errors
    return record


def test_restricted_files_give_groups_view_access(
    app,
    set_app_config_fn_scoped,
    db,
    user_admin,
    admin_group,
    validated_rdm_record_instance_no_files,
    search_clear,
):
    """Restricted files alone are enough for the groups to be granted."""
    record = _import(
        validated_rdm_record_instance_no_files,
        RESTRICTED_FILES,
        set_app_config_fn_scoped,
        ["admin", admin_group.id],
    )

    assert _group_grants(record["id"]) == sorted(
        [("admin", "view"), (admin_group.id, "view")]
    )


def test_restricted_record_gives_groups_view_access(
    app,
    set_app_config_fn_scoped,
    db,
    user_admin,
    validated_rdm_record_instance_no_files,
    search_clear,
):
    """Restricted metadata gets the groups too."""
    record = _import(
        validated_rdm_record_instance_no_files,
        RESTRICTED_RECORD,
        set_app_config_fn_scoped,
        ["admin"],
    )

    assert _group_grants(record["id"]) == [("admin", "view")]


def test_public_record_gets_no_groups(
    app,
    set_app_config_fn_scoped,
    db,
    user_admin,
    validated_rdm_record_instance_no_files,
    search_clear,
):
    """A fully public record needs no grants."""
    record = _import(
        validated_rdm_record_instance_no_files,
        PUBLIC,
        set_app_config_fn_scoped,
        ["admin"],
    )

    assert _group_grants(record["id"]) == []


def test_no_groups_when_setting_is_unset(
    app,
    set_app_config_fn_scoped,
    db,
    user_admin,
    validated_rdm_record_instance_no_files,
    search_clear,
):
    """Nothing is granted unless groups are configured."""
    record = _import(
        validated_rdm_record_instance_no_files,
        RESTRICTED_FILES,
        set_app_config_fn_scoped,
        [],
    )

    assert _group_grants(record["id"]) == []


def test_group_already_granted_is_not_granted_again(
    app,
    set_app_config_fn_scoped,
    db,
    user_admin,
    admin_group,
    validated_rdm_record_instance_no_files,
    search_clear,
):
    """A later import adds new groups and leaves existing grants alone."""
    instance = validated_rdm_record_instance_no_files
    record = _import(instance, RESTRICTED_FILES, set_app_config_fn_scoped, ["admin"])
    set_app_config_fn_scoped(
        {"BULK_IMPORTER_RESTRICTED_ACCESS_GROUPS": ["admin", admin_group.id]}
    )

    draft = current_rdm_records_service.edit(system_identity, record["id"])
    with UnitOfWork(invenio_db.session) as uow:
        instance._grant_restricted_access(draft, {"access": RESTRICTED_FILES}, uow)
        uow.commit()

    assert _group_grants(record["id"]) == sorted(
        [("admin", "view"), (admin_group.id, "view")]
    )


def test_validation_accepts_group_named_by_its_id(
    app, set_app_config_fn_scoped, user_admin, valid_rdm_record_instance
):
    """A group whose id is its name can be granted."""
    set_app_config_fn_scoped({"BULK_IMPORTER_RESTRICTED_ACCESS_GROUPS": ["admin"]})

    valid_rdm_record_instance._verify_restricted_access_groups(
        {"access": RESTRICTED_FILES}
    )

    assert valid_rdm_record_instance.errors == []


def test_validation_rejects_unknown_group(
    app, set_app_config_fn_scoped, valid_rdm_record_instance
):
    """A group that does not exist fails at the Validate step."""
    set_app_config_fn_scoped(
        {"BULK_IMPORTER_RESTRICTED_ACCESS_GROUPS": ["no-such-group"]}
    )

    valid_rdm_record_instance._verify_restricted_access_groups(
        {"access": RESTRICTED_FILES}
    )

    assert [e["type"] for e in valid_rdm_record_instance.errors] == [
        "access_group_not_found"
    ]


def test_validation_accepts_newly_created_group(
    app, set_app_config_fn_scoped, db, valid_rdm_record_instance
):
    """A group created within Invenio, whose id is its name, can be granted."""
    role = current_datastore.create_role(
        id="restricted-readers", name="restricted-readers"
    )
    current_datastore.commit()
    assert role.id == role.name
    set_app_config_fn_scoped({"BULK_IMPORTER_RESTRICTED_ACCESS_GROUPS": [role.id]})

    valid_rdm_record_instance._verify_restricted_access_groups(
        {"access": RESTRICTED_FILES}
    )

    assert valid_rdm_record_instance.errors == []


def test_validation_ignores_groups_for_public_record(
    app, set_app_config_fn_scoped, valid_rdm_record_instance
):
    """A public record gets no groups, so they are not checked."""
    set_app_config_fn_scoped(
        {"BULK_IMPORTER_RESTRICTED_ACCESS_GROUPS": ["no-such-group"]}
    )

    valid_rdm_record_instance._verify_restricted_access_groups({"access": PUBLIC})

    assert valid_rdm_record_instance.errors == []
