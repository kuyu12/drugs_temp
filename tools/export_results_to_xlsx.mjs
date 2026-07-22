import fs from "node:fs/promises";
import path from "node:path";

import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

function columnName(index) {
  let name = "";
  let current = index;
  while (current > 0) {
    const remainder = (current - 1) % 26;
    name = String.fromCharCode(65 + remainder) + name;
    current = Math.floor((current - 1) / 26);
  }
  return name;
}

async function main() {
  const [, , inputCsvPath, outputXlsxPath] = process.argv;
  if (!inputCsvPath || !outputXlsxPath) {
    throw new Error("Usage: node export_results_to_xlsx.mjs <input.csv> <output.xlsx>");
  }

  const csvText = await fs.readFile(inputCsvPath, "utf8");
  const workbook = await Workbook.fromCSV(csvText, { sheetName: "Results" });
  const sheet = workbook.worksheets.getItemAt(0);
  const usedRange = sheet.getUsedRange();
  usedRange.format.autofitColumns();
  usedRange.format.autofitRows();
  sheet.freezePanes.freezeRows(1);

  const values = usedRange.values ?? [];
  const headerCount = Array.isArray(values[0]) ? values[0].length : 0;
  if (headerCount > 0) {
    const headerRange = sheet.getRange(`A1:${columnName(headerCount)}1`);
    headerRange.format.font.bold = true;
    headerRange.format.fill.color = "#DCE6F1";
    headerRange.format.borders = { preset: "all", style: "thin", color: "#B8CBE6" };
  }

  await fs.mkdir(path.dirname(outputXlsxPath), { recursive: true });
  const output = await SpreadsheetFile.exportXlsx(workbook);
  await output.save(outputXlsxPath);
}

await main();
