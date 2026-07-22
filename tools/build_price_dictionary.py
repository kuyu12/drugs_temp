from pathlib import Path

import pandas as pd


def main() -> None:
    source_dir = Path("data_sources")
    output_path = source_dir / "drug_price_dictionary.csv"
    frames: list[pd.DataFrame] = []

    for path in sorted(source_dir.glob("*.xlsx")):
        df = pd.read_excel(path, sheet_name=0, header=1)
        cols = list(df.columns)
        name_col = "שם תכשיר" if "שם תכשיר" in cols else cols[1]
        code_col = "קוד" if "קוד" in cols else cols[0]
        frames.append(
            pd.DataFrame(
                {
                    "source_file": path.name,
                    "code": df[code_col],
                    "drug_name": df[name_col],
                }
            )
        )

    out = pd.concat(frames, ignore_index=True)
    out["drug_name"] = out["drug_name"].astype(str).str.strip()
    out["code"] = out["code"].astype(str).str.strip()
    out = out[out["drug_name"].ne("") & out["drug_name"].ne("nan")]
    out = out.drop_duplicates(subset=["drug_name", "code", "source_file"]).sort_values(["drug_name", "source_file"])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(output_path, index=False, encoding="utf-8")
    print(f"Wrote {len(out)} rows to {output_path}")


if __name__ == "__main__":
    main()
