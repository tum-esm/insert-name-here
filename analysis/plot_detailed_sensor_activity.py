from datetime import datetime, timedelta
from matplotlib import pyplot as plt
import polars as pl
from os.path import dirname
import os
from src import utils

PROJECT_DIR = dirname(os.path.abspath(__file__))
MEASUREMENT_DF_CACHE_PATH = lambda sensor_number: os.path.join(
    PROJECT_DIR, "cache", f"grouped_measurements_df_{sensor_number}.parquet"
)
LOGS_DF_CACHE_PATH = lambda sensor_number: os.path.join(
    PROJECT_DIR, "cache", f"grouped_logs_df_{sensor_number}.parquet"
)

MEASUREMENT_TYPE = [
    "co2",
    "air",
    "system",
    "wind",
    "enclosure",
]
LOG_TYPE = [
    "info",
    "warning",
    "error",
]

DATA_TYPE_COLOR = {
    "co2": "#ef4444",  # red-500
    "air": "#f97316",  # orange-500
    "system": "#22c55e",  # green-500
    "wind": "#0f766e",  # teal-500
    "enclosure": "#1d4ed8",  # blue-500
    "info": "#22c55e",  # green-500
    "warning": "#f97316",  # orange-500
    "error": "#ef4444",  # red-500
}
MEASUREMENT_TYPE_OFFSET = {
    "co2": 0,
    "air": 0.045,
    "system": 0.015,
    "wind": -0.015,
    "enclosure": -0.045,
}
LOG_TYPE_OFFSET = {t: -round(i * 0.03, 2) for i, t in enumerate(LOG_TYPE)}


def get_measurement_df(sensor_number: int) -> pl.DataFrame:
    if os.path.exists(MEASUREMENT_DF_CACHE_PATH(sensor_number)):
        print(f"using cached df for measurements of raspi {sensor_number}")
        return pl.read_parquet(MEASUREMENT_DF_CACHE_PATH(sensor_number))

    print(f"fetch new df for measurements of raspi {sensor_number}")
    measurements = utils.SQLQueries.fetch_sensor_measurements(config, sensor_name)
    measurements_df = pl.DataFrame(
        {
            "timestamp": [m.timestamp for m in measurements],
            "variant": [m.value.variant for m in measurements],
        },
        schema={
            "timestamp": pl.Datetime,
            "variant": str,
        },
    ).sort(by="timestamp")
    grouped_measurements_df = measurements_df.groupby_dynamic(
        "timestamp", every="2m"
    ).agg(
        [
            ((pl.col("variant").filter(pl.col("variant") == t)).count()).alias(
                f"{t}_rpm"
            )
            for t in MEASUREMENT_TYPE
        ]
    )
    grouped_measurements_df.write_parquet(MEASUREMENT_DF_CACHE_PATH(sensor_number))
    return grouped_measurements_df


def get_logs_df(sensor_number: int) -> pl.DataFrame:
    if os.path.exists(LOGS_DF_CACHE_PATH(sensor_number)):
        print(f"using cached df for logs of raspi {sensor_number}")
        return pl.read_parquet(LOGS_DF_CACHE_PATH(sensor_number))

    print(f"fetch new df for logs of raspi {sensor_number}")
    logs = utils.SQLQueries.fetch_sensor_logs(config, sensor_name)
    logs_df = pl.DataFrame(
        {
            "timestamp": [l.timestamp for l in logs],
            "severity": [l.severity for l in logs],
        },
        schema={
            "timestamp": pl.Datetime,
            "severity": str,
        },
    ).sort(by="timestamp")
    grouped_logs_df = logs_df.groupby_dynamic("timestamp", every="2m").agg(
        [
            ((pl.col("severity").filter(pl.col("severity") == t)).count()).alias(
                f"{t}_rpm"
            )
            for t in LOG_TYPE
        ]
    )
    grouped_logs_df.write_parquet(LOGS_DF_CACHE_PATH(sensor_number))
    return grouped_logs_df


if __name__ == "__main__":
    config = utils.ConfigInterface.read()
    for sensor_number in range(1, 21):
        sensor_name = f"tum-esm-midcost-raspi-{sensor_number}"
        measurements_df = get_measurement_df(sensor_number)
        logs_df = get_logs_df(sensor_number)

        measurements_df = measurements_df.groupby_rolling(
            "timestamp", period=timedelta(minutes=10)
        ).agg([pl.col(f"{t}_rpm").mean() for t in MEASUREMENT_TYPE])

        # logs_df = logs_df.groupby_rolling(
        #    "timestamp", period=timedelta(minutes=5)
        # )

        plt.subplots(
            3,
            1,
            gridspec_kw={"height_ratios": [2, 2, 2], "hspace": 1},
            figsize=(12, 8),
        )

        # TODO: label y axis properly
        # TODO: add titles
        # TODO: add legends

        with utils.plot(
            subplot_row_count=3,
            subplot_col_count=1,
            subplot_number=1,
            xlabel="UTC time",
            ylabel="code version with\nactive measurement data",
            title="CO2 Messages",
            xaxis_scale="days",
        ) as p:
            xs = measurements_df.get_column("timestamp")
            ys = [
                y + MEASUREMENT_TYPE_OFFSET["co2"]
                for y in measurements_df.get_column(f"co2_rpm")
            ]
            p.plot(
                xs,
                ys,
                linewidth=1.5,
                color=DATA_TYPE_COLOR["co2"],
                alpha=1,
                label="co2",
            )
            p.set_xlim(
                xmin=datetime.utcnow() - timedelta(days=2),
                xmax=datetime.utcnow(),
            )

        with utils.plot(
            subplot_row_count=3,
            subplot_col_count=1,
            subplot_number=2,
            xlabel="UTC time",
            ylabel="code version with\nactive measurement data",
            title="Other Measurement Messages",
            xaxis_scale="days",
        ) as p:
            for t in MEASUREMENT_TYPE:
                if t == "co2":
                    continue
                xs = measurements_df.get_column("timestamp")
                ys = [
                    y + MEASUREMENT_TYPE_OFFSET[t]
                    for y in measurements_df.get_column(f"{t}_rpm")
                ]
                p.plot(
                    xs,
                    ys,
                    linewidth=1.5,
                    color=DATA_TYPE_COLOR[t],
                    alpha=0.7,
                    label=t,
                )
            p.set_xlim(
                xmin=datetime.utcnow() - timedelta(days=2),
                xmax=datetime.utcnow(),
            )

        with utils.plot(
            subplot_row_count=3,
            subplot_col_count=1,
            subplot_number=3,
            xlabel="UTC time",
            ylabel="code version with\nactive measurement data",
            title="Log Messages",
            xaxis_scale="days",
        ) as p:
            for t in LOG_TYPE:
                xs = logs_df.get_column("timestamp")
                ys = [LOG_TYPE_OFFSET[t] for y in logs_df.get_column(f"{t}_rpm")]
                p.scatter(
                    xs,
                    ys,
                    s=10,
                    color=DATA_TYPE_COLOR[t],
                    alpha=0.7,
                    label=t,
                )
            p.set_xlim(
                xmin=datetime.utcnow() - timedelta(days=2),
                xmax=datetime.utcnow(),
            )
            p.set_ylim(ymax=0.03, ymin=-0.09)
            p.set_yticks(
                list(LOG_TYPE_OFFSET.values()),
                list(LOG_TYPE_OFFSET.keys()),
            )

        utils.save_plot(f"sensor_activity_{sensor_number}.png")
