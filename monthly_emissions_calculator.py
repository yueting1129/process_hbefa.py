#!/usr/bin/env python3
"""Calculate monthly road-traffic emissions for Tempo 30/50/60.

This script:
- reads `traffic_volume_Vehcat.csv`, `EFA_Season.csv`, and `Level_of_service_share.csv`
- normalizes obvious formatting differences only
- computes monthly emissions per speed and vehicle category
- records missing/ambiguous/special-case items in a log
- writes `monthly_emission_results.xlsx` with two worksheets
"""
from __future__ import annotations

import argparse
import calendar
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


TRAFFIC_FILE = "traffic_volume_Vehcat.csv"
EFA_FILE = "EFA_Season.csv"
LOS_FILE = "Level_of_service_share.csv"
OUTPUT_FILE = "monthly_emission_results.csv"
ALL_VEHICLE_2026_OUTPUT_FILE = "result with all vehicle in 2026.csv"

# Skip these months (no data to calculate)
SKIP_MONTHS = {"202604", "202605", "202606", "202607", "202608", "202609", "202610", "202611", "202612"}

# ============================================================================
# CONFIGURATION: Adjust these constants if input files or definitions change.
# ============================================================================

SPEEDS = ["30", "50", "60"]
VEHCATS = ["pass. car", "LCV", "HGV", "urban bus"]  # Use lowercase to match most CSV columns

# Road type in emission-factor table varies by speed; this mapping reflects reality.
# If the EFA_Season.csv file structure changes, update this.
ROADTYPE_BY_SPEED = {"30": "Distr", "50": "Trunk-City", "60": "Trunk-City"}

# Vehicle-category normalization: maps input variations to canonical forms.
# If traffic_volume_Vehcat.csv uses different labels, add them here.
VEHCAT_MAP = {
    "pass. car": "pass. car",
    "pass.car": "pass. car",
    "pass car": "pass. car",
    "pass. Car": "pass. car",  # Also accept uppercase variant
    "lcv": "LCV",
    "hgv": "HGV",
    "urban bus": "urban bus",
    "urbanbus": "urban bus",
}

# Level-of-Service mapping: traffic-input labels to emission-factor table labels.
# traffic_volume share file uses "Freeflow", "Heavy", "Saturated"
# EFA_Season.csv uses "Freeflow", "Heavy", "Satur."
LOS_FACTOR = {"freeflow": "Freeflow", "heavy": "Heavy", "saturated": "Satur."}

# Year-round / seasonal labels in EFA_Season.csv AmbientCondPattern column.
YEARROUND_LABELS = {"", "annual", "year-round", "year round", "all year"}

# Calendar-based season assignment (Northern Hemisphere).
# Adjust if a different seasonal definition is required.
SEASON_BY_MONTH = {
    12: "Winter", 1: "Winter", 2: "Winter",
    3: "Spring", 4: "Spring", 5: "Spring",
    6: "Summer", 7: "Summer", 8: "Summer",
    9: "Autumn", 10: "Autumn", 11: "Autumn",
}

OUTPUT_COLUMNS = [
    "month",
    "30_total",
    "30_pass.Car",
    "30_LCV",
    "30_HGV",
    "30_urban_bus",
    "50_total",
    "50_pass.Car",
    "50_LCV",
    "50_HGV",
    "50_urban_bus",
    "60_total",
    "60_pass.Car",
    "60_LCV",
    "60_HGV",
    "60_urban_bus",
    "Difference of tempo 60 and 50",
    "Difference of tempo 30 and 50",
]

LOG_COLUMNS = ["month", "speed", "vehcat", "input_type", "matching_conditions", "reason"]
OUTPUT_VEHCAT_SUFFIX = {"pass. car": "pass.Car", "LCV": "LCV", "HGV": "HGV", "urban bus": "urban_bus"}


def norm_text(value: object) -> str:
    """Normalize a text value for matching: case-insensitive, trim, collapse whitespace."""
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"nan", "nat", "none"}:
        return ""
    return " ".join(text.split()).lower()


