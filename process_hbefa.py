#!/usr/bin/env python3
"""
process_hbefa.py

Usage:
  python process_hbefa.py --input-dir "E:/.../HBEFA DATA" --output combined.csv

This script scans a directory for CSV files, extracts these input columns:
  VehCat, Year, TrafficSit, EFA_weighted, AmbientCondPattern

And writes a combined CSV with columns:
  VehCat, Year, RoadType, Speed, Level of Service, EFA_weighted, AmbientCondPattern

TrafficSit is expected in the form like: URB/Distr/30/St+Go
  RoadType -> 2nd segment (Distr)
  Speed -> 3rd segment (30)
  Level of Service -> 4th segment (St+Go)

The script attempts to be robust to capitalization and small variations in column names.
"""
from __future__ import annotations
import argparse
import os
import sys
import pandas as pd
from glob import glob
from typing import List


EXPECTED_COLUMNS = ["VehCat", "Year", "TrafficSit", "EFA_weighted", "AmbientCondPattern"]


def find_csv_files(input_dir: str) -> List[str]:
    patterns = [os.path.join(input_dir, "*.CSV"), os.path.join(input_dir, "*.csv")]
    files = []
    for p in patterns:
        files.extend(glob(p))
    files = sorted(set(files))
    return files


def match_columns(df_columns: List[str]) -> dict:
    """Return mapping from expected column name -> actual column name in dataframe (or None)."""
    mapping = {}
    lower_map = {c.strip().lower(): c for c in df_columns}
    for exp in EXPECTED_COLUMNS:
        key = exp.strip().lower()
        mapped = None
        # direct match
        if key in lower_map:
            mapped = lower_map[key]
        else:
            # try flexible matches: remove non-alnum
            def norm(s: str) -> str:
                return ''.join(ch.lower() for ch in s if ch.isalnum())

            nkey = norm(exp)
            for col in df_columns:
                if norm(col) == nkey:
                    mapped = col
                    break
        mapping[exp] = mapped
    return mapping


def split_trafficsit(ts: str):
    """Split a TrafficSit string into components. Return (roadtype, speed, level_of_service)."""
    if pd.isna(ts):
        return "", "", ""
    s = str(ts).strip()
    if s == "":
        return "", "", ""
    parts = [p.strip() for p in s.split('/')]
    # Example: ['URB','Distr','30','St+Go'] -> RoadType=parts[1], Speed=parts[2], LOS=parts[3]
    road = parts[1] if len(parts) > 1 else ""
    speed = parts[2] if len(parts) > 2 else ""
    los = parts[3] if len(parts) > 3 else ""
    return road, speed, los


def process_file(path: str) -> pd.DataFrame:
    # read CSV
    df = pd.read_csv(path, dtype=str, encoding='utf-8', engine='python', on_bad_lines='skip')

    if df.shape[0] == 0:
        return pd.DataFrame(columns=["VehCat", "Year", "RoadType", "Speed", "Level of Service", "EFA_weighted", "AmbientCondPattern"])

    mapping = match_columns(list(df.columns))
    missing = [k for k, v in mapping.items() if v is None]
    if missing:
        print(f"Warning: file {os.path.basename(path)} is missing columns: {missing}. Missing columns will be empty in output.")

    # extract columns (or fill with empty strings)
    extracted = pd.DataFrame()
    for col in EXPECTED_COLUMNS:
        actual = mapping.get(col)
        if actual is not None:
            extracted[col] = df[actual].astype(str)
        else:
            extracted[col] = ""

    # split TrafficSit
    roads = extracted['TrafficSit'].apply(split_trafficsit)
    extracted['RoadType'] = roads.apply(lambda t: t[0])
    extracted['Speed'] = roads.apply(lambda t: t[1])
    extracted['Level of Service'] = roads.apply(lambda t: t[2])

    # Build final dataframe with desired column order
    final = pd.DataFrame()
    final['Year'] = extracted['Year']
    final['VehCat'] = extracted['VehCat']
    final['RoadType'] = extracted['RoadType']
    final['Speed'] = extracted['Speed']
    final['Level of Service'] = extracted['Level of Service']
    final['EFA_weighted'] = extracted['EFA_weighted']
    final['AmbientCondPattern'] = extracted['AmbientCondPattern']

    return final


def main():
    parser = argparse.ArgumentParser(description='Process HBEFA CSV files and combine selected columns.')
    parser.add_argument('--input-dir', '-i', help='Directory containing CSV files', default='.')
    parser.add_argument('--output', '-o', help='Output CSV file path', default='combined_hbefa.csv')
    parser.add_argument('--drop-duplicates', action='store_true', help='Drop duplicate rows in the combined output')
    args = parser.parse_args()

    input_dir = os.path.abspath(args.input_dir)
    if not os.path.isdir(input_dir):
        print(f"Error: input directory does not exist: {input_dir}")
        sys.exit(1)

    out_abs = os.path.abspath(args.output)
    files = find_csv_files(input_dir)
    # exclude the output file if it's in the same folder
    files = [f for f in files if os.path.abspath(f) != out_abs]
    if not files:
        print(f"No CSV files found in {input_dir}")
        sys.exit(0)

    parts = []
    for f in files:
        try:
            df = process_file(f)
            if df is not None and df.shape[0] > 0:
                parts.append(df)
        except Exception as e:
            print(f"Error processing {f}: {e}")

    if not parts:
        print("No data extracted from CSVs.")
        sys.exit(0)

    combined = pd.concat(parts, ignore_index=True, sort=False)
    if args.drop_duplicates:
        before = combined.shape[0]
        combined = combined.drop_duplicates()
        after = combined.shape[0]
        # duplicates dropped silently

    # write output
    out_path = os.path.abspath(args.output)
    combined.to_csv(out_path, index=False, encoding='utf-8')


if __name__ == '__main__':
    main()

