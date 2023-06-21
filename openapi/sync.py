import logging
import asyncio
import json
import aiohttp
from aiocache import caches
from .utils import hexstr_to_bytes, coin_name, to_hex, sha256
from .types import Coin
from .db import (
    Asset, NftMetadata, SingletonSpend,
    get_db, save_asset, get_unspent_asset_coin_ids,
    update_asset_coin_spent_height, get_nft_metadata_by_hash, save_metadata,
    get_singelton_spend_by_id, delete_singleton_spend_by_id, save_singleton_spend,
    get_address_sync_height, save_address_sync_height, get_latest_tx_block_number,
)

from .did import get_did_info_from_coin_spend
from .nft import get_nft_info_from_coin_spend
from .rpc_client import FullNodeRpcClient

logger = logging.getLogger(__name__)



async def fetch_nft_metadata(db, url: str, hash: bytes):
    row = await get_nft_metadata_by_hash(db, hash)
    if row:
        return
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=60) as response:
            response.raise_for_status()
            binary = await response.read()
            binary_sha256 = sha256(binary)
            if binary_sha256 != hash:
                raise ValueError("nft metadta hash mismatch")
            data = json.loads(binary)
            await save_metadata(db, NftMetadata(
                hash=binary_sha256,
                format=data.get('format'),
                name=data.get('name'),
                collection_id=data.get('collection', {}).get('id'),
                collection_name=data.get('collection', {}).get('name'),
                full_data=data
            ))
            logger.debug('fetch metadata: %s success', hash.hex())


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
            'metadata': to_hex(bytes(uncurried_nft.metadata)),
            'transfer_program': to_hex(bytes(uncurried_nft.transfer_program) if uncurried_nft.transfer_program else None),
            'metadata_updater_hash': to_hex(uncurried_nft.metadata_updater_hash.as_atom()),
            'supports_did': uncurried_nft.supports_did,
            'owner_did': to_hex(new_did_id) if new_did_id else None,
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


async def sync_user_assets(chain_id, address: bytes, client: FullNodeRpcClient):
    """
    sync did / nft by https://docs.chia.net/docs/12rpcs/full_node_api/#get_coin_records_by_hint
    """
    # todo: use singleflight or use special process to sync
    db = get_db(chain_id)

    start_height_info = await get_address_sync_height(db, address)
    if start_height_info:
        start_height = start_height_info['height'] + 1
    else:
        start_height = 1

    end_height = await get_latest_tx_block_number(db)
    if end_height is None:
        end_height = await client.get_block_number()
    
    if start_height >= end_height:
        return

    logger.debug('chain: %s, address: %s, sync from %d to %d', chain_id, address.hex(), start_height, end_height)

    coin_records = await client.get_coin_records_by_hint(
        address, include_spent_coins=False, start_height=start_height, end_height=end_height+1)
    
    logger.debug('hint records: %d', len(coin_records))
    if coin_records:
        pz_and_solutions = await asyncio.gather(*[
            client.get_puzzle_and_solution(hexstr_to_bytes(cr['coin']['parent_coin_info']), cr['confirmed_block_index'])
            for cr in coin_records
        ])

        for coin_record, parent_coin_spend in zip(coin_records, pz_and_solutions):
            await handle_coin(address, coin_record, parent_coin_spend, db)

    await save_address_sync_height(db, address, end_height)



async def get_and_sync_singleton(chain_id, singleton_id: bytes, client: FullNodeRpcClient):
    db = get_db(chain_id)
    singleton_spend = await get_singelton_spend_by_id(db, singleton_id)
    if singleton_spend is None:
        fetch_coin_id = singleton_id
        spent_block_index = None
    else:
        fetch_coin_id = singleton_spend.coin_id
        spent_block_index = singleton_spend.spent_block_index
    odd_coin_record = None
    while spent_block_index is None or spent_block_index > 0:
        coin_recrods = await client.get_coin_records_by_parent_ids([fetch_coin_id, ], include_spent_coins=True, start_height=spent_block_index, end_height=spent_block_index + 1 if spent_block_index else None)
        odd_coin_record = None
        for cr in coin_recrods:
            if cr['coin']['amount'] % 2 == 1:
                if odd_coin_record is not None:
                    raise ValueError('more than one odd coin')
                odd_coin_record = cr
        if odd_coin_record is None:
            break
        spent_block_index = odd_coin_record['spent_block_index']
        odd_coin = Coin.from_json_dict(odd_coin_record['coin'])
        fetch_coin_id = odd_coin.name()

    if odd_coin_record is None:
        if singleton_spend:
            # maybe reorg
            await delete_singleton_spend_by_id(db, singleton_id)
            return await get_and_sync_singleton(chain_id, singleton_id, client)
        else:
            raise ValueError("This is not a singleton")

    parent_coin_id = hexstr_to_bytes(odd_coin_record['coin']['parent_coin_info'])
    await save_singleton_spend(db, SingletonSpend(
        singleton_id=singleton_id,
        coin_id=parent_coin_id,
        spent_block_index=odd_coin_record['confirmed_block_index']))
        

    coin_spend = await client.get_puzzle_and_solution(parent_coin_id, odd_coin_record['confirmed_block_index'])
    return {
        'parent_coin_spend': coin_spend,
        'current_coin': odd_coin_record['coin']
    }

