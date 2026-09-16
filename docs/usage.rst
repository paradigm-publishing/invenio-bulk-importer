..
    Copyright (C) 2025 Ubiquity Press.

    Invenio-Bulk-Importer is free software; you can redistribute it and/or
    modify it under the terms of the MIT License; see LICENSE file for more
    details.


Usage
=====

Invenio-Bulk-Importer ingests records into an Invenio-RDM instance from a
source file. Two formats are supported:

* **CSV**: one row in the file produces one record in RDM. Most of this page
  documents the column naming conventions the CSV reader understands, both to
  help authors write valid import files and to record why the format looks the
  way it does.
* **ONIX 3.0**: one book in the file produces a record for the book *and* one
  for each of its chapters, linked to each other. See `ONIX 3.0 format`_.

Transformers that feed additional fields into ``metadata.custom_fields`` are
configured separately; see :doc:`configuration`.


CSV format overview
-------------------

A CSV import file has a single header row followed by one row per record.
Multi-valued fields do not get their own rows — instead, the importer uses
two encodings that live within a single record row:

*Flat columns*
    One column maps to one metadata field. The cell holds either a single
    value (``title``, ``publisher``) or a newline-separated list
    (``languages.id``, ``formats``). The column name is the metadata path.

*Grouped columns* (rows-as-entries)
    A set of sibling columns share a prefix (for example
    ``creators.given_name`` and ``creators.family_name``). Each cell holds a
    newline-separated list, and entries at the same line index across the
    sibling columns belong to the same sub-record. This is how we encode
    lists of dicts without moving to multiple CSV rows per record.

*Discriminator columns*
    The column name itself encodes a type or scheme, and the cell holds the
    value — ``additional_descriptions.abstract``,
    ``creators.identifiers.orcid``. This pattern is only used where the
    discriminator comes from a closed vocabulary; see
    `Column patterns`_ below.

The importer is permissive about empty columns: omitting a column is the
same as leaving every cell blank. Required fields are listed explicitly in
`Field reference`_.


Column patterns
---------------

Flat columns
~~~~~~~~~~~~

The simplest case: one column, one field. Values are strings or
newline-separated lists; the column name mirrors the metadata path.

::

    title,publisher,languages.id
    "A short paper",Ubiquity Press,"eng
    fra"

Used for scalar metadata (``title``, ``description``, ``version``,
``publisher``, ``publication_date``), controlled-vocabulary references
where only the ``id`` is needed (``resource_type.id``, ``languages.id``),
free-form lists (``formats``, ``sizes``, ``references.reference``,
``keywords``), and record-level settings (``access.*``, ``communities``,
``id``, ``default_community_slug``).

A few flat columns are aliases that expand into a nested structure
internally — see `Aliases and shortcuts`_.

Grouped columns (rows-as-entries)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Grouped columns share a prefix and encode a list of sub-records. Within
each cell, values are newline-separated; the *n*-th line across all
sibling columns describes the *n*-th sub-record.

::

    creators.type,creators.given_name,creators.family_name
    "personal
    personal","Nils
    Ada","Schlüter
    Lovelace"

Used wherever the sub-record has more than one free-form field, for
example: ``creators.*``, ``contributors.*``, ``dates.*``,
``identifiers.*``, ``related_identifiers.*``, ``rights.*``,
``locations.*``, ``subjects.*``, ``funders.*``, ``awards.*``.

**Blank lines matter.** For pairings where one side is optional — such as
``funders.*`` without a matching award — the row index is preserved by
leaving a blank line rather than skipping the row. This is handled by
passing ``drop_empty=False`` to
:py:func:`~invenio_bulk_importer.serializers.records.utils.process_grouped_fields`
for the ``funders``/``awards`` pair; see
:py:meth:`~invenio_bulk_importer.serializers.records.csv.MetadataSchema.load_funding`.

**Affiliations use a secondary separator.** Inside a creator or
contributor row, multiple affiliations are separated by ``;`` within a
single newline-delimited cell, so that affiliation pairs
(``affiliations.id`` / ``affiliations.name``) stay associated with the
right person.

Discriminator columns
~~~~~~~~~~~~~~~~~~~~~

The column name encodes a type or scheme; the cell holds the value.

