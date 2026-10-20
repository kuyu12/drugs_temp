# Databricks notebook source
# MAGIC %md
# MAGIC # Medical Devices API -> snapshot -> table preparation
# MAGIC Import this notebook into Databricks. Install the wheel below after replacing
# MAGIC the Volume path. Python 3.11+ and Unity Catalog-enabled compute are required.
# MAGIC This notebook prepares a DataFrame and prints DDL; it does not create or write a table.

# COMMAND ----------
# MAGIC %pip install /Volumes/<catalog>/<schema>/<volume>/libs/moh_medical_devices_pipeline-0.1.0-py3-none-any.whl

# COMMAND ----------
# MAGIC %md
# MAGIC If the environment requests a Python restart after installation, restart it
# MAGIC before continuing. Set the widgets below to existing company-approved paths.

# COMMAND ----------
dbutils.widgets.text("root", "/Volumes/<catalog>/<schema>/<volume>/medical_devices")
dbutils.widgets.text("run_id", "")
dbutils.widgets.text("page_size", "1000")
dbutils.widgets.text("max_pages", "0")
dbutils.widgets.text("search", "")
dbutils.widgets.dropdown("declaration_only", "false", ["false", "true"])
dbutils.widgets.text("target_table", "catalog.schema.medical_devices_snapshots")

# COMMAND ----------
import json
import logging
from pathlib import Path

from moh_medical_devices.client import Client
from moh_medical_devices.pipeline import run_snapshot
from moh_medical_devices.table import prepare_dataframe, table_ddl

root = dbutils.widgets.get("root")
run_id = dbutils.widgets.get("run_id")
page_size = int(dbutils.widgets.get("page_size"))
max_pages_value = int(dbutils.widgets.get("max_pages"))
target_table = dbutils.widgets.get("target_table")
if not root.startswith("/Volumes/") or "<" in root or len(Path(root).parts) < 5:
    raise ValueError("Set root to an existing /Volumes/catalog/schema/volume/... path")
if not run_id:
    raise ValueError("Set a snapshot run_id; reuse it only for a retry, not a new refresh")
if max_pages_value < 0:
    raise ValueError("max_pages must be 0 (full snapshot) or positive (sample)")
ddl = table_ddl(target_table)  # Validate the identifier before any API work.
logging.basicConfig(level=logging.INFO)

# COMMAND ----------
client = Client()
try:
    manifest = run_snapshot(
        client, root, run_id, page_size=page_size,
        max_pages=max_pages_value or None,
        search=dbutils.widgets.get("search"),
        declaration_only=dbutils.widgets.get("declaration_only") == "true",
    )
finally:
    client.close()
print(json.dumps(manifest, ensure_ascii=False, indent=2))

# COMMAND ----------
# MAGIC %md
# MAGIC ## Prepare the table data
# MAGIC Only a complete snapshot with a valid checksum is accepted here.
# MAGIC A sample is retained on the Volume but will not be prepared for publication.

# COMMAND ----------
snapshot_dir = str(Path(root) / run_id)
if manifest["status"] == "complete":
    devices_df = prepare_dataframe(spark, snapshot_dir)
    display(devices_df.limit(20))
    print("Preparation only. Proposed table DDL:\n" + ddl)
else:
    print("Sampled snapshot only. Set max_pages=0 and use a new run_id for a full extraction.")

# COMMAND ----------
# MAGIC %md
# MAGIC ## Optional publication template (not executed)
# MAGIC After the company approves the table destination and write policy, a separate
# MAGIC publishing task can execute the DDL and write the complete snapshot below.
# MAGIC Retrying the same run replaces that run's partition, not the full history.
# MAGIC No publication switch or table write is active in this notebook.

# COMMAND ----------
# Future approved task only; validate manifest/run_id and destination again there:
# assert manifest["status"] == "complete"
# spark.sql(ddl)
# (devices_df.write.format("delta").mode("overwrite")
#     .option("replaceWhere", f"run_id = '{run_id}'")
#     .saveAsTable(target_table))