def canonical_vehicle_category(value: object) -> Optional[str]:
    key = norm_text(value)
    return VEHCAT_MAP.get(key)


def canonical_los(value: object) -> Optional[str]:
    key = norm_text(value)
    if key in {"freeflow", "heavy", "saturated", "satur."}:
        return key
    return None


def canonical_factor_los(value: object) -> Optional[str]:
    key = canonical_los(value)
    if key is None:
        return None
    if key == "satur.":
        return "Satur."
    return LOS_FACTOR.get(key, None)


def season_from_month(month_yyyymm: str) -> str:
    month = int(str(month_yyyymm)[4:6])
    return SEASON_BY_MONTH[month]


def year_month_from_yyyymm(month_yyyymm: str) -> Tuple[int, int]:
    s = str(month_yyyymm)
    return int(s[:4]), int(s[4:6])


def roadtype_from_speed(speed: str) -> str:
    return ROADTYPE_BY_SPEED[str(speed)]


def parse_numeric(series):
    return pd.to_numeric(series, errors="coerce")


def load_traffic_volume(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str, na_filter=False)
    df = df.loc[:, ~df.columns.str.match(r"^Unnamed")].copy()
    df["Year"] = df["Year"].astype(str).str.strip()
    df["Month"] = df["Month"].astype(str).str.strip()

    # Standardize numeric columns
    for col in df.columns:
        if col not in {"Year", "Month"}:
            df[col] = parse_numeric(df[col].replace("", np.nan))

    return df


def load_los_shares(path: Path) -> Dict[str, Dict[str, float]]:
    df = pd.read_csv(path, dtype=str, na_filter=False)
    df = df.copy()
    col_map: Dict[str, str] = {}
    for col in df.columns:
        norm = norm_text(col).replace("_", " ")
        if norm.startswith("60"):
            col_map["60"] = col
        elif norm.startswith("50"):
            col_map["50"] = col
        elif norm.startswith("30"):
            col_map["30"] = col
    if set(col_map) != set(SPEEDS):
        raise ValueError(f"Could not identify LOS columns from {list(df.columns)}")

    out: Dict[str, Dict[str, float]] = {}
    for speed in SPEEDS:
        col = col_map[speed]
        sub = {}
        for _, row in df.iterrows():
            los = canonical_los(row[df.columns[0]])
            if los is None:
                continue
            sub[los] = float(row[col]) if str(row[col]).strip() != "" else np.nan
        if set(sub) != {"freeflow", "heavy", "saturated"}:
            raise ValueError(f"LOS share file is missing rows for speed {speed}: {sub}")
        out[speed] = sub
    return out


def validate_and_normalize_los_shares(
    shares: Dict[str, Dict[str, float]],
    logs: List[dict],
) -> Dict[str, Dict[str, Optional[float]]]:
    normalized: Dict[str, Dict[str, Optional[float]]] = {}
    for speed, vals in shares.items():
        total = sum(v for v in vals.values() if pd.notna(v))
        if abs(total - 1.0) <= 0.001:
            normalized[speed] = vals.copy()
        elif abs(total - 100.0) <= 0.001:
            normalized[speed] = {k: v / 100.0 if pd.notna(v) else np.nan for k, v in vals.items()}
        else:
            normalized[speed] = {k: None for k in vals}
            logs.append(
                {
                    "month": "",
                    "speed": speed,
                    "vehcat": "",
                    "input_type": "LOS share",
                    "matching_conditions": f"{speed} shares",
                    "reason": f"invalid LOS-share total ({total})",
                }
            )
    return normalized


