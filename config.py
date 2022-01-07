from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.util.config import load_config

CACHE_CONFIG = {
    'default': {
        'cache': "aiocache.SimpleMemoryCache",
    },
    # use redis, uncomment next
    # 'default': {
    #     'cache': "aiocache.RedisCache",
    #     'endpoint': "",
    #     'port': 6379,
    #     'password': '',
    # }
}


CHIA_ROOT_PATH = DEFAULT_ROOT_PATH
CHIA_CONFIG = load_config(CHIA_ROOT_PATH, "config.yaml")
