# Medical Devices Registry

Independent Python project for the public Ministry of Health Medical Devices
registry. Direct HTTP requests are used; no browser or crawling runtime is needed.

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

Frontend configuration and code were inspected on 2026-10-20. A full local
file-based extraction returned 30,283 rows across 31 pages, with 30,282 distinct
registration numbers. The earlier extraction used the listing endpoint only.
Details for one inspected registration had the same 13 business fields, but
equivalence for every registration is not assumed. The notebook can fetch all
details as well. See `integration/openapi.yaml` for the unchanged API contracts.
The notebook has not been executed in the company Databricks workspace.

Source spellings include `maxResaults`, `manufacter`, `isDecending`,
`typePremission`, `experationDate` and `experties`. Pages start at zero.
Details require registrationNumber as a JSON number, while responses return a
string. Detail totalRows may be zero even when matching detail records exist.

`typePremission=false` means all declaration categories, not active licenses only.
True selects the declaration route. Expiration dates are preserved without
inferring an official active/expired status.

## Databricks notebook: pandas only

Clone this repository into a Databricks Git folder and open
`notebooks/medical_devices_ingestion.ipynb`. Run the dependency installation cell,
restart Python if requested by the runtime, then run the remaining cells. Imports
are resolved from the project checkout; alternatively install the project using
`pip install /path/to/checkout` before running the notebook.

No Volume, uploaded wheel, Unity Catalog, Spark, widgets, table destination or
run_id is required. Requirements: Python 3.11+, pandas, requests, enough driver
memory and outbound HTTPS to registries.health.gov.il:443. Use company-approved
package distribution where required.

Notebook configuration:

- `page_size=1000`: listing pagination size.
- `include_details=True`: fetch details once per unique registration number.
- `search=''`: blank for the entire registry.
- `declaration_only=False`: all declaration categories.
- `detail_workers=4`: bounded threads for detail requests (1..8).
- `requests_per_second=2`: shared detail request-start limit, including retries (0..5, exclusive of zero).
- `delay_seconds=2`: listing pacing and sequential-detail pacing.

At about 30,000 registrations and 2 starts/second, the detail rate-limit floor
alone is about 4.2 hours. Network latency and retries add time; no completion time
or freedom from blocking is guaranteed. This rate is a client setting, not a
published or approved server quota. Reduce requests_per_second if throttled.
Set detail_workers=1 to use the original sequential mode, which retains the
configured per-request delay (over 17 hours at 2 seconds for 30,000 details).
The function's default remains sequential for existing callers; the notebook
explicitly enables four workers. Set include_details=False if listing fields suffice.
Filter-option lookups are not joined as if they were device detail records.

Each thread reuses an independent public-API Session. Only detail calls run in
parallel; listing pages remain ordered and sequential. There are at most
detail_workers submitted futures, not one future per device. HTTP 429/5xx
Retry-After/backoff updates a shared cooldown. Access/contract errors cancel new
work, close worker sessions and fail the whole extraction without partial success.
Already-running HTTP requests may finish or reach their configured timeout.
Duplicate registrations are fetched once and mapped back without changing row order.

At completion, `devices_df` is a **pandas DataFrame**, not a Spark DataFrame:

```python
devices_df.shape
devices_df.attrs['extraction']
devices_df[['registration_number', 'product_name_en', 'details']].head()
```

Every listing row, original column, normalized column and raw_json is retained.
Duplicate registration numbers stay as separate rows. The details column holds
a list of all matching detail records, preserving nested and future fields.
details_raw_json retains the complete detail response, and
details_fetched_at_utc records its fetch time separately. No arbitrary detail
record is selected and no listing fields are overwritten by detail values.

No files or tables are written. Data lives only in the current Python session
and is lost when it ends. An interrupted run must restart; there are no durable
checkpoints in this mode. An API/enrichment failure raises instead of returning
partial success. devices_df is cleared before each run to avoid stale results.

Counts, page lengths, page identity, repeated pages and final head/count are
checked. The API has no verified snapshot token: same-count changes outside the
first page cannot be ruled out, especially during a long details run. Detected
source changes require a fresh run. For Jobs, use one notebook task and max
concurrent runs=1. API requests run on the driver, not in Spark UDFs.

## Optional legacy CLI snapshots

The existing file-based CLI is retained separately. The notebook does not call
it or the optional Spark/table-preparation helpers.

```sh
python3 -m pip install -e '.[test]'
python3 -m pytest -q
python3 -m moh_medical_devices --output output --run-id sample_20261020 --max-pages 2
```

Omit --max-pages for a full local file snapshot. CLI output includes raw page
checkpoints, records.jsonl and a manifest under output/run_id. Resume requires
unchanged source head/count and matching parameters. A complete manifest requires
the fetched row count to match the API total. Samples are marked sampled, and
errors are failed. Optional table preparation only accepts complete,
checksum-verified file snapshots; it never writes a table itself.

Registration number is not a unique row key. CLI row identity is
run_id/source_page/source_row, while raw_json preserves all original fields.
Dates use the observed MM/dd/yyyy format, retaining original strings and leaving
invalid dates unknown instead of guessing.

The checked-in ipynb is the notebook source of truth. The integration folder
contains Postman collection/environment and OpenAPI. API request contracts and
authentication behavior are unchanged.
