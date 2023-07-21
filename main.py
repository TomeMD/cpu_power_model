from my_parser import create_parser
import pandas as pd
import numpy as np
import seaborn as sns
import matplotlib
import matplotlib.pyplot as plt
import warnings
from datetime import datetime, timedelta
from influxdb_client import InfluxDBClient
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_squared_error, r2_score
from sklearn.linear_model import LinearRegression
from sklearn.preprocessing import PolynomialFeatures
from matplotlib.dates import DateFormatter, MinuteLocator
from influxdb_client.client.warnings import MissingPivotFunction
import matplotlib.font_manager

influxdb_url = "http://montoxo.des.udc.es:8086"
influxdb_token = "MyToken"
influxdb_org = "MyOrg"
influxdb_bucket = "glances"

degree = 2

load_query = '''
    from(bucket: "{influxdb_bucket}") 
        |> range(start: {start_date}, stop: {stop_date}) 
        |> filter(fn: (r) => r["_measurement"] == "percpu")
        |> filter(fn: (r) => r["_field"] == "total" )
        |> aggregateWindow(every: 2s, fn: mean, createEmpty: false)
        |> group(columns: ["_measurement"])  
        |> aggregateWindow(every: 2s, fn: sum, createEmpty: false)'''

freq_query = '''
    from(bucket: "{influxdb_bucket}") 
        |> range(start: {start_date}, stop: {stop_date}) 
        |> filter(fn: (r) => r["_measurement"] == "cpu_frequency")
        |> filter(fn: (r) => r["_field"] == "value" )
        |> aggregateWindow(every: 2s, fn: mean, createEmpty: false)'''


energy_query = '''
    from(bucket: "{influxdb_bucket}") 
        |> range(start: {start_date}, stop: {stop_date}) 
        |> filter(fn: (r) => r["_measurement"] == "ENERGY_PACKAGE")
        |> filter(fn: (r) => r["_field"] == "rapl:::PACKAGE_ENERGY:PACKAGE0(J)" or r["_field"] == "rapl:::PACKAGE_ENERGY:PACKAGE1(J)")
        |> aggregateWindow(every: 2s, fn: sum, createEmpty: false)
        |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
        |> map(fn: (r) => ({{
            _time: r._time, 
            host: r.host, 
            _measurement: r._measurement, 
            _field: "total_energy", 
            _value: (if exists r["rapl:::PACKAGE_ENERGY:PACKAGE0(J)"] then r["rapl:::PACKAGE_ENERGY:PACKAGE0(J)"] else 0.0)
                 + (if exists r["rapl:::PACKAGE_ENERGY:PACKAGE1(J)"] then r["rapl:::PACKAGE_ENERGY:PACKAGE1(J)"] else 0.0)
        }}))'''

def parse_timestamps(file_name):
    with open(file_name, 'r') as f:
        lines = f.readlines()
    timestamps = []
    for i in range(0, len(lines), 2):
        start_line = lines[i]
        stop_line = lines[i+1]
        start_str = " ".join(start_line.split(" ")[-2:]).strip()
        stop_str = " ".join(stop_line.split(" ")[-2:]).strip()
        exp_type = start_line.split(" ")[1]
        if (exp_type == "IDLE"): 
            start = datetime.strptime(start_str, '%Y-%m-%d %H:%M:%S%z') 
        else: # Stress test CPU consumption
            start = datetime.strptime(start_str, '%Y-%m-%d %H:%M:%S%z') + timedelta(seconds=20)
        stop = datetime.strptime(stop_str, '%Y-%m-%d %H:%M:%S%z')
        timestamps.append((start, stop, exp_type))
    return timestamps

def query_influxdb(query, start_date, stop_date):
    client = InfluxDBClient(url=influxdb_url, token=influxdb_token, org=influxdb_org)
    query_api = client.query_api()
    query = query.format(start_date=start_date, stop_date=stop_date, influxdb_bucket=influxdb_bucket)
    result = query_api.query_data_frame(query)
    return result

