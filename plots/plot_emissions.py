#!/usr/bin/env python3
"""Plot NO2 emissions for Tempo 30, 50, and 60 scenarios."""
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

plt.rcParams['font.sans-serif'] = ['Arial', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = Path(__file__).resolve().parent

DIFF_60_50 = 'Difference of tempo 60 and 50'
DIFF_30_50 = 'Difference of tempo 30 and 50'

SCENARIOS = [
    ('30_total', 'Tempo 30', 'o'),
    ('50_total', 'Tempo 50', 's'),
    ('60_total', 'Tempo 60', '^'),
]

DIFFERENCES = [
    (DIFF_60_50, 'Difference of tempo 60 and 50', 'o'),
    (DIFF_30_50, 'Difference of tempo 30 and 50', 's'),
]

PLOT_JOBS = [
    {
        'csv': 'result with all vehicle in 2026.csv',
        'prefix': 'result_with_all_vehicle_in_2026',
        'title': 'NO2 emission estimation of Landshuter Allee',
        'title_2014_2025': 'NO2 emission estimation of Landshuter Allee(2014-2025)',
        'title_2026': 'NO2 emission estimation of Landshuter Allee(2026)',
        'difference_title': 'NO2 emission difference compared with Tempo 50 of Landshuter Allee',
        'include_all_month_emission': True,
    },
    {
        'csv': 'monthly_emission_results.csv',
        'prefix': 'monthly_emission_results_with_tunnel_restrictions_in_2026',
        'title': 'NO2 emission estimation of Landshuter Allee with Tunnel restrictions in 2026',
        'title_2014_2025': 'NO2 emission estimation of Landshuter Allee with Tunnel restrictions in 2026(2014-2025)',
        'title_2026': 'NO2 emission estimation of Landshuter Allee with Tunnel restrictions in 2026(2026)',
        'difference_title': 'NO2 emission difference compared with Tempo 50 of Landshuter Allee with Tunnel restrictions in 2026',
        'include_all_month_emission': False,
    },
]


def load_results(csv_name):
    path = BASE_DIR / csv_name
    if not path.exists():
        print(f"Error: Data file not found at {path}")
        return None

    df = pd.read_csv(path)
    df['date'] = pd.to_datetime(df['month'], format='%Y%m')
    df['year'] = df['date'].dt.year
    df['month_num'] = df['date'].dt.month
    df = df.sort_values('date').reset_index(drop=True)

    for column in ['30_total', '50_total', '60_total', DIFF_60_50, DIFF_30_50]:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors='coerce')

    if DIFF_60_50 not in df.columns:
        df[DIFF_60_50] = df['60_total'] - df['50_total']
    if DIFF_30_50 not in df.columns:
        df[DIFF_30_50] = df['30_total'] - df['50_total']

    return df


def save_png(fig, file_stem):
    path = OUTPUT_DIR / f'{file_stem}.png'
    fig.savefig(path, dpi=900, bbox_inches='tight')
    print(f"PNG plot saved to: {path}")
    plt.close(fig)


def plot_lines(ax, df, x_col, series):
    for y_col, label, marker in series:
        ax.plot(df[x_col], df[y_col], marker=marker, label=label, linewidth=1.2, markersize=4)


def format_axis(ax, title, ylabel):
    ax.set_title(title, fontsize=13, fontweight='bold', pad=20)
    ax.set_xlabel('Month', fontsize=12, fontweight='bold')
    ax.set_ylabel(ylabel, fontsize=12, fontweight='bold')
    ax.tick_params(axis='x', rotation=45)
    ax.grid(True, alpha=0.3, linestyle='--')
    ax.legend(fontsize=11, loc='best', framealpha=0.9)


def plot_all_month_emissions(df, job):
    fig, ax = plt.subplots(figsize=(18, 6))
    plot_lines(ax, df, 'date', SCENARIOS)
    format_axis(ax, job['title'], 'NO2 Emission (kg)')
    fig.autofmt_xdate()
    fig.tight_layout()
    save_png(fig, f"{job['prefix']}_emission_all_months")


def plot_all_month_differences(df, job):
    fig, ax = plt.subplots(figsize=(18, 6))
    plot_lines(ax, df, 'date', DIFFERENCES)
    ax.axhline(0, color='black', linewidth=0.8, alpha=0.7)
    format_axis(ax, job['difference_title'], 'Difference in NO2 Emission (kg)')
    fig.autofmt_xdate()
    fig.tight_layout()
    save_png(fig, f"{job['prefix']}_difference_all_months")


def plot_years(df, years, title, file_stem, ncols=3):
    years = [year for year in years if year in set(df['year'])]
    if not years:
        print(f"No data available for {title}")
        return

    nrows = (len(years) + ncols - 1) // ncols
    fig, axes = plt.subplots(
        nrows=nrows,
        ncols=ncols,
        figsize=(6 * ncols, 4 * nrows),
        sharex=False,
        sharey=True,
    )
    axes = list(axes.flat) if hasattr(axes, 'flat') else [axes]

    for ax, year in zip(axes, years):
        year_df = df[df['year'] == year].sort_values('month_num')
        plot_lines(ax, year_df, 'month_num', SCENARIOS)
        ax.set_title(str(year), fontsize=12, fontweight='bold')
        ax.set_xlabel('Month', fontsize=10)
        ax.set_ylabel('NO2 Emission (kg)', fontsize=10)
        ax.set_xticks(range(1, 13))
        ax.grid(True, alpha=0.3, linestyle='--')

    for ax in axes[len(years):]:
        ax.set_visible(False)

    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc='lower center', ncol=3, fontsize=11, framealpha=0.9)
    fig.suptitle(title, fontsize=14, fontweight='bold', y=0.995)
    fig.tight_layout(rect=[0, 0.04, 1, 0.96])
    save_png(fig, file_stem)


def run_job(job):
    df = load_results(job['csv'])
    if df is None:
        return

    if job['include_all_month_emission']:
        plot_all_month_emissions(df, job)
    plot_all_month_differences(df, job)
    plot_years(df, range(2014, 2026), job['title_2014_2025'], f"{job['prefix']}_emission_2014_2025_by_year")
    plot_years(df, [2026], job['title_2026'], f"{job['prefix']}_emission_2026", ncols=1)


for plot_job in PLOT_JOBS:
    run_job(plot_job)
