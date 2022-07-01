import logging
import asyncio
from aiocache import caches
from .utils import hexstr_to_bytes, coin_name, to_hex
from .types import Coin
from .db import (
    Asset, get_db, get_sync_height_from_db, save_asset, get_unspent_asset_coin_ids,
    update_asset_coin_spent_height,
)

from .did import get_did_info_from_coin_spend
from .nft import get_nft_info_from_coin_spend
from .rpc_client import FullNodeRpcClient

logger = logging.getLogger(__name__)

DELAY_BLOCK = 10

async def get_sync_height(chain_id, address: bytes):
    cache = caches.get('default')
    key = f"sync:{chain_id}:{address.hex()}"
    height = await cache.get(key, default=0)
    return height


async def set_sync_height(chain_id, address: bytes, height: int):
    cache = caches.get('default')
    key = f"sync:{chain_id}:{address.hex()}"
    await cache.set(key, height, ttl=3600*24*3)


async def handle_coin(address, coin_record, parent_coin_spend, db):
    coin = Coin.from_json_dict(coin_record['coin'])
    logger.debug('handle coin: %s', coin.name().hex())
    did_info = get_did_info_from_coin_spend(coin, parent_coin_spend, address)
    if did_info is not None:
        curried_params = {
            'recovery_list_hash': to_hex(did_info['recovery_list_hash']),
            'recovery_list': [to_hex(r) for r in did_info['recovery_list']],
            'num_verification': did_info['num_verification'],
            'metadata': to_hex(bytes(did_info['metadata']))
        }
        asset = Asset(
            coin_id=coin.name(),
            asset_type='did',
            asset_id=did_info['did_id'],
            confirmed_height=coin_record['confirmed_block_index'],
            spent_height=0,
            coin=coin.to_json_dict(),
            lineage_proof=did_info['lineage_proof'].to_json_dict(),
            p2_puzzle_hash=did_info['p2_puzzle_hash'],
            curried_params=curried_params,
        )

        await save_asset(db, asset)
        logger.debug('new asset, type: %s, id: %s', asset.asset_type, asset.asset_id.hex())
        return

    nft_info = get_nft_info_from_coin_spend(coin, parent_coin_spend, address)
    if nft_info is not None:
        uncurried_nft, new_did_id, new_p2_puzhash, lineage_proof = nft_info
        curried_params = {
            'metadata': to_hex(bytes(uncurried_nft.metadata) if uncurried_nft.metadata else None),
            'transfer_program': to_hex(bytes(uncurried_nft.transfer_program) if uncurried_nft.transfer_program else None),
            'did_id': to_hex(new_did_id) if new_did_id else None,
        }
        asset = Asset(
            coin_id=coin.name(),
            asset_type='nft',
            asset_id=uncurried_nft.singleton_launcher_id,
            confirmed_height=coin_record['confirmed_block_index'],
            spent_height=0,
            coin=coin.to_json_dict(),
            p2_puzzle_hash=new_p2_puzhash,
            nft_did_id=new_did_id,
            lineage_proof=lineage_proof.to_json_dict(),
            curried_params=curried_params
        )
        await save_asset(db, asset)
        logger.info('new asset, address: %s, type: %s, id: %s', address.hex(), asset.asset_type, asset.asset_id.hex())
        return


async def sync_user_assets(chain_id, address: bytes, client: FullNodeRpcClient):
    """
    sync did / nft by https://docs.chia.net/docs/12rpcs/full_node_api/#get_coin_records_by_hint
    """
    # todo: use singleflight or use special process to sync
    db = get_db(chain_id)
    start_height = await get_sync_height(chain_id, address)
    if not start_height:
        start_height = await get_sync_height_from_db(db, address)

    end_height = (await client.get_block_number()) - DELAY_BLOCK
    if start_height >= end_height:
        return

    logger.debug('chain: %s, address: %s, sync from %d to %d', chain_id, address.hex(), start_height, end_height)

    # check did and nft coins has been spent
    unspent_coin_ids = await get_unspent_asset_coin_ids(db)
    for cr in await client.get_coin_records_by_names(unspent_coin_ids, include_spent_coins=True):
        spent_height = cr['spent_block_index']
        if spent_height == 0:
            continue
        await update_asset_coin_spent_height(db, coin_name(**cr['coin']), spent_height)

    coin_records = await client.get_coin_records_by_hint(
        address, include_spent_coins=False, start_height=start_height, end_height=end_height)
    
    logger.debug('hint records: %d', len(coin_records))
    if coin_records:
        pz_and_solutions = await asyncio.gather(*[
            client.get_puzzle_and_solution(hexstr_to_bytes(cr['coin']['parent_coin_info']), cr['confirmed_block_index'])
            for cr in coin_records
        ])

        for coin_record, parent_coin_spend in zip(coin_records, pz_and_solutions):
            await handle_coin(address, coin_record, parent_coin_spend, db)

    await set_sync_height(chain_id, address, end_height)
