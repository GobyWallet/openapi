import os
import json
from typing import List, Optional, Dict
import aioredis
import logzero
from logzero import logger
from fastapi import FastAPI, APIRouter, Request, Body, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from chia.rpc.full_node_rpc_client import FullNodeRpcClient
from chia.util.bech32m import encode_puzzle_hash, decode_puzzle_hash as inner_decode_puzzle_hash
from chia.types.spend_bundle import SpendBundle
from chia.types.blockchain_format.program import Program
import config as settings


app = FastAPI()

cwd = os.path.dirname(__file__)

log_dir = os.path.join(cwd, "logs")

if not os.path.exists(log_dir):
    os.mkdir(log_dir)

logzero.logfile(os.path.join(log_dir, "api.log"))


async def get_full_node_client() -> FullNodeRpcClient:
    config = settings.CHIA_CONFIG
    full_node_client = await FullNodeRpcClient.create(config['self_hostname'], config['full_node']['rpc_port'], settings.CHIA_ROOT_PATH, settings.CHIA_CONFIG)
    return full_node_client


async def redis_pool(db: int = 0):
    redis = aioredis.from_url(
        f"redis://:{settings.REDIS_PWD}@{settings.REDIS_HOST}/{db}?encoding=utf-8"
    )
    await redis.ping()
    return redis


@app.on_event("startup")
async def startup():
    app.state.client = await get_full_node_client()
    # check full node connect
    await app.state.client.get_blockchain_state()
    app.state.redis = await redis_pool()


@app.on_event("shutdown")
async def shutdown():
    await app.state.redis.close()

    app.state.client.close()
    await app.state.client.await_closed()


def to_hex(data: bytes):
    return data.hex()


def decode_puzzle_hash(address):
    try:
        return inner_decode_puzzle_hash(address)
    except ValueError:
        raise HTTPException(400, "Invalid Address")

def coin_to_json(coin):
    return {
        'parent_coin_info':  to_hex(coin.parent_coin_info),
        'puzzle_hash': to_hex(coin.puzzle_hash),
        'amount': str(coin.amount)
    }


router = APIRouter()


class UTXO(BaseModel):
    parent_coin_info: str
    puzzle_hash: str
    amount: str


@router.get("/utxos", response_model=List[UTXO])
async def get_utxos(address: str, request: Request):
    # todo: use block indexer and support unconfirmed param
    pzh = decode_puzzle_hash(address)
    redis: aioredis.Redis = request.app.state.redis
    cache_key = f'utxo:{address}'
    cache_data = await redis.get(cache_key)
    if cache_data is not None:
        return json.loads(cache_data)
    
    full_node_client = request.app.state.client
    coin_records = await full_node_client.get_coin_records_by_puzzle_hash(puzzle_hash=pzh, include_spent_coins=True)
    data = []

    for row in coin_records:
        if row.spent:
            continue
        data.append(coin_to_json(row.coin))
    
    await redis.set(cache_key, json.dumps(data, ensure_ascii=False), ex=10)
    return data


@router.post("/sendtx")
async def create_transaction(request: Request, item = Body({})):
    spb = SpendBundle.from_json_dict(item['spend_bundle'])
    full_node_client = request.app.state.client
    
    try:
        resp = await full_node_client.push_tx(spb)
    except ValueError as e:
        logger.warning("sendtx: %s, error: %r", spb, e)
        raise HTTPException(400, str(e))
 
    return {
        'status': resp['status'],
        'id': spb.name().hex()
    }


class ChiaRpcParams(BaseModel):
    method: str
    params: Optional[Dict] = None


@router.post('/chia_rpc')
async def full_node_rpc(request: Request, item: ChiaRpcParams):
    # todo: limit method and add cache
    full_node_client = request.app.state.client
    async with full_node_client.session.post(full_node_client.url + item.method, json=item.params, ssl_context=full_node_client.ssl_context) as response:
        res_json = await response.json()
        return res_json


async def get_user_balance(puzzle_hash: bytes, request: Request):
    redis = request.app.state.redis

    data = await redis.get(f'balance:{puzzle_hash.hex()}')
    if data is not None:
        return int(data)

    full_node_client = request.app.state.client
    coin_records = await full_node_client.get_coin_records_by_puzzle_hash(puzzle_hash=puzzle_hash, include_spent_coins=True)
    amount = sum([c.coin.amount for c in coin_records if c.spent == 0])

    await redis.set(f'balance:{puzzle_hash.hex()}', amount, ex=10)
    return amount


@router.get('/balance')
async def query_balance(address, request: Request):
    # todo: use block indexer and support unconfirmed param
    puzzle_hash = decode_puzzle_hash(address)
    redis = request.app.state.redis
    cache_key = f'balance:{address}'
    cache_data = await redis.get(cache_key)
    if cache_data is not None:
        return json.loads(cache_data)
    amount = await get_user_balance(puzzle_hash, request)
    data = {
        'amount': amount
    }
    await redis.set(cache_key, json.dumps(data, ensure_ascii=False), ex=10)
    return data


DEFAULT_TOKEN_LIST = [
    {
        'chain': 'xch',
        'id': 'xch',
        'name': 'XCH',
        'symbol': 'XCH',
        'decimals': 12,
        'logo_url': 'https://static.goby.app/image/token/xch/XCH_32.png',
        'is_verified': True,
        'is_core': True,
    },
    {
        'chain': 'xch',
        'id': '8ebf855de6eb146db5602f0456d2f0cbe750d57f821b6f91a8592ee9f1d4cf31',
        'name': 'Marmot',
        'symbol': 'MRMT',
        'decimals': 3,
        'logo_url': 'https://static.goby.app/image/token/mrmt/MRMT_32.png',
        'is_verified': True,
        'is_core': True,
    },
    {
        'chain': 'xch',
        'id': '78ad32a8c9ea70f27d73e9306fc467bab2a6b15b30289791e37ab6e8612212b1',
        'name': 'Spacebucks',
        'symbol': 'SBX',
        'decimals': 3,
        'logo_url': 'https://static.goby.app/image/token/sbx/SBX_32.png',
        'is_verified': True,
        'is_core': True,
    },
]


@router.get('/tokens')
async def list_tokens():
    return DEFAULT_TOKEN_LIST

app.include_router(router, prefix="/v1")
