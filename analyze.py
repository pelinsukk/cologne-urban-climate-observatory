"""Descriptive analysis of paired Cool City Lab box measurements."""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd

SURFACES = {15: "sand", 16: "grass", 18: "gravel", 19: "tar"}
START, END = pd.Timestamp("2021-06-07"), pd.Timestamp("2021-07-14")
COLORS = {"sand": "#aa603a", "grass": "#228365", "gravel": "#638198", "tar": "#262637"}


def read_boxes(path):
    series, quality = {}, {}
    with pd.ExcelFile(path, engine="openpyxl") as book:
        for sensor, surface in SURFACES.items():
            names = [name for name in book.sheet_names if f"({sensor})" in name]
            if len(names) != 1:
                raise ValueError(f"Expected one worksheet for sensor {sensor}, found {names}")
            raw = pd.read_excel(book, sheet_name=names[0], skiprows=2, header=None, usecols=[0, 1])
            time = pd.to_datetime(raw.iloc[:, 0], format="mixed", dayfirst=True, errors="coerce")
            temp = pd.to_numeric(raw.iloc[:, 1].astype("string").str.replace(",", ".", regex=False),
                                 errors="coerce").replace([float("inf"), float("-inf")], float("nan"))
            values = pd.Series(temp.array, index=time, name=surface).dropna()
            values = values.loc[values.index.notna()].astype(float)
            if values.index.tz is not None:
                raise ValueError("Expected unzoned box timestamps; review source changes.")
            quality[surface] = {"source_rows": len(raw), "missing_or_invalid_temperature": int(temp.isna().sum()),
                                "invalid_timestamp": int(time.isna().sum()),
                                "duplicate_valid_timestamps": int(values.index.duplicated().sum())}
            series[surface] = values.groupby(level=0).mean().sort_index()
    return series, quality


def paired_hours(series, minimum):
    hourly = {}
    for name, values in series.items():
        bins = values.loc[(values.index >= START) & (values.index < END)].resample("h")
        hourly[name] = bins.mean().where(bins.count() >= minimum)
    return pd.DataFrame(hourly).reindex(pd.date_range(START, END, freq="h", inclusive="left")).dropna()


def read_weather(path):
    data = pd.read_csv(path, usecols=["date_end", "airtemp"], dtype="string")
    time = pd.to_datetime(data.pop("date_end"), format="mixed", utc=True, errors="coerce")
    data = data.apply(pd.to_numeric, errors="coerce")
    data.index = pd.DatetimeIndex(time, name="utc_interval_end")
    data = data.loc[data.index.notna()]
    return data.groupby(level=0).mean().sort_index()


def summarize(paired):
    if paired.empty:
        raise ValueError("No common hours meet the coverage rule within the analysis window.")
    delta = paired.drop(columns="tar").rsub(paired["tar"], axis=0)
    return {name: {"mean_c": float(v.mean()), "median_c": float(v.median()),
                   "p10_c": float(v.quantile(.1)), "p90_c": float(v.quantile(.9)),
                   "tar_warmer_fraction": float(v.gt(0).mean())}
            for name, v in delta.items()}


def plot(paired, weather, output):
    fig, axs = plt.subplots(3, 1, figsize=(10, 9), layout="constrained")
    hours = pd.date_range(START, END, freq="h", inclusive="left")
    daily = paired.reindex(hours).resample("D")
    mean = daily.mean().where(daily.count() >= 18)
    cycle = paired.groupby(paired.index.hour).mean()
    for surface in paired.columns:
        axs[0].plot(mean.index, mean[surface], label=surface.capitalize(), color=COLORS[surface])
        axs[1].plot(cycle.index, cycle[surface], color=COLORS[surface])
    axs[0].set(title="A. Daily box means (≥18 paired hours)", ylabel="Box temperature (°C)")
    axs[0].legend(ncol=4, loc="upper right")
    axs[1].set(title="B. Mean by recorded box-clock hour", xlabel="Recorded hour (timezone unknown)",
               ylabel="Box temperature (°C)", xticks=range(0,24,3))
    axs[2].plot(weather.index, weather["airtemp"], color="#855182")
    axs[2].set(title="C. Daily station air temperature (UTC, ≥216 readings)",
               ylabel="Air temperature (°C)", xlabel="UTC date")
    for ax in (axs[0], axs[2]):
        ax.set_xlim(START, END)
        ax.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=mdates.MO))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    for ax in axs:
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(alpha=.18)
    fig.savefig(output / "overview.png", dpi=170)
    plt.close(fig)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--boxes", type=Path, default=Path("data/Cool_City_Lab_Temperaturen_Boxen.xlsx"))
    p.add_argument("--weather", type=Path, default=Path("data/meteo_CoolCityLab.csv"))
    p.add_argument("--out", type=Path, default=Path("outputs"))
    args = p.parse_args()
    for source in (args.boxes, args.weather):
        if not source.is_file():
            p.error(f"Missing {source}. Download the original files as described in README.md.")
    series, quality = read_boxes(args.boxes)
    weather = read_weather(args.weather)
    weather = weather.loc[(weather.index >= START.tz_localize("UTC")) &
                          (weather.index < END.tz_localize("UTC"))]
    if weather.empty:
        raise ValueError("No station weather records in the comparison dates.")
    paired, strict = (paired_hours(series, n) for n in (10, 12))
    summary = {
        "start_box_clock": str(START), "end_box_clock_exclusive": str(END),
        "possible_hours": int((END - START) / pd.Timedelta(hours=1)),
        "paired_hours_min_10": len(paired), "paired_hours_min_12": len(strict),
        "tar_minus_other_min_10": summarize(paired),
        "tar_minus_other_min_12": summarize(strict) if len(strict) else None,
        "box_file_quality": quality,
        "weather_context": {"utc_rows": len(weather),
                            "valid_air_temperature_rows": int(weather["airtemp"].count()),
                            "mean_air_temperature_c": float(weather["airtemp"].mean())}
    }
    weather_days = weather["airtemp"].resample("D")
    weather_daily = weather_days.mean().where(weather_days.count() >= 216)
    weather_daily = weather_daily.reindex(pd.date_range(
        START, END, freq="D", inclusive="left", tz="UTC"))
    summary["weather_context"]["days_with_at_least_216_readings"] = int(weather_daily.count())
    args.out.mkdir(parents=True, exist_ok=True)
    plot(paired, weather_daily.to_frame(), args.out)
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n")
    print(json.dumps(summary, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
