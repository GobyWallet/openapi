
SECONDS_PER_BLOCK = (24 * 3600) / 4608

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


SUPPORTED_CHAINS = [
    {
        "id": 1,
        "network_name": "mainnet",
        "network_prefix": "xch",
        "native_token": {
            "decimals": 12,
            "name": "XCH",
            "symbol": "XCH",
            "logo": "https://static.goby.app/image/token/xch/XCH_32.png"
        },
        "agg_sig_me_additional_data": "ccd5bb71183532bff220ba46c268991a3ff07eb358e8255a65c30a2dce0e5fbb",
        "proxy_rpc_url": "http://127.0.0.1:8555",
        "chia_root_path": "",
    },
    {
        "id": 2,
        "network_name": "testnet10",
        "network_prefix": "txch",
        "native_token": {
            "decimals": 12,
            "name": "XCH",
            "symbol": "XCH",
            "logo": "https://static.goby.app/image/token/xch/XCH_32.png"
        },
        "agg_sig_me_additional_data": "ae83525ba8d1dd3f09b277de18ca3e43fc0af20d20c4b3e92ef2a48bd291ccb2",
        "proxy_rpc_url": "http://127.0.0.1:8556",
        "chia_root_path": "",
    },
    # 1 - 10 reserved
]


RPC_METHOD_WHITE_LIST = [
    'get_coin_record_by_name',
    'get_puzzle_and_solution',
    'get_coin_records_by_puzzle_hash',
    'get_coin_records_by_puzzle_hashes',
    'get_coin_records_by_names',
]

NFT_CHAIN_START_HEIGHT = {
    "mainnet": 2013332,
    "testnet10": 1010929,
}