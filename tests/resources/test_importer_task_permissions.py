"""Importer tasks and records are administration-only."""

import pytest

TASK_ENDPOINTS = [
    "/importer-tasks",
    "/importer-tasks/{task_id}",
    "/importer-tasks/{task_id}/metadata",
    "/importer-records",
]


@pytest.mark.parametrize("endpoint", TASK_ENDPOINTS)
def test_anonymous_cannot_read_importer_data(client, headers, task, endpoint):
    """Importer data must not be readable without logging in.

    Tasks and records carry the source data and the transformed metadata of
    records that are not published yet, so none of it is public.
    """
    response = client.get(endpoint.format(task_id=task.id), headers=headers)

    assert response.status_code in (401, 403), endpoint


@pytest.mark.parametrize("endpoint", TASK_ENDPOINTS)
def test_non_admin_cannot_read_importer_data(
    plain_user_client, headers, task, endpoint
):
    """Being logged in is not enough; the endpoints are administration-only."""
    response = plain_user_client.get(endpoint.format(task_id=task.id), headers=headers)

    assert response.status_code == 403, endpoint


def test_admin_can_still_read_importer_data(admin_client, headers, task):
    """The administration UI keeps working."""
    for endpoint in TASK_ENDPOINTS:
        response = admin_client.get(endpoint.format(task_id=task.id), headers=headers)
        assert response.status_code == 200, endpoint


def test_metadata_file_is_not_publicly_cacheable(admin_client, headers, task):
    """The uploaded CSV must not be stored by shared caches."""
    response = admin_client.get(f"/importer-tasks/{task.id}/metadata", headers=headers)

    assert response.status_code == 200
    assert not response.cache_control.public
    assert response.headers["Content-Disposition"].startswith("attachment")