def load_efa_factors(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str, na_filter=False)
    expected = {"Year", "VehCat", "RoadType", "Speed", "Level of Service", "EFA_weighted", "AmbientCondPattern"}
    missing = expected - set(df.columns)
    if missing:
        raise ValueError(f"EFA file missing expected columns: {sorted(missing)}")
    df = df.copy()
    df["Year"] = pd.to_numeric(df["Year"], errors="coerce").astype("Int64")
    df["Speed"] = pd.to_numeric(df["Speed"], errors="coerce").astype("Int64")
    df["EFA_weighted"] = pd.to_numeric(df["EFA_weighted"], errors="coerce")
    df["VehCat_norm"] = df["VehCat"].map(canonical_vehicle_category)
    df["RoadType_norm"] = df["RoadType"].map(norm_text)
    df["LOS_norm"] = df["Level of Service"].map(canonical_factor_los)
    df["Ambient_norm"] = df["AmbientCondPattern"].map(norm_text)
    return df


def build_factor_lookups(df: pd.DataFrame) -> Tuple[dict, dict]:
    seasonal: Dict[Tuple[int, str, str, str, str, str], set] = {}
    year_round: Dict[Tuple[int, str, str, str, str], set] = {}

    for _, row in df.iterrows():
        year = int(row["Year"])
        vehcat = row["VehCat_norm"]
        roadtype = row["RoadType_norm"]
        speed = str(int(row["Speed"])) if pd.notna(row["Speed"]) else ""
        los = row["LOS_norm"]
        ef = row["EFA_weighted"]
        if vehcat is None or los is None or pd.isna(ef) or speed == "":
            continue

        ambient = row["Ambient_norm"]
        if ambient in YEARROUND_LABELS:
            year_round.setdefault((year, vehcat, roadtype, speed, los), set()).add(float(ef))
        else:
            seasonal.setdefault((year, vehcat, roadtype, speed, los, ambient), set()).add(float(ef))
    return seasonal, year_round


def lookup_emission_factor(
    year: int,
    vehcat: str,
    speed: str,
    los: str,
    season: str,
    seasonal_lookup: dict,
    year_round_lookup: dict,
) -> Tuple[Optional[float], Optional[dict]]:
    roadtype = norm_text(ROADTYPE_BY_SPEED[str(speed)])
    seasonal_key = (year, vehcat, roadtype, speed, los, season.lower())
    year_round_key = (year, vehcat, roadtype, speed, los)

    seasonal_vals = seasonal_lookup.get(seasonal_key, set())
    if seasonal_vals:
        if len(seasonal_vals) == 1:
            return next(iter(seasonal_vals)), None
        return None, {
            "input_type": "emission factor",
            "matching_conditions": f"year={year}; vehcat={vehcat}; speed={speed}; los={los}; season={season}; roadtype={roadtype}",
            "reason": "duplicate/ambiguous emission-factor match",
        }

    year_round_vals = year_round_lookup.get(year_round_key, set())
    if year_round_vals:
        if len(year_round_vals) == 1:
            return next(iter(year_round_vals)), None
        return None, {
            "input_type": "emission factor",
            "matching_conditions": f"year={year}; vehcat={vehcat}; speed={speed}; los={los}; year-round; roadtype={roadtype}",
            "reason": "duplicate/ambiguous emission-factor match",
        }

    return None, {
        "input_type": "emission factor",
        "matching_conditions": f"year={year}; vehcat={vehcat}; speed={speed}; los={los}; season={season}; roadtype={roadtype}",
        "reason": "missing emission factor",
    }