def remove_outliers(df, column):
    Q1 = df[column].quantile(0.25)
    Q3 = df[column].quantile(0.75)
    IQR = Q3 - Q1
    lower_bound = Q1 - 1.5 * IQR
    upper_bound = Q3 + 1.5 * IQR
    df_filtered = df[(df[column] >= lower_bound) & (df[column] <= upper_bound)]
    return df_filtered

def get_experiment_data(start_date, stop_date, exp_type):
    load_df = query_influxdb(load_query, start_date, stop_date)
    freq_df = query_influxdb(freq_query, start_date, stop_date)
    energy_df = query_influxdb(energy_query, start_date, stop_date)
    load_df_filtered = remove_outliers(load_df, "_value")
    freq_df_filtered = remove_outliers(freq_df, "_value")
    energy_df_filtered = remove_outliers(energy_df, "_value")
    ec_cpu_df = pd.merge(load_df_filtered, energy_df_filtered, on="_time", suffixes=("_load", "_energy"))
    ec_cpu_df = pd.merge(ec_cpu_df, freq_df_filtered, on="_time", suffixes=("", "_freq"))
    ec_cpu_df.rename(columns={'_value': '_value_freq'}, inplace=True)
    ec_cpu_df = ec_cpu_df[["_time", "_value_load", "_value_freq", "_value_energy"]]
    ec_cpu_df["exp_type"] = exp_type
    ec_cpu_df.dropna(inplace=True)

    return ec_cpu_df

def plot_time_series(df, title, xlabel, ylabels, path):
    plt.figure()
    fig, ax1 = plt.subplots()
    ax2 = ax1.twinx()

    # Set CPU Utilization axis
    sns.lineplot(x=df["_time"], y=df["_value_load"], label="Utilización de CPU", ax=ax1)
    sns.lineplot(x=df["_time"], y=df["_value_freq"], label="Frecuencia de CPU", ax=ax1,color='tab:green')
    ax1.set_xlabel(xlabel)
    ax1.set_ylabel(ylabels[0] + " / " + ylabels[1])
    ax1.tick_params(axis='y')
    for label in ax1.get_xticklabels():
        label.set_rotation(45)
    
    # Set Energy Consumption axis
    sns.lineplot(x=df["_time"], y=df["_value_energy"], label="Consumo energético", ax=ax2, color='tab:orange')
    ax2.set_ylabel(ylabels[2])
    ax2.tick_params(axis='y')
    ax2.set_ylim(0, 1000)

    # Set time axis
    plt.title(title)
    ax1.xaxis.set_major_locator(MinuteLocator(interval=10))
    ax1.xaxis.set_major_formatter(DateFormatter('%H:%M'))

    # Set legend
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    lines = lines1 + lines2
    labels = labels1 + labels2
    ax1.legend(lines, labels, loc='upper left')
    ax2.get_legend().remove()

    plt.tight_layout()
    plt.savefig(path)


def show_model_performance(name, expected, predicted):
    print(f"Modelo: {name}")
    print(f"Mean squared error: {mean_squared_error(expected, predicted)}")
    print(f"R2 score: {r2_score(expected, predicted)}")
    print("")

def plot_lin_regression(model, X, y):
    plt.plot(X, y, color="blue", linewidth=2, label="Regresión lineal")
    m = model.coef_[0]  # Coefficient (slope)
    b = model.intercept_  # Intercept (constant)
    return f"Lineal: y = {b[0]:.0f} + {m[0]:.4f}x\n"

def plot_poly_regression(model, X, y):
    fig = plt.figure()
    ax = fig.add_subplot(projection='3d')

    ax.scatter(X[:, 0], X[:, 1], y, color='red', label='Valores predichos')

    ax.set_xlabel('Utilización de CPU')
    ax.set_ylabel('Frecuencia de CPU')
    ax.set_zlabel('Consumo energético')
    ax.legend()

    names = ["U_cpu", "F_cpu", "(U_cpu*F_cpu)", "U_cpu^2", "F_cpu^2"]
    m = model.coef_[0]
    b = model.intercept_
    eq = f"Polinómica: y = {b[0]:.0f}"
    for i in range(0, 5):
        eq += f" + {m[i+1]:.8f}*{names[i]}"
        if (i%2 == 0): eq += "\n"
    eq+= "\n"
    print(eq)
    return eq