::

    additional_titles.alternative-title.eng,additional_descriptions.abstract,creators.identifiers.orcid
    "Something else","A short abstract","0000-0002-5699-3684"

Used in three places:

* ``additional_titles.<type>[.<lang>]``
* ``additional_descriptions.<type>[.<lang>]``
* ``creators.identifiers.<scheme>`` and
  ``contributors.identifiers.<scheme>``

These all share one property: the discriminator
(``<type>``, ``<lang>``, ``<scheme>``) is a small, closed vocabulary whose
members are known in advance. Putting it in the header lets authors write
one ORCID per creator without thinking about scheme alignment, and lets
spreadsheet tools see distinct columns for abstract vs. method
descriptions.

.. note::

   ``rights.id`` / ``rights.title`` look like discriminator columns but
   are actually a *grouped* pair — they hold the id and title of the same
   rights entry, one per newline-separated line. See the handler at
   :py:meth:`~invenio_bulk_importer.serializers.records.csv.MetadataSchema.load_rights`.

**Known limitation.** A discriminator column cannot represent two entries
with the same discriminator on the same record — e.g. two
``additional_descriptions.methods.eng`` entries. This has not come up in
practice; if it does, the field must migrate to the grouped pattern.

Convention for new fields
~~~~~~~~~~~~~~~~~~~~~~~~~

When adding a new CSV column, pick the pattern by asking whether the
discriminator is a closed vocabulary:

* **Closed vocabulary, small set, values are known in advance** (identifier
  schemes, language codes, a fixed list of description types) → use the
  discriminator pattern.
* **Open set, or the sub-record has more than one meaningful field**
  (free-form dates with descriptions, related identifiers with relation
  and resource type, rights with optional id/title) → use the grouped
  pattern.
* **Single value or trivial list** → use a flat column.

This is the rule going forward; fields that don't fit it today are
captured in `Open questions`_.


Field reference
---------------

Required columns are marked with a ``*``. All other columns are optional.
The "Maps to" column shows the path in the record dict produced by the
importer.

Record-level columns
~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 25 15 25 35

   * - CSV column
     - Pattern
     - Maps to
     - Notes
   * - ``id``
     - flat
     - ``id``
     - Optional. If present, updates an existing record.
   * - ``doi``
     - flat (alias)
     - ``pids.doi.identifier`` (provider ``external``)
     - See `Aliases and shortcuts`_.
   * - ``filenames``
     - flat (alias)
     - ``files``
     - Newline-separated list of filenames. Alias for ``files``.
   * - ``default_community_slug``
     - flat
     - ``default_community``
     - Aliases: ``default_collection``, ``default_collection_slug``.
   * - ``communities``
     - flat
     - ``communities``
     - Newline-separated slugs. Aliases: ``community_slugs``,
       ``collections``, ``collection_slugs``.
   * - ``access.record``
     - flat
     - ``access.record``
     - ``public`` (default) or ``restricted``.
   * - ``access.files``
     - flat
     - ``access.files``
     - ``public`` (default) or ``restricted``.
   * - ``access.embargo.active``
     - flat
     - ``access.embargo.active``
     - Any truthy value enables the embargo block.
   * - ``access.embargo.until``
     - flat
     - ``access.embargo.until``
     - ISO-8601 date.
   * - ``access.embargo.reason``
     - flat
     - ``access.embargo.reason``
     - Free text.

