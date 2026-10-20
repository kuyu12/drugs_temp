# Medical Devices Registry (pandas, version 0.2.0)

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

## Project layout

- `src/moh_medical_devices/client.py`: HTTP client, retries and shared rate limiter.
- `src/moh_medical_devices/pandas_ingestion.py`: listing/detail extraction into pandas.
- `src/moh_medical_devices/record_normalization.py`: original-field preservation and normalized columns.
- `notebooks/medical_devices_ingestion.ipynb`: executable notebook.
- `integration/`: unchanged Swagger/OpenAPI and Postman definitions.

There is no table.py, Spark ingestion, Delta DDL or file snapshot pipeline.
The public function is `fetch_medical_devices_dataframe`, not featch_dataframe.
Always transfer the entire project, not only the notebook. Version 0.2.0 requires
pandas_ingestion.py and record_normalization.py; these must be tracked in Git.

## Databricks notebook: pandas only

Clone this repository into a Databricks Git folder and open
`notebooks/medical_devices_ingestion.ipynb`. Run the dependency installation cell,
restart Python if requested by the runtime, then run the remaining cells. The setup cell validates required source files, reports the loaded package path
and checks version 0.2.0. After pulling updated code, restart Python to clear any
older imports. Imports are resolved from the project checkout; alternatively install the project using
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

Public Python API:

```python
from moh_medical_devices import (
    MedicalDevicesClient, MedicalDevicesConfig, fetch_medical_devices_dataframe,
)

client = MedicalDevicesClient(MedicalDevicesConfig())
try:
    devices_df = fetch_medical_devices_dataframe(
        client, detail_workers=4, requests_per_second=2,
    )
finally:
    client.close()
```

At completion, `devices_df` is a **pandas DataFrame**, not a Spark DataFrame:

```python
devices_df.shape
devices_df.attrs['extraction']
devices_df[['registration_number', 'product_name_en', 'details']].head()
```

On failure the notebook prints the complete chained traceback and re-raises the
same exception. `last_error` holds that exception object; `last_error_traceback`
holds the full formatted text even if the notebook UI truncates its display.
HTTP/JSON/application errors retain the response object on `RegistryError.response`
and include the untruncated body, status and endpoint in exception notes.
Original HTTP, transport and JSON exceptions remain chained; detail failures
also identify the registration number, including failures inside worker threads.
Request headers/cookies are not printed. Error bodies may contain upstream data;
review diagnostics before sharing them outside approved company channels.

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

## Local installation and checks

```sh
python3 -m pip install -e '.[test]'
python3 -m pytest -q
python3 -m moh_medical_devices --search Somnu
```

The CLI builds a pandas DataFrame in memory and prints a summary, without writing
files. The notebook retains devices_df in the session for further work. Use a
narrow search such as Somnu for a short live smoke test; search='' fetches the
entire registry and every requested detail.

Build the wheel if the company prefers package installation:

```sh
python3 -m pip wheel . --no-deps --wheel-dir dist
python3 tools/build_delivery.py
```

The delivery builder checks that required notebook/package files exist and are
tracked in Git before packaging. The ZIP includes source, notebook, tests,
integration definitions and only wheels matching version 0.2.0. The notebook
does not require a wheel, Volume, catalog, SQL or a table.

The API request contracts and public source are unchanged. The checked-in ipynb
is the notebook source of truth; do not transfer a notebook without its package.
