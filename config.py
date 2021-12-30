from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.util.config import load_config


REDIS_HOST = ''
REDIS_PWD = ''

CHIA_ROOT_PATH = DEFAULT_ROOT_PATH
CHIA_CONFIG = load_config(CHIA_ROOT_PATH, "config.yaml")