Metadata columns
~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 30 20 20 30

   * - CSV column
     - Pattern
     - Maps to
     - Notes
   * - ``title`` \*
     - flat
     - ``metadata.title``
     - Required, non-empty.
   * - ``additional_titles.<type>[.<lang>]``
     - discriminator
     - ``metadata.additional_titles[]``
     - e.g. ``additional_titles.alternative-title.eng``.
   * - ``publication_date`` \*
     - flat
     - ``metadata.publication_date``
     - Required. Also accepts the legacy header
       ``publication_date (EDTF Level 0 forrmat)``.
   * - ``description``
     - flat
     - ``metadata.description``
     -
   * - ``additional_descriptions.<type>[.<lang>]``
     - discriminator
     - ``metadata.additional_descriptions[]``
     - e.g. ``additional_descriptions.abstract``.
   * - ``version``
     - flat
     - ``metadata.version``
     -
   * - ``publisher`` \*
     - flat
     - ``metadata.publisher``
     -
   * - ``resource_type.id`` \*
     - flat
     - ``metadata.resource_type.id``
     - Required. Vocabulary id (e.g. ``publication``, ``dataset``).
   * - ``languages.id``
     - flat (list)
     - ``metadata.languages[].id``
     - Newline-separated ISO-639-3 codes.
   * - ``creators.*`` \*
     - grouped
     - ``metadata.creators[]``
     - At least one creator row required. Sub-columns: ``type``,
       ``given_name``, ``family_name``, ``name``, ``role.id``,
       ``affiliations.id``, ``affiliations.name``, and any
       ``identifiers.<scheme>``. Multiple affiliations separated by
       ``;`` within a cell.
   * - ``contributors.*``
     - grouped
     - ``metadata.contributors[]``
     - Same sub-columns as ``creators``; ``role.id`` is required per row.
   * - ``dates.date``, ``dates.type.id``, ``dates.description``
     - grouped
     - ``metadata.dates[]``
     -
   * - ``subjects.subject``, ``subjects.scheme``
     - grouped
     - ``metadata.subjects[]``
     - Counts must match. Each pair is looked up in the ``subjects``
       vocabulary; unmatched entries fail validation.
   * - ``keywords``
     - flat (list)
     - ``metadata.subjects[]`` (unschemed)
     - Free-text terms. Newline-separated; each becomes a subject entry
       with no scheme. Use ``subjects.subject`` / ``subjects.scheme``
       for vocabulary-controlled entries.
   * - ``references.reference``
     - flat (list)
     - ``metadata.references[].reference``
     - Newline-separated.
   * - ``identifiers.identifier``, ``identifiers.scheme``
     - grouped
     - ``metadata.identifiers[]``
     -
   * - ``related_identifiers.*``
     - grouped
     - ``metadata.related_identifiers[]``
     - Sub-columns: ``identifier``, ``scheme``, ``relation_type.id``,
       ``resource_type.id``.
   * - ``rights.id``, ``rights.title``
     - grouped
     - ``metadata.rights[]``
     - For each row, either ``id`` (vocabulary-matched) or ``title``
       (free text, stored as ``{"en": title}``) is populated.
   * - ``formats``, ``sizes``
     - flat (list)
     - ``metadata.formats[]``, ``metadata.sizes[]``
     - Newline-separated.
   * - ``funders.id``, ``funders.name``
     - grouped
     - ``metadata.funding[].funder``
     - Paired positionally with ``awards.*``. Blank lines preserved.
   * - ``awards.id``, ``awards.number``, ``awards.title``,
       ``awards.acronym``, ``awards.program``
     - grouped
     - ``metadata.funding[].award``
     - Paired with ``funders.*`` by row index.
   * - ``locations.lat``, ``locations.lon``, ``locations.place``,
       ``locations.description``
     - grouped
     - ``metadata.locations.features[]``
     - Coordinates produce ``Point`` geometries. Lat/lon are paired
       within a feature.

Custom fields
~~~~~~~~~~~~~

Any column not recognised above is ignored unless it is handled by a
custom-fields transformer. Transformers are registered under
``BULK_IMPORTER_CUSTOM_FIELDS['csv_rdm_record_serializer']`` and receive
the raw row dict; see :doc:`configuration`. The test fixture at
``tests/serializers/data/rdm_records.csv`` exercises ``imprint.*`` columns
through this mechanism.


Aliases and shortcuts
---------------------

The reader honours a handful of alias column names for convenience or
backward compatibility:

``doi``
    Maps to ``pids.doi.identifier``, with ``provider`` forced to
    ``external``. Prefer ``doi`` in new files — the full path is only
    used internally.

``filenames``
    Maps to ``files``. Newline-separated list of filenames associated
    with the record.

``keywords``
    Free-text terms. Each newline-separated value is appended to
    ``metadata.subjects`` as a subject entry without a scheme. This is
    not a shortcut for ``subjects`` — they are two distinct inputs that
    both land in ``metadata.subjects``: ``keywords`` for free text, and
    ``subjects.subject`` / ``subjects.scheme`` for entries drawn from a
    controlled vocabulary. The two feeds are merged on read.

``default_community_slug``
    Accepted aliases: ``default_collection``, ``default_collection_slug``.