def calculate_weighted_ef(
    year: int,
    vehcat: str,
    speed: str,
    season: str,
    shares: Dict[str, Optional[float]],
    seasonal_lookup: dict,
    year_round_lookup: dict,
    month: str,
    logs: List[dict],
) -> Optional[float]:
    """
    Compute the weighted average emission factor for a vehicle/speed combination.

    The weighted EF is:
      EF_weighted = freeflow_share × EF(Freeflow)
                  + heavy_share × EF(Heavy)
                  + saturated_share × EF(Saturated)

    where each EF is looked up from the emission-factor table, using the year,
    vehicle category, speed, Level of Service, and season.
    """
    factors = {}
    for los in ["freeflow", "heavy", "saturated"]:
        ef, log = lookup_emission_factor(year, vehcat, speed, LOS_FACTOR[los], season, seasonal_lookup, year_round_lookup)
        if log is not None:
            log = dict(log)
            log.update({"month": month, "speed": speed, "vehcat": vehcat})
            logs.append(log)
            return None
        factors[los] = ef

    if any(shares.get(los) is None or pd.isna(shares.get(los)) for los in ["freeflow", "heavy", "saturated"]):
        logs.append(
            {
                "month": month,
                "speed": speed,
                "vehcat": vehcat,
                "input_type": "LOS share",
                "matching_conditions": f"speed={speed}",
                "reason": "invalid LOS-share total",
            }
        )
        return None

    return (
        shares["freeflow"] * factors["freeflow"]
        + shares["heavy"] * factors["heavy"]
        + shares["saturated"] * factors["saturated"]
    )


