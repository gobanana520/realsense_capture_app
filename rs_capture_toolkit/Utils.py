import logging
from pathlib import Path
import json
from easydict import EasyDict

PROJ_ROOT = Path(__file__).resolve().parents[1]


def read_config():
    """Read the configuration file and return it as an EasyDict object."""
    config_file = PROJ_ROOT / "config" / "config.json"
    config = read_data_from_json(config_file)
    return EasyDict(config)


def get_logger(name, level="INFO"):
    """
    Creates and returns a logger with the specified name and level.

    Args:
        name (str): The name of the logger.
        level (str): The logging level (e.g., 'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL').

    Returns:
        logging.Logger: Configured logger instance.
    """

    logger = logging.getLogger(name)

    # Convert the level string to a logging level constant
    log_level = getattr(logging, level.upper(), logging.INFO)
    logger.setLevel(log_level)

    # Avoid adding multiple handlers if the logger already has them
    if not logger.handlers:
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )

        ch = logging.StreamHandler()
        ch.setLevel(log_level)  # Set the handler's level as well
        ch.setFormatter(formatter)

        logger.addHandler(ch)

    return logger


def read_data_from_json(file_path):
    """Read data from a JSON file and return it as a dictionary."""
    with Path(file_path).open("r") as f:
        data = json.load(f)
    return data


def write_data_to_json(file_path, data):
    """Write data to a JSON file."""
    with Path(file_path).open("w") as f:
        json.dump(data, f, indent=2, sort_keys=False, ensure_ascii=True)
