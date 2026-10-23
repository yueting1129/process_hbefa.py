from pathlib import Path

import matplotlib
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates


CSV_PATH = Path("traffic_volume_Vehcat.csv")
OUTPUT_PATH = Path("traffic_volume_DTV_monthly_line.png")


def main() -> None:
    df = pd.read_csv(CSV_PATH)
    df = df[["Month", "50_DTV", "30_DTV"]].copy()

    df["Month"] = pd.to_datetime(
        df["Month"].astype("Int64").astype(str),
        format="%Y%m",
        errors="coerce",
    )
    df["50_DTV"] = pd.to_numeric(df["50_DTV"], errors="coerce")
    df["30_DTV"] = pd.to_numeric(df["30_DTV"], errors="coerce")
    df = df.dropna(subset=["Month", "50_DTV", "30_DTV"]).sort_values("Month")

    fig, ax = plt.subplots(figsize=(16, 5.6), dpi=180)
    ax.plot(
        df["Month"],
        df["50_DTV"],
        marker="o",
        linewidth=2.2,
        markersize=2.4,
        color="#2563eb",
        label="50_DTV",
    )
    ax.plot(
        df["Month"],
        df["30_DTV"],
        marker="s",
        linewidth=2.2,
        markersize=2.4,
        color="#d97706",
        label="30_DTV",
    )

    ax.set_title("Estimated Monthly Daily Traffic Volume by Vehicle Category", fontsize=13, pad=12)
    ax.set_xlabel("Month")
    ax.set_ylabel("DTV (Daily Traffic Volume)")
    ax.grid(True, axis="y", color="#d9dee7", linewidth=0.8)
    ax.grid(True, axis="x", color="#eef1f5", linewidth=0.5)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, loc="best")
    ax.ticklabel_format(style="plain", axis="y")
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    fig.autofmt_xdate(rotation=35, ha="right")
    fig.tight_layout()
    fig.savefig(OUTPUT_PATH, bbox_inches="tight")

    print(f"Saved: {OUTPUT_PATH.resolve()}")
    print(f"Rows plotted: {len(df)}")
    if not df.empty:
        months = df["Month"].dt.strftime("%Y-%m")
        print(f"Date range: {months.min()} to {months.max()}")


if __name__ == "__main__":
    main()
