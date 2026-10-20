# Medical Devices Registry

Independent Python project for the public Ministry of Health Medical Devices
registry. It uses direct HTTP requests; no browser or crawling runtime is needed.

## Observed API

Base URL: `https://registries.health.gov.il/api/MedicalDevices`

All five observed operations use POST with JSON:

| Operation | Purpose |
| --- | --- |
| GetMedicalDevicesDataWithParam | Search and pagination |
| GetMedicalDeviceByRegistrationNumber | Details for a numeric registrationNumber |
| GetAccessoryNameFilter | Accessory-name suggestions |
| GetManufacturesFilter | Manufacturer suggestions |
| GetRegisteredOwnerFilter | Registered-owner suggestions |

Frontend configuration and code were inspected on 2026-10-20. Search reported
30,283 records. A 1,000-row first page and the 283-row final page (page 30) were
verified. Details for one registration returned the same 13 business fields as
the search listing. The extraction uses the listing, avoiding one call per device.
See `integration/openapi.yaml` for request/response schemas and verification scope.

Full local extraction also passed on 2026-10-20: 30,283 rows across 31 pages,
30,282 distinct registration numbers, no duplicate full-row hashes and no invalid
date strings. This verified the API and local pipeline, not a run on Databricks.
The notebook and table preparation have not been executed in the company workspace.

Important source spellings: `maxResaults`, `manufacter`, `isDecending`,
`typePremission`, `experationDate`, `experties`. Search pages start at zero.
The detail request must send registrationNumber as a JSON number; the response
returns it as a string. Details may report totalRows=0 even with matching rows.
For details, check the returned records rather than treating totalRows=0 as absence.

`typePremission=false` means all declaration categories, not only active licenses.
The source includes old expiration dates. No active/expired status is inferred.
`typePremission=true` is the website's declaration-route filter.

## Databricks notebook

Build on a developer machine:

```sh
python3 -m pip wheel . --no-deps --wheel-dir dist
```

Upload the wheel to an existing Unity Catalog Volume. Import either
`notebooks/medical_devices_ingestion.ipynb` or the Databricks source `.py` notebook.
Replace the wheel path in its first installation cell.

Requirements: Python 3.11+, UC-enabled compute, Volume READ/WRITE privileges and
outbound HTTPS to registries.health.gov.il:443. Install dependencies via company
approved package distribution. PySpark is supplied by Databricks, not this package.

Set widgets:

- `root`: existing `/Volumes/catalog/schema/volume/medical_devices` directory.
- `run_id`: unique snapshot ID, e.g. `medical_devices_20261020`; keep the same ID only for retries.
- `page_size`: 1000 by default; 1..1000 supported by this client.
- `max_pages`: 0 for a full snapshot, positive for an explicit sample.
- `search`: blank for the whole registry or a source text filter.
- `declaration_only`: false for all declaration categories.
- `target_table`: the proposed three-part name, used to prepare DDL only.

For Jobs use one notebook task and max concurrent runs=1. Run API calls on the
driver, not in Spark UDFs. A new scheduled refresh needs a new run_id.

## Output and completeness

`<root>/<run_id>/` contains config, per-page raw JSON, records.jsonl and manifest.
Checks reject HTTP/application/HTML errors, count changes, wrong page numbers,
short pages and repeated pages. A final head/count recheck detects some source
changes. The API offers no verified snapshot token: same-count changes outside
the head cannot be ruled out. Long-interrupted runs should use a new run_id.

The manifest is complete only when fetched rows equal the reported total.
Sampling is explicitly marked sampled; failures are failed. The DataFrame builder
accepts only complete, checksum-verified snapshots.
No assumption is made that registration_number uniquely identifies a row:
all source rows are retained. Proposed row identity is run_id/source_page/source_row.
row_hash and duplicate statistics aid review rather than silently dropping data.
All original fields, including future fields, remain in raw_json and raw page files.

Dates are parsed as the observed MM/dd/yyyy format. Original date strings remain
in expiration_date_raw; invalid or missing dates become null, not guessed dates.

## Table preparation only

The notebook builds `devices_df`, displays 20 rows and prints Delta DDL. It does
not execute SQL, create a table, modify permissions, or publish records. A commented
publication template is included for a later approved task using replaceWhere
to replace only the selected run_id partition. The target catalog/schema/table
must be agreed with the company before enabling writes.

## Local run and checks

```sh
python3 -m pip install -e '.[test]'
python3 -m pytest -q
python3 -m moh_medical_devices --output output --run-id sample_20261020 --max-pages 2
```

Omit --max-pages for a full local snapshot. Rebuild the ipynb after source notebook
changes with `python3 tools/build_notebook.py`. The integration folder includes
Postman collection/environment, OpenAPI and a shareable ZIP.

Official Databricks references:
- https://docs.databricks.com/aws/en/volumes/
- https://docs.databricks.com/aws/en/delta/selective-overwrite