if __name__ == '__main__':
 
    parser = create_parser()
    args = parser.parse_args()
    f_train_timestamps = args.train_timestamps
    f_actual_values = args.actual_values
    model_name = args.name
    regression_plot_path = args.regression_plot_path
    data_plot_path = args.data_plot_path

    warnings.simplefilter("ignore", MissingPivotFunction)

    # Get train data
    experiment_dates = parse_timestamps(f_train_timestamps) # Get timestamps from log file
    time_series = pd.DataFrame(columns=["_time", "_value_load", "_value_freq", "_value_energy", "exp_type"])
    for start_date, stop_date, exp_type in experiment_dates:
        experiment_data = get_experiment_data(start_date.strftime("%Y-%m-%dT%H:%M:%SZ"), stop_date.strftime("%Y-%m-%dT%H:%M:%SZ"), exp_type)
        time_series = pd.concat([time_series, experiment_data], ignore_index=True)

    # Plot time series
    plot_time_series(time_series, "Series temporales",
                     "Tiempo (HH:MM)", ["Utilización de CPU (%)", "Frecuencia de CPU (MHz)", "Consumo energético (J)"], data_plot_path)
    
    idle_consumption = time_series[time_series["exp_type"] == "IDLE"]["_value_energy"].mean()
    
    # Split into train and test data
    stress_data = time_series[time_series["exp_type"] != "IDLE"]
    X1 = stress_data["_value_load"].values.reshape(-1, 1)
    X2 = stress_data["_value_freq"].values.reshape(-1, 1)
    X = np.hstack((X1, X2))
    y = stress_data["_value_energy"].values.reshape(-1, 1)
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    poly_features = PolynomialFeatures(degree=degree)
    X_poly_train = poly_features.fit_transform(X_train)
    X_poly_test = poly_features.transform(X_test)

    # Train model
    poly_reg = LinearRegression()
    poly_reg.fit(X_poly_train, y_train)

    # Get predicted values
    y_poly_pred = poly_reg.predict(X_poly_test)

    # Get actual values if provided
    X_actual = y_actual = None
    if f_actual_values is not None:
        test_dates = parse_timestamps(f_actual_values)
        test_df = pd.DataFrame(columns=["_time", "_value_load", "_value_freq", "_value_energy"])
        for start_date, stop_date, exp_type in test_dates:
            experiment_data = get_experiment_data(start_date.strftime("%Y-%m-%dT%H:%M:%SZ"), stop_date.strftime("%Y-%m-%dT%H:%M:%SZ"), exp_type)
            test_df = pd.concat([test_df, experiment_data], ignore_index=True)
        X1_actual = test_df["_value_load"].values.reshape(-1, 1)
        X2_actual = test_df["_value_load"].values.reshape(-1, 1)
        X_actual = np.hstack((X1_actual, X2_actual))
        y_actual = test_df["_value_energy"].values.reshape(-1, 1)

    # Plot model
    plt.figure()
    if (X_actual is not None and y_actual is not None):
        plt.scatter(X_actual, y_actual, color="green", label="Datos de test (custom)")
    title = ""
    title += plot_poly_regression(poly_reg, X_poly_test, y_poly_pred)
    title += f"Consumo en reposo: {idle_consumption:.0f} J"
    plt.title(title)
    plt.legend()
    plt.tight_layout()
    plt.savefig(regression_plot_path)

    # If actual values are provided they are used to test the model
    if (X_actual is not None and y_actual is not None):
        y_test = y_actual
        X_poly_actual = poly_features.transform(X_actual)
        y_poly_pred = poly_reg.predict(X_poly_actual)

    show_model_performance(f"{model_name} (Regresión polinómica)", y_test, y_poly_pred)

