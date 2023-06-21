"""
check tx status
"""
import asyncio
import json
import logging
import time
import logzero
from databases import Database
from decimal import Decimal
from datetime import datetime
from dataclasses import dataclass
from typing import List, Dict
from collections import defaultdict
from .rpc_client import FullNodeRpcClient
from .db import (
    get_latest_blocks, Block, get_block_by_height,
    reorg as reorg_db, save_block, update_asset_coin_spent_height,
)
from .utils import hexstr_to_bytes, coin_name


logger = logging.getLogger("openapi.watcher")


class Watcher:
    def __init__(self, url_or_path: str, db: Database):
        self.url_or_path = url_or_path
        self.client = None
        self.db = db

    async def reorg(self, block_height: int):
        # block height block is correct, +1 is error
        await reorg_db(block_height)
        logger.info("reorg success: %d", block_height)


    async def start(self):
        if self.url_or_path.startswith('http'):
            self.client = await FullNodeRpcClient.create_by_proxy_url(self.url_or_path)
        else:
            self.client = await FullNodeRpcClient.create_by_chia_root_path(self.url_or_path)
        await self.db.connect()

        try:
            prev_block = (await get_latest_blocks(self.db, 1))[0]
            prev_block = Block(
                hash=prev_block['hash'],
                height=prev_block['height'],
                timestamp=prev_block['timestamp'],
                prev_hash=prev_block['prev_hash'],
            )
        except IndexError:
            prev_block = None

        if prev_block:
            start_height = prev_block.height + 1
        else:
            resp = await self.client.get_blockchain_state()
            start_height = resp['peak']['height']
        logger.info("start height: %d", start_height)
        while True:
            
            peak_height = (await self.client.get_blockchain_state())['peak']['height']

            if start_height > peak_height:
                time.sleep(3)
                continue
            
            try:
                bc = await self.client.get_block_record_by_height(start_height)
            except Exception as e:
                logger.error("fetch block error: %s", e)
                time.sleep(3)
                continue
            
            block = Block(
                hash=hexstr_to_bytes(bc['header_hash']),
                height=int(bc['height']),
                timestamp=int(bc['timestamp'] or 0),
                prev_hash=hexstr_to_bytes(bc['prev_hash']),
                is_tx=bool(bc['timestamp']),
            )
    
            logger.info("fetch block %d, %s, %d", start_height, block.hash.hex(), block.timestamp)

            if prev_block and bytes(prev_block.hash) != bytes(block.prev_hash):
                logger.warning("block chain reorg, prev: %d(%s), curr: %d(%s",
                             prev_block.height, prev_block.hash.hex(), block.height, block.prev_hash.hex())
                check_height = start_height - 1
                while check_height:
                    bc = await self.client.get_block_record_by_height(height=check_height)
                    db_block = await get_block_by_height(check_height)
                    if hexstr_to_bytes(bc['header_hash']) == bytes(db_block['hash']):
                        prev_block = db_block
                        break
                    else:
                        check_height -= 1
                start_height = check_height  # will +1 in the func end

                logger.info("reorg to height: %d", check_height)
                await self.reorg(check_height)
            else:
                if block.is_tx:
                    s = time.monotonic()
                    await self.new_block(block)
                    logger.info('block time cost: %s', time.monotonic() - s)
                await save_block(self.db, block)
                prev_block = block
            start_height += 1

    async def new_block(self, block: Block):
        additions, removals = await self.client.get_additions_and_removals(block.hash)

        removals_id = []
        for coin_record in removals:
            coin_id = coin_name(**coin_record['coin'])
            removals_id.append(coin_id)
        
        await update_asset_coin_spent_height(self.db, removals_id, block.height)


async def main():
    from .config import settings
    tasks = []
    for row in settings.SUPPORTED_CHAINS.values():
        if row.get('enable') == False:
            continue
        
        db = Database(row['database_uri'])
        tasks.append(Watcher(row['rpc_url_or_chia_path'], db).start())
    await asyncio.gather(*tasks)

if __name__ == '__main__':
    import os
    from . import log_dir
    from .config import settings
    logzero.setup_logger(
    'openapi', level=logging.getLevelName(settings['LOG_LEVEL']), logfile=os.path.join(log_dir, "watcher.log"),
    disableStderrLogger=True)
    asyncio.run(main())
