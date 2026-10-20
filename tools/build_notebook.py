"""Generate a standard ipynb from the checked-in Databricks source notebook."""
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
source = root / "notebooks/medical_devices_ingestion.py"
cells = []
for chunk in source.read_text().split("# COMMAND ----------"):
    lines = [line for line in chunk.strip().splitlines() if line != "# Databricks notebook source"]
    lines = [line[8:] if line.startswith("# MAGIC ") else line for line in lines]
    text = "\n".join(lines).strip()
    if not text:
        continue
    if text.startswith("%md"):
        cells.append({"cell_type": "markdown", "metadata": {}, "source": text[3:].strip()})
    else:
        cells.append({"cell_type": "code", "metadata": {}, "source": text,
                      "execution_count": None, "outputs": []})
notebook = {"nbformat": 4, "nbformat_minor": 5,
            "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                         "language_info": {"name": "python"}}, "cells": cells}
for index, cell in enumerate(cells):
    cell["id"] = f"cell-{index:02d}"
target = source.with_suffix(".ipynb")
target.write_text(json.dumps(notebook, indent=2) + "\n")
print(target)
