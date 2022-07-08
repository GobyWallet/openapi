import os
import json
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Dict
import asyncio
import logging
from fastapi import FastAPI, APIRouter, Request, Body, Depends, HTTPException
from fastapi.responses import JSONResponse
from aiocache import caches, cached, Cache
from pydantic import BaseModel
from .utils import int_to_hex, hexstr_to_bytes, to_hex, sanitize_obj_hex
from .utils.bech32m import decode_puzzle_hash, encode_puzzle_hash
from .utils.singleflight import SingleFlight
from .rpc_client import FullNodeRpcClient
from .types import Coin, Program
from .sync import sync_user_assets
from .db import get_db, get_assets, register_db, connect_db, disconnect_db, get_metadata_by_hashes
from . import config as settings


logger = logging.getLogger(__name__)

caches.set_config(settings.CACHE_CONFIG)

app = FastAPI()


RPC_METHOD_WHITE_LIST = set(settings.RPC_METHOD_WHITE_LIST)


@dataclass
class Chain:
    id: str
    network_name: str
    network_prefix: str
    client: FullNodeRpcClient
    # db: 


async def init_chains(app, chains_config):
    chains: Dict[str, Chain] = {}
    for row in chains_config:
        if row.get('enable') == False:
            continue
        id_hex = int_to_hex(row['id'])

        if row.get('proxy_rpc_url'):
            client = await FullNodeRpcClient.create_by_proxy_url(row['proxy_rpc_url'])
        elif row.get('chia_root_path'):
            client = await FullNodeRpcClient.create_by_chia_root_path(row['chia_root_path'])
        else:
            raise ValueError(f"chian {row['id']} has no full node rpc config")
        
        # check client
        network_info =  await client.get_network_info()
        chain = Chain(id_hex, row['network_name'], row['network_prefix'], client)
        chains[id_hex] = chain
        register_db(chain.id, row['database_uri'])
        await connect_db(chain.id)

    app.state.chains = chains


@app.on_event("startup")
async def startup():
    logger.info("begin init")
    await init_chains(app, settings.SUPPORTED_CHAINS)
    logger.info("finish init")


@app.on_event("shutdown")
async def shutdown():
    for chain in app.state.chains.values():
        chain.client.close()
        await chain.client.await_closed()
        await disconnect_db(chain.id)


def decode_address(address, prefix):
    try:
        _prefix, puzzle_hash = decode_puzzle_hash(address)
        if _prefix != prefix:
            raise ValueError("wrong prefix")
        return puzzle_hash
    except ValueError:
        raise HTTPException(400, "Invalid Address")


async def get_chain(request: Request, chain="0x01") -> Chain:
    if chain not in request.app.state.chains:
        raise HTTPException(400, "Ivalid Chain")
    return request.app.state.chains[chain]


async def get_cache(request: Request) -> Cache:
    return caches.get('default')


router = APIRouter()


class UTXO(BaseModel):
    parent_coin_info: str
    puzzle_hash: str
    amount: str


def coin_javascript_compat(coin):
    return {
        'parent_coin_info':  coin['parent_coin_info'],
        'puzzle_hash': coin['puzzle_hash'],
        'amount': str(coin['amount'])
    }


@router.get("/utxos", response_model=List[UTXO])
@cached(ttl=10, key_builder=lambda *args, **kwargs: f"utxos:{kwargs['address']}", alias='default')
async def get_utxos(address: str, chain: Chain = Depends(get_chain)):
    # todo: use block indexer
    pzh = decode_address(address, chain.network_prefix)

    # the old version db has inefficient index, should set include_spent_coins=True
    coin_records = await chain.client.get_coin_records_by_puzzle_hash(puzzle_hash=pzh, include_spent_coins=False)
    data = []

    for row in coin_records:
        if row['spent']:
            continue
        data.append(coin_javascript_compat(row['coin']))
    return data


class SendTxBody(BaseModel):
    spend_bundle: dict


@router.post("/sendtx")
async def create_transaction(item: SendTxBody, chain: Chain = Depends(get_chain)):
    spb = item.spend_bundle
    try:
        spb = sanitize_obj_hex(spb)
        resp = await chain.client.push_tx(spb)
    except ValueError as e:
        logger.warning("sendtx: %s, error: %r", spb, e)
        raise HTTPException(400, str(e))
    return {
        'status': resp['status'],
    }


class ChiaRpcParams(BaseModel):
    method: str
    params: Optional[Dict] = None


@router.post('/chia_rpc')
async def full_node_rpc(item: ChiaRpcParams, chain: Chain = Depends(get_chain)):
    """
    ref: https://docs.chia.net/docs/12rpcs/full_node_api
    """
    # todo: limit method and add cache
    if item.method not in RPC_METHOD_WHITE_LIST:
        raise HTTPException(400, f"unspport chia rpc method: {item.method}")

    return await chain.client.raw_fetch(item.method, item.params)


@router.get('/balance')
@cached(ttl=10, key_builder=lambda *args, **kwargs: f"balance:{kwargs['address']}", alias='default')
async def query_balance(address: str, chain: Chain = Depends(get_chain)):
    # todo: use block indexer
    puzzle_hash = decode_address(address, chain.network_prefix)
    coin_records = await chain.client.get_coin_records_by_puzzle_hash(puzzle_hash=puzzle_hash, include_spent_coins=False)
    amount = sum([c['coin']['amount'] for c in coin_records if not c['spent']])
    data = {
        'amount': amount
    }
    return data


sf = SingleFlight()

class AssetTypeEnum(str, Enum):
    NFT = "nft"
    DID = "did"


@router.get('/assets')
async def list_assets(address: str, chain: Chain = Depends(get_chain),
    asset_type: AssetTypeEnum=AssetTypeEnum.NFT, asset_id: Optional[str]=None,
    start_height=0, limit=10):
    """
    - the api only support did coins that use inner puzzle hash for hint, so some did coins may not return
    """

    puzzle_hash = decode_address(address, chain.network_prefix)
    await sf.do(address, lambda: sync_user_assets(chain.id, puzzle_hash, chain.client))
    db = get_db(chain.id)
    # todo: use nftd/did indexer, now use db for cache
    assets = await get_assets(
        db, asset_type=asset_type, asset_id=hexstr_to_bytes(asset_id) if asset_id else None,
        p2_puzzle_hash=puzzle_hash, start_height=start_height, limit=limit
    )

    data = []
    for asset in assets:
        item = {
            'asset_type': asset.asset_type,
            'asset_id': to_hex(asset.asset_id),
            'coin': asset.coin,
            'coin_id': to_hex(asset.coin_id),
            'confirmed_height': asset.confirmed_height,
            'lineage_proof': asset.lineage_proof,
            'curried_params': asset.curried_params,
        }
        data.append(item)

    return data


app.include_router(router, prefix="/v1")