def calculate_monthly_emissions(
    traffic: pd.DataFrame,
    los_shares: Dict[str, Dict[str, Optional[float]]],
    seasonal_lookup: dict,
    year_round_lookup: dict,
    exclude_hgv_202602_202603: bool = True,
) -> Tuple[pd.DataFrame, List[dict], Dict[str, int]]:
    """
    Calculate monthly road-traffic emissions for each speed scenario and vehicle category.

    For each month, speed, and vehicle category:
      1. Look up the weighted emission factor (weighted by Level of Service shares)
      2. Compute monthly emission = days_in_month × 2.5 km × daily_volume × weighted_EF
      3. Aggregate into speed totals

    Special case: February and March 2026 (202602, 202603) exclude HGV from totals
    unless exclude_hgv_202602_202603 is set to False.

    Returns:
      - emissions DataFrame with columns [month, 30_total, 30_pass.Car, ..., 60_urban_bus]
      - logs List of dicts recording missing data, exclusions, and anomalies
      - stats Dict with counts of negative traffic, blanks, etc.
    """
    logs: List[dict] = []
    output_rows: List[dict] = []
    stats = {"negative_traffic": 0, "negative_emission": 0, "missing_lookup": 0, "blank_category": 0, "excluded_hgv": 0}

    month_order = traffic["Month"].astype(str).str.strip().tolist()
    seen_months = set()

    traffic_cols = {
        (speed, vehcat): f"{speed}_{vehcat}" for speed in SPEEDS for vehcat in VEHCATS
    }

    # Build case-insensitive column lookup map
    col_norm_map = {}
    for col in traffic.columns:
        col_norm_map[norm_text(col)] = col

    for _, row in traffic.iterrows():
        month = str(row["Month"]).strip()
        if month in SKIP_MONTHS:
            continue
        if month in seen_months:
            logs.append(
                {
                    "month": month,
                    "speed": "",
                    "vehcat": "",
                    "input_type": "traffic volume",
                    "matching_conditions": "month row",
                    "reason": "duplicate month in traffic input",
                }
            )
            continue
        seen_months.add(month)

        year, month_num = year_month_from_yyyymm(month)
        days_in_month = calendar.monthrange(year, month_num)[1]
        season = season_from_month(month)
        out: Dict[str, object] = {"month": month}

        for speed in SPEEDS:
            speed_values: Dict[str, Optional[float]] = {}
            for vehcat in VEHCATS:
                col_name = traffic_cols[(speed, vehcat)]
                # Case-insensitive lookup
                norm_col_name = norm_text(col_name)
                actual_col_name = col_norm_map.get(norm_col_name)

                # Use OUTPUT_VEHCAT_SUFFIX for consistent column naming in output
                output_vehcat_key = OUTPUT_VEHCAT_SUFFIX[vehcat]
                output_col_key = f"{speed}_{output_vehcat_key}"

                matching_conditions = f"speed={speed}; vehcat={vehcat}; source_column={col_name}"
                if exclude_hgv_202602_202603 and month in {"202602", "202603"} and vehcat == "HGV":
                    out[output_col_key] = None
                    logs.append(
                        {
                            "month": month,
                            "speed": speed,
                            "vehcat": vehcat,
                            "input_type": "special rule",
                            "matching_conditions": matching_conditions,
                            "reason": "HGV excluded by design for 202602/202603",
                        }
                    )
                    stats["excluded_hgv"] += 1
                    speed_values[vehcat] = None
                    continue

                if actual_col_name is None:
                    raw_volume = np.nan
                else:
                    raw_volume = row[actual_col_name] if actual_col_name in row.index else np.nan
                volume = pd.to_numeric(raw_volume, errors="coerce") if pd.notna(raw_volume) and str(raw_volume).strip() != "" else np.nan

                if pd.isna(volume):
                    out[output_col_key] = None
                    logs.append(
                        {
                            "month": month,
                            "speed": speed,
                            "vehcat": vehcat,
                            "input_type": "traffic volume",
                            "matching_conditions": matching_conditions,
                            "reason": "missing traffic volume",
                        }
                    )
                    stats["blank_category"] += 1
                    speed_values[vehcat] = None
                    continue

                if float(volume) < 0:
                    out[output_col_key] = None
                    logs.append(
                        {
                            "month": month,
                            "speed": speed,
                            "vehcat": vehcat,
                            "input_type": "traffic volume",
                            "matching_conditions": matching_conditions,
                            "reason": "negative traffic volume",
                        }
                    )
                    stats["negative_traffic"] += 1
                    speed_values[vehcat] = None
                    continue

                weighted_ef = calculate_weighted_ef(
                    year=year,
                    vehcat=vehcat,
                    speed=speed,
                    season=season,
                    shares=los_shares[speed],
                    seasonal_lookup=seasonal_lookup,
                    year_round_lookup=year_round_lookup,
                    month=month,
                    logs=logs,
                )
                if weighted_ef is None:
                    out[output_col_key] = None
                    speed_values[vehcat] = None
                    stats["missing_lookup"] += 1
                    continue

                emission = days_in_month * 2.5 * float(volume) * weighted_ef
                if emission < 0:
                    logs.append(
                        {
                            "month": month,
                            "speed": speed,
                            "vehcat": vehcat,
                            "input_type": "calculated emission",
                            "matching_conditions": f"year={year}; season={season}; speed={speed}; vehcat={vehcat}",
                            "reason": "negative emission",
                        }
                    )
                    stats["negative_emission"] += 1
                    out[output_col_key] = None
                    speed_values[vehcat] = None
                else:
                    out[output_col_key] = float(emission)
                    speed_values[vehcat] = float(emission)

            # totals
            if exclude_hgv_202602_202603 and month in {"202602", "202603"}:
                required = ["pass. car", "LCV", "urban bus"]
            else:
                required = VEHCATS
            total_key = f"{speed}_total"
            if any(speed_values.get(v) is None for v in required):
                out[total_key] = None
                logs.append(
                    {
                        "month": month,
                        "speed": speed,
                        "vehcat": "",
                        "input_type": "total",
                        "matching_conditions": f"speed={speed}; required={','.join(required)}",
                        "reason": "blank total due to blank component(s)",
                    }
                )
            else:
                required_values = [speed_values[v] for v in required if speed_values[v] is not None]
                total = sum(float(v) for v in required_values)
                out[total_key] = 0.0 if abs(total) == 0.0 else float(total)

        if out.get("60_total") is not None and out.get("50_total") is not None:
            out["Difference of tempo 60 and 50"] = float(out["60_total"]) - float(out["50_total"])
        else:
            out["Difference of tempo 60 and 50"] = None

        if out.get("30_total") is not None and out.get("50_total") is not None:
            out["Difference of tempo 30 and 50"] = float(out["30_total"]) - float(out["50_total"])
        else:
            out["Difference of tempo 30 and 50"] = None

        output_rows.append(out)

    out_df = pd.DataFrame(output_rows)
    out_df = out_df.reindex(columns=OUTPUT_COLUMNS)

    # Align output order with the order of appearance in traffic input.
    out_df["month"] = pd.Categorical(out_df["month"], categories=month_order, ordered=True)
    out_df = out_df.sort_values("month", kind="stable").reset_index(drop=True)
    out_df["month"] = out_df["month"].astype(str)

    return out_df, logs, stats


