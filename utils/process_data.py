import pandas as pd
import numpy as np
from utils import config
from datetime import datetime, timedelta


def parse_timestamps(file_name):
    with open(file_name, 'r') as f:
        lines = f.readlines()
    timestamps = []
    for i in range(0, len(lines), 2):
        start_line = lines[i]
        stop_line = lines[i + 1]
        start_str = " ".join(start_line.split(" ")[-2:]).strip()
        stop_str = " ".join(stop_line.split(" ")[-2:]).strip()
        exp_type = start_line.split(" ")[1]
        if exp_type == "IDLE":
            start = datetime.strptime(start_str, '%Y-%m-%d %H:%M:%S%z')
        else:  # Stress test CPU consumption
            start = datetime.strptime(start_str, '%Y-%m-%d %H:%M:%S%z') + timedelta(seconds=20)
        stop = datetime.strptime(stop_str, '%Y-%m-%d %H:%M:%S%z')
        timestamps.append((start, stop, exp_type))
    return timestamps


def remove_outliers(df, column, out_range):
    q1 = df[column].quantile(0.25)
    q3 = df[column].quantile(0.75)
    iqr = q3 - q1
    lower_bound = q1 - out_range * iqr
    upper_bound = q3 + out_range * iqr
    df_filtered = df[(df[column] >= lower_bound) & (df[column] <= upper_bound)]
    return df_filtered


def get_experiment_data(start_date, stop_date, all_vars, out_range):
    ec_cpu_df = pd.DataFrame()
    for var in all_vars:
        df = config.query_influxdb(config.var_query[var], start_date, stop_date, config.influxdb_bucket)
        if not df.empty:
            df = remove_outliers(df, "_value", out_range)
            df.rename(columns={'_value': var}, inplace=True)
            df = df[["_time", var]]
            if ec_cpu_df.empty:
                ec_cpu_df = df
            else:
                ec_cpu_df = pd.merge(ec_cpu_df, df, on='_time')
    ec_cpu_df.rename(columns={'_time': 'time'}, inplace=True)
    ec_cpu_df.dropna(inplace=True)
    return ec_cpu_df[all_vars + ["time"]]


def get_time_series(x_vars, timestamps, out_range, include_idle=False):
    experiment_dates = parse_timestamps(timestamps)
    all_vars = x_vars.copy()
    time_series = pd.DataFrame(columns=all_vars)
    config.log(f"Time series starts at {experiment_dates[0][0]} and end at {experiment_dates[-1][1]}")
    for start_date, stop_date, exp_type in experiment_dates:
        if not include_idle and exp_type == "IDLE":
            continue
        start_str = start_date.strftime("%Y-%m-%dT%H:%M:%SZ")
        stop_str = stop_date.strftime("%Y-%m-%dT%H:%M:%SZ")
        if config.verbose:
            config.log(f"Querying data to InfluxDB between {start_str} and {stop_str}")
        experiment_data = get_experiment_data(start_str, stop_str, all_vars, out_range)
        time_series = pd.concat([time_series, experiment_data], ignore_index=True)
    return time_series


def get_idle_consumption(timestamps, out_range):
    experiment_dates = parse_timestamps(timestamps)
    energy_series = pd.DataFrame(columns=["energy"])
    for start_date, stop_date, exp_type in experiment_dates:
        if exp_type == "IDLE":
            start_str = start_date.strftime("%Y-%m-%dT%H:%M:%SZ")
            stop_str = stop_date.strftime("%Y-%m-%dT%H:%M:%SZ")
            experiment_data = get_experiment_data(start_str, stop_str, ["energy"], out_range)
            energy_series = pd.concat([energy_series, experiment_data], ignore_index=True)
    return energy_series["energy"].mean()


def get_formatted_vars(x_vars, data):
    x_values = []
    for i, var in enumerate(x_vars):
        x_values.append(data[var].values.reshape(-1, 1))
    x_stack = np.hstack(x_values)
    y = data["energy"].values.reshape(-1, 1)
    return x_stack, y