``communities``
    Accepted aliases: ``community_slugs``, ``collections``,
    ``collection_slugs``.

``publication_date (EDTF Level 0 forrmat)``
    Legacy header preserved for existing import templates. **Note the
    typo** (``forrmat``); it is intentional, matching the header in
    files already in use. Prefer plain ``publication_date`` in new files.


Open questions
--------------

The following points are unresolved. They are documented here so that
template authors understand the current behaviour and so that follow-up
tickets can be tracked against concrete sections.

* **Repeated discriminators.** The discriminator pattern cannot represent
  two ``additional_descriptions`` entries that share the same type *and*
  language (for example, two ``additional_descriptions.methods.eng``).
  The second cell silently overwrites the first on read. If this case
  appears in real data, the field must migrate to the grouped pattern.

* **Aliases: keep or deprecate?** ``doi``, ``filenames``, and the
  ``default_collection`` / ``community_slugs`` variants are in active
  use. We have not decided whether they are permanent shortcuts or
  transitional aliases to be removed in a future version. This page
  currently documents them as permanent.

* **Custom fields documentation.** Custom-field behaviour is driven by
  ``BULK_IMPORTER_CUSTOM_FIELDS`` and is therefore site-specific. We
  currently document the mechanism in :doc:`configuration` and only
  mention the columns here in passing. Whether custom-field conventions
  (including the preferred pattern) belong in this page is open.


ONIX 3.0 format
---------------

The ``onix3`` serializer reads the aggregated ONIX 3.0 message produced by the
publisher-delivery preprocessor. That message is a narrow, predictable dialect
of ONIX rather than arbitrary publisher ONIX:

* an ``<ONIXMessage release="3.0">`` in the
  ``http://ns.editeur.org/onix/3.0/reference`` namespace, using reference tags
  (never short tags);
* one ``<Product>`` per book, its chapters as
  ``<ContentDetail>/<ContentItem>``;
* every file a ``gs://`` link in ``<SupportingResource>``, with its filename
  and size alongside.

Files outside that shape are rejected with a message saying what was found,
rather than silently importing nothing. Create the task with
``serializer = onix3`` and ``mode = import``.

Records and groups
~~~~~~~~~~~~~~~~~~

Each ``<Product>`` becomes a **group**: a ``publication-book`` record followed
by one ``publication-book-chapter`` record per content item, front matter
included. A group is imported together, so the book and its chapters succeed
or fail as a unit. A book with no content items is a group of one and imports
like a CSV row.

A chapter is transformed on its own, long after the file was read, so its
source data carries what it inherits from its book: publisher, publication
date, languages, licence and the book's authors.

Linking books and chapters
~~~~~~~~~~~~~~~~~~~~~~~~~~

The book gets one ``haspart`` related identifier per chapter, and each chapter
one ``ispartof`` back to its book. Both are written by **DOI**, which the
preprocessor supplies for books and chapters alike, so the links survive
DataCite export.

The two directions degrade independently: the book links to a chapter through
the *chapter's* DOI, and a chapter to its book through the *book's*. Where the
DOI at the other end is missing, the link cannot be written yet; its intent is
recorded in the importer record's ``group_relations`` for the group import to
resolve once every record of the group has a PID.

Field mapping
~~~~~~~~~~~~~

Values are mapped at transform time, not when the file is read, so correcting
a lookup table and re-validating picks the change up without uploading the
file again.