def perform_quality_checks(
    traffic: pd.DataFrame,
    emissions: pd.DataFrame,
    logs: List[dict],
    los_normalized: Dict[str, Dict[str, Optional[float]]],
    seasonal_lookup: dict,
    year_round_lookup: dict,
    exclude_hgv_202602_202603: bool = True,
) -> Dict[str, object]:
    results: Dict[str, object] = {}
    results["unique_months_input"] = traffic["Month"].astype(str).nunique(dropna=True)
    results["output_months"] = len(emissions)
    results["duplicate_month_rows"] = int(emissions["month"].duplicated().sum())
    results["los_totals"] = {speed: sum(v for v in vals.values() if v is not None) for speed, vals in los_normalized.items()}
    results["unresolved_factor_logs"] = [
        log for log in logs if log.get("input_type") == "emission factor" and "missing emission factor" in str(log.get("reason", "")) or "duplicate/ambiguous emission-factor match" in str(log.get("reason", ""))
    ]

    # Check totals against component sums.
    total_mismatches = []
    for _, row in emissions.iterrows():
        month = row["month"]
        for speed in SPEEDS:
            total = row[f"{speed}_total"]
            required_vehcats = (
                ["pass. car", "LCV", "urban bus"]
                if exclude_hgv_202602_202603 and month in {"202602", "202603"}
                else VEHCATS
            )
            required = [row[f"{speed}_{OUTPUT_VEHCAT_SUFFIX[v]}" ] for v in required_vehcats]
            if pd.notna(total):
                if any(pd.isna(v) for v in required):
                    total_mismatches.append((month, speed, "total present despite blank components"))
                else:
                    expected = sum(float(v) for v in required)
                    if not np.isclose(float(total), expected, rtol=0, atol=1e-9):
                        total_mismatches.append((month, speed, f"expected {expected}, got {total}"))
    results["total_mismatches"] = total_mismatches
    return results


def write_output(emissions: pd.DataFrame, logs: List[dict], output_path: Path) -> None:
    """Write emissions to CSV. Optionally write logs to a separate CSV."""
    # Convert from g to kg by dividing by 1000
    emissions_copy = emissions.copy()
    for col in emissions_copy.columns:
        if col != "month" and pd.api.types.is_numeric_dtype(emissions_copy[col]):
            emissions_copy[col] = emissions_copy[col] / 1000.0
    
    emissions_copy.to_csv(output_path, index=False)
    
    # Optionally: also write logs to a separate file
    log_path = output_path.parent / (output_path.stem + "_log.csv")
    log_df = pd.DataFrame(logs)
    if log_df.empty:
        log_df = pd.DataFrame(columns=LOG_COLUMNS)
    else:
        for col in LOG_COLUMNS:
            if col not in log_df.columns:
                log_df[col] = ""
        log_df = log_df[LOG_COLUMNS]
    log_df.to_csv(log_path, index=False)


