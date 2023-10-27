from cpu_power_model.parser.my_parser import create_parser, check_config, update_config
from cpu_power_model.config.print import print_config


def run():
    # Configuration
    parser = create_parser()
    args = parser.parse_args()
    update_config(args)
    check_config()
    print_config()
