import os
from utils.process_data import *
from utils.plot_data import *


def test_model(model):
    # Get actual test values if provided
    if config.actual:
        config.log(f"Parsing test timestamps from {config.f_actual_timestamps}")
        test_timestamps = parse_timestamps(config.f_actual_timestamps)
        config.log("Getting model variables time series from corresponding period")
        test_time_series = get_time_series(config.x_vars+["energy"], test_timestamps, config.test_range)
        plot_time_series("Test Time Series", test_time_series, config.x_vars, f'{config.model_name}-test-data.png')
        X_actual, y_actual = get_formatted_vars(config.x_vars, test_time_series)
        model.set_actual_values(X_actual, y_actual)
    # Predict values
    model.predict()


def save_model_results(model):
    expected = model.y_actual if config.actual else model.y_test
    predicted = model.y_pred_actual if config.actual else model.y_pred
    plot_results(expected, predicted, f'{config.model_name}-results.png')
    # If model dimension is 2 it is represented as a polynomial function
    if len(config.x_vars) == 1:
        plot_model(model, config.x_vars[0], f'{config.model_name}-function.png')
    model.write_model_performance(config.actual)


def run_tests_with_mode(model):
    if config.interactive:
        config.log("Entering interactive testing mode")
        keep_testing = True
        base_dir = config.output_dir
        config.actual = True
        while keep_testing:
            test_file = config.get_input_and_log("Enter test timestamps file path: ")
            if not os.path.exists(test_file):
                config.log(f"Specified timestamps file doesn't exists: {test_file}", "ERR")
                continue
            test_name = config.get_input_and_log("Enter test time series name: ")
            config.f_actual_timestamps = test_file
            config.output_dir = f'{base_dir}/{test_name}'
            config.img_dir = f'{config.output_dir}/img'
            os.makedirs(config.output_dir, exist_ok=True)
            os.makedirs(config.img_dir, exist_ok=True)
            test_model(model)
            save_model_results(model)
            answer = config.get_input_and_log("¿Do you want to run more tests? (y/n): ").lower()
            if answer != "y":
                keep_testing = False
    else:
        test_model(model)
        save_model_results(model)