def main() -> int:
    parser = argparse.ArgumentParser(description="Calculate monthly road-traffic emissions for Tempo 30/50/60.")
    parser.add_argument("--input-dir", default=str(Path(__file__).resolve().parent), help="Directory containing the CSV input files")
    parser.add_argument("--output", default=str(Path(__file__).resolve().parent / OUTPUT_FILE), help="Output Excel workbook path")
    args = parser.parse_args()

    input_dir = Path(args.input_dir).resolve()
    output_path = Path(args.output).resolve()

    traffic_path = input_dir / TRAFFIC_FILE
    efa_path = input_dir / EFA_FILE
    los_path = input_dir / LOS_FILE

    traffic = load_traffic_volume(traffic_path)
    los_shares_raw = load_los_shares(los_path)
    shared_logs: List[dict] = []
    los_shares = validate_and_normalize_los_shares(los_shares_raw, shared_logs)
    efa = load_efa_factors(efa_path)
    seasonal_lookup, year_round_lookup = build_factor_lookups(efa)

    emissions, logs, stats = calculate_monthly_emissions(traffic, los_shares, seasonal_lookup, year_round_lookup)
    logs = shared_logs + logs
    qc = perform_quality_checks(traffic, emissions, logs, los_shares, seasonal_lookup, year_round_lookup)

    all_vehicle_output_path = output_path.parent / ALL_VEHICLE_2026_OUTPUT_FILE
    all_vehicle_emissions, all_vehicle_logs, all_vehicle_stats = calculate_monthly_emissions(
        traffic,
        los_shares,
        seasonal_lookup,
        year_round_lookup,
        exclude_hgv_202602_202603=False,
    )
    all_vehicle_logs = shared_logs + all_vehicle_logs
    all_vehicle_qc = perform_quality_checks(
        traffic,
        all_vehicle_emissions,
        all_vehicle_logs,
        los_shares,
        seasonal_lookup,
        year_round_lookup,
        exclude_hgv_202602_202603=False,
    )
    write_output(all_vehicle_emissions, all_vehicle_logs, all_vehicle_output_path)
    write_output(emissions, logs, output_path)

    blank_output_cells = int(emissions.isna().sum().sum())
    all_vehicle_blank_output_cells = int(all_vehicle_emissions.isna().sum().sum())
    print("Input files used:")
    print(f"  - {traffic_path.name}")
    print(f"  - {efa_path.name}")
    print(f"  - {los_path.name}")
    print("Detected columns:")
    print(f"  traffic_volume_Vehcat.csv -> {list(traffic.columns)}")
    print(f"  EFA_Season.csv -> {list(efa.columns[:7])}")
    print(f"  Level_of_service_share.csv -> {list(pd.read_csv(los_path, dtype=str, na_filter=False).columns)}")
    print(f"Months processed: {len(emissions)}")
    print(f"Blank output cells: {blank_output_cells}")
    print(
        "Main issue counts: "
        f"missing traffic volume={sum('missing traffic volume' in str(x.get('reason', '')) for x in logs)}, "
        f"missing emission factor={sum('missing emission factor' in str(x.get('reason', '')) for x in logs)}, "
        f"duplicate/ambiguous factor={sum('duplicate/ambiguous emission-factor match' in str(x.get('reason', '')) for x in logs)}, "
        f"HGV excluded={sum('HGV excluded by design' in str(x.get('reason', '')) for x in logs)}, "
        f"invalid LOS-share total={sum('invalid LOS-share total' in str(x.get('reason', '')) for x in logs)}"
    )
    print(f"Output written to: {output_path}")
    print(f"All-vehicle 2026 output written to: {all_vehicle_output_path}")
    print("Quality checks:")
    print(f"  unique_months_input={qc['unique_months_input']}, output_months={qc['output_months']}, duplicate_month_rows={qc['duplicate_month_rows']}")
    print(f"  LOS totals={qc['los_totals']}")
    print(f"  unresolved_factor_logs={len(qc['unresolved_factor_logs'])}")
    print(f"  total_mismatches={len(qc['total_mismatches'])}")
    print(f"  negative traffic={stats['negative_traffic']}, negative emissions={stats['negative_emission']}")
    print("All-vehicle 2026 quality checks:")
    print(f"  blank output cells={all_vehicle_blank_output_cells}")
    print(f"  total_mismatches={len(all_vehicle_qc['total_mismatches'])}")
    print(f"  HGV excluded={all_vehicle_stats['excluded_hgv']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())










