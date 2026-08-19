# -*- coding: utf-8 -*-
#
# Copyright (C) 2025 Ubiquity Press.
#
# Invenio-Bulk-Importer is free software; you can redistribute it and/or
# modify it under the terms of the MIT License; see LICENSE file for more
# details.

"""States for Importer Records and Tasks."""

from enum import Enum
from typing import Dict


class ImporterRecordState(Enum):
    """States for individual importer records."""

    CREATED = "created"
    VALIDATING = "validating"
    SERIALIZER_VALIDATION_FAILED = "serializer validation failed"
    VALIDATION_FAILED = "validation failed"
    VALIDATED = "validated"
    IMPORT_FAILED = "import failed"
    IMPORTED = "success"


class ImporterTaskState(Enum):
    """States for importer tasks."""

    CREATED = "created"
    VALIDATING = "validating"
    VALIDATION_FAILED = "validated with failures"
    VALIDATED = "validated"
    IMPORTING = "importing"
    IMPORT_FAILED = "imported with failures"
    SUCCESS = "success"
    DAMAGED = "damaged"


class TaskStateCalculator:
    """Calculate task state based on record states."""

    @staticmethod
    def calculate_task_state(record_states: Dict[str, int]) -> str:
        """
        Calculate task state based on record state counts.

        Args:
            record_states: Dictionary with state names as keys and counts as values

        Returns:
            Task state string
        """

        def state_count(state: Enum) -> int:
            """Helper function to get the count for a given state."""
            return record_states.get(state.value, 0)

        total_records = record_states["total_records"]
        # Extract counts for all ImporterRecordState values
        created_count = state_count(ImporterRecordState.CREATED)
        serializer_validation_failed_count = state_count(
            ImporterRecordState.SERIALIZER_VALIDATION_FAILED
        )
        validation_failed_count = state_count(ImporterRecordState.VALIDATION_FAILED)
        validated_count = state_count(ImporterRecordState.VALIDATED)
        import_failed_count = state_count(ImporterRecordState.IMPORT_FAILED)
        success_count = state_count(ImporterRecordState.IMPORTED)

        if total_records == 0:
            return ImporterTaskState.CREATED.value

        if created_count > 0 and (
            serializer_validation_failed_count > 0
            or validation_failed_count > 0
            or validated_count > 0
        ):
            # Some records have been through validation, others have not yet.
            return ImporterTaskState.VALIDATING.value

        if created_count > 0:
            # Nothing has been validated yet.
            return ImporterTaskState.CREATED.value

        # Check for validation failures
        if validation_failed_count > 0 or serializer_validation_failed_count > 0:
            return ImporterTaskState.VALIDATION_FAILED.value
        # Check if all records are validated
        if validated_count == total_records and created_count == 0:
            return ImporterTaskState.VALIDATED.value

        if validated_count > 0 and (import_failed_count > 0 or success_count > 0):
            # If there are records that are validated and currently being imported
            return ImporterTaskState.IMPORTING.value

        if validated_count == 0 and import_failed_count > 0:
            # If there are records that failed to import but were validated
            return ImporterTaskState.IMPORT_FAILED.value

        if success_count == total_records:
            # If all records were successfully imported
            return ImporterTaskState.SUCCESS.value

        # Default fallback
        return ImporterTaskState.DAMAGED.value