.. list-table::
   :header-rows: 1
   :widths: 40 30 30

   * - ONIX
     - Book record
     - Chapter record
   * - ``ProductIdentifier`` type 06 / ``TextItemIdentifier`` type 06
     - ``pids.doi`` (provider ``external``)
     - ``pids.doi`` (provider ``external``)
   * - ``ProductIdentifier`` type 15 (ISBN-13)
     - ``metadata.identifiers[]`` and imprint ``isbn``
     - imprint ``isbn`` (the book's)
   * - ``TitleText`` / ``Subtitle``
     - ``metadata.title`` / ``additional_titles[]`` (``subtitle``)
     - ``metadata.title``; imprint ``title`` is the book's
   * - ``Contributor``
     - ``creators[]`` / ``contributors[]`` by role
     - ``creators[]``, falling back to the book's
   * - ``PublishingDate`` role 01
     - ``metadata.publication_date`` as EDTF
     - inherited
   * - ``PublisherName``, ``LanguageCode``
     - ``metadata.publisher``, ``metadata.languages[]``
     - inherited
   * - ``TextContent`` type 03
     - ``metadata.description``
     - ``metadata.description`` (the abstract)
   * - ``TextContent`` types 06 and 12
     - ``additional_descriptions[]`` (``other``)
     -
   * - ``Subject`` scheme 20
     - ``metadata.subjects[]``, free text
     - ``metadata.subjects[]``, free text
   * - ``Extent`` type 05 / ``NumberOfPages``
     - ``metadata.sizes[]``
     - ``metadata.sizes[]``
   * - ``PageRun``
     -
     - imprint ``pages``
   * - ``Collection``, ``EditionStatement``
     - imprint ``series_name``, ``volume``, ``edition``
     -
   * - ``CopyrightStatement``
     - ``metadata.copyright``
     -
   * - ``EpubLicense``
     - ``metadata.rights[]`` and access (below)
     - inherited

Contributor roles follow ONIX codelist 17: authors (``A01``, ``A38``) and
co-authors (``A02``) become creators; editors (``B01``, ``B02``, ``B09``) and
translators (``B06``) become contributors. A book credited only to editors
promotes them to creators, since a record needs at least one. Roles with no
repository equivalent are recorded as contributors with the ``other`` role, so
a contributor is never dropped.

Access and files
~~~~~~~~~~~~~~~~

Record metadata is public. Files are public for an openly licensed title
(one carrying an ``<EpubLicense>``) and restricted otherwise, since the absence
of that licence is what marks a title as not openly licensed. Both behaviours
are configurable; see :doc:`configuration`.

Who may see a restricted record is decided by the instance's permission policy.
On top of that, the groups listed in ``BULK_IMPORTER_RESTRICTED_ACCESS_GROUPS`` are given
view access to every record whose metadata or files are restricted, for CSV and
ONIX imports alike; see :doc:`configuration`.

A book record gets its full-content PDF followed by its cover. A chapter
record gets its own PDF. The MARC record the preprocessor also lists is never
attached. Only ``gs://`` links are accepted: a ``file://`` link names a path on
whichever machine wrote the file, which the importer's workers cannot reach.

Errors
~~~~~~

Besides ordinary validation errors, a record can fail with:

``retracted_title``
    The title is withdrawn (``PublishingStatus`` 11). Fails the book and its
    chapters.
``invalid_file_uri``
    An attached file is not a ``gs://`` link.
``file_name_mismatch``
    A link does not end in the filename ONIX declares for it. The link's last
    segment becomes the file's name on the record, so a disagreement would
    store the file under the wrong name.
``unsupported_mode``
    The task is in ``delete`` mode, which ONIX imports do not support.

Known gaps
~~~~~~~~~~

* **Communities.** ONIX carries none, so records carry none. On an instance
  with ``RDM_COMMUNITY_REQUIRED_TO_PUBLISH`` enabled, every record fails with
  ``community_not_provided`` until a community is supplied another way.
* **Licence names.** Creative Commons licence links resolve on their own; any
  other licence needs an entry in the ``licenses`` setting, or no rights entry
  is written.
* **Funding.** The message carries no ``<Funding>``, so ``metadata.funding``
  stays empty.
* **Audiences and proprietary subject codes.** Audience values are
  publisher-specific and are not mapped. Scheme-23 subject codes are dropped
  unless the ``subject_codes`` setting maps them.
* **Part titles.** A part grouping several chapters loses its title before the
  message is written, so it cannot be recovered on import.
* **Group import.** Until the group import task lands, records are imported one
  at a time and links recorded in ``group_relations`` are not resolved.


Export serialization
--------------------

The export serializer
(:py:class:`~invenio_bulk_importer.serializers.records.csv_export.CSVRDMRecordExportSerializer`)
reverses the patterns above: nested dicts are flattened with ``.`` as the
separator, lists are collapsed to newline-separated strings, and
creator/contributor identifiers are re-emitted as
``creators.identifiers.<scheme>`` columns. Fields not yet handled on
export (notably funding) are noted under `Open questions`_.


.. automodule:: invenio_bulk_importer
