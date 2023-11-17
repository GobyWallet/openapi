from typing import Optional, List, Any
from databases import Database
import sqlalchemy
from sqlalchemy import inspect, Column, ForeignKey, Integer, String, BINARY, BLOB, JSON, Boolean
from sqlalchemy import select, update, insert, delete, func
from sqlalchemy.ext.declarative import as_declarative, declared_attr

from . import config as settings

KEY_DBS = {}



def get_db(key) -> Database:
    return KEY_DBS[key]


def register_db(key, uri):
    if key in KEY_DBS:
        raise ValueError(f"db: {key} has exists")
    KEY_DBS[key] = Database(uri)


def create_tables(db: Database):
    database_url = db.url
    if database_url.scheme in ["mysql", "mysql+aiomysql", "mysql+asyncmy"]:
        url = str(database_url.replace(driver="pymysql"))
    elif database_url.scheme in [
        "postgresql+aiopg",
        "sqlite+aiosqlite",
        "postgresql+asyncpg",
    ]:
        url = str(database_url.replace(driver=None))
    engine = sqlalchemy.create_engine(url)
    Base.metadata.create_all(bind=engine)

async def connect_db(key=None):
    if key is None:
        for db in KEY_DBS.values():
            create_tables(db)
            await db.connect()
    else:
        db = KEY_DBS[key]
        create_tables(db)
        await db.connect()


async def disconnect_db(key=None):
    if key is None:
        for db in KEY_DBS.values():
            await db.disconnect()
    else:
        await KEY_DBS[key].disconnect()


@as_declarative()
class Base:
    id: Any
    __name__: str
    # Generate __tablename__ automatically
    @declared_attr
    def __tablename__(cls) -> str:
        return cls.__name__.lower()
    
    def to_dict(self):
        return {
            c.key: getattr(self, c.key)
            for c in inspect(self).mapper.column_attrs
        }


class Asset(Base):
    coin_id = Column(BINARY(32), primary_key=True)
    asset_type = Column(String(16), nullable=False, doc='did/nft')
    asset_id = Column(BINARY(32), nullable=False)
    confirmed_height = Column(Integer, nullable=False, server_default='0')
    spent_height = Column(Integer, index=True, nullable=False, server_default='0') # spent record can be deleted
    coin = Column(JSON, nullable=False)
    lineage_proof = Column(JSON, nullable=False)
    p2_puzzle_hash = Column(BINARY(32), nullable=False, index=True)
    nft_did_id = Column(BINARY(32), nullable=True, doc='for nft')
    curried_params = Column(JSON, nullable=False, doc='for recurry')


class SingletonSpend(Base):
    singleton_id = Column(BINARY(32), primary_key=True)
    coin_id = Column(BINARY(32), nullable=False)
    spent_block_index = Column(Integer, nullable=False, server_default='0')


class NftMetadata(Base):
    hash = Column(BINARY(32), primary_key=True, doc='sha256')
    format = Column(String(32), nullable=False, server_default='')
    name = Column(String(256), nullable=False, server_default='')
    collection_id = Column(String(256), nullable=False, server_default='')
    collection_name = Column(String(256), nullable=False, server_default='')
    full_data = Column(JSON, nullable=False)


class Block(Base):
    hash = Column(BINARY(32), primary_key=True)
    height = Column(Integer, unique=True, nullable=False)
    timestamp = Column(Integer, nullable=False)
    prev_hash = Column(BINARY(32), nullable=False)
    is_tx = Column(Boolean, nullable=False)


class AddressSync(Base):
    __tablename__ = 'address_sync'
    address = Column(BINARY(32), primary_key=True)
    height = Column(Integer, nullable=False, server_default='0')


def get_assets(db: Database, asset_type: Optional[str]=None, asset_id: Optional[bytes]=None, p2_puzzle_hash: Optional[bytes]=None, 
    nft_did_id: Optional[bytes]=None, include_spent_coins=False,
    start_height: Optional[int]=None, offset: Optional[int]=None, limit: Optional[int]=None) -> List[Asset]:
    query = select(Asset).order_by(Asset.confirmed_height.asc())
    if asset_type:
        query = query.where(Asset.asset_type == asset_type)
    if p2_puzzle_hash:
        query = query.where(Asset.p2_puzzle_hash == p2_puzzle_hash)
    if nft_did_id:
        query = query.where(Asset.nft_did_id == nft_did_id)
    if not include_spent_coins:
        query = query.where(Asset.spent_height == 0)
    if asset_id:
        query = query.where(Asset.asset_id == asset_id)
    if start_height:
        query = query.where(Asset.confirmed_height > start_height)
    if offset:
        query = query.offset(offset)
    if limit:
        query = query.limit(limit)
    return db.fetch_all(query)


async def update_asset_coin_spent_height(db: Database, coin_ids: List[bytes], spent_height: int):
    
    chunk_size = 200
    async with db.transaction():
        for i in range(0, len(coin_ids), chunk_size):
            chunk_ids = coin_ids[i: i+chunk_size]
            sql = update(Asset)\
            .where(Asset.coin_id.in_(chunk_ids))\
            .values(spent_height=spent_height)
            await db.execute(sql)


async def save_asset(db: Database, asset: Asset):
    async with db.transaction():
        return await db.execute(insert(Asset).values(asset.to_dict()).prefix_with('OR REPLACE'))


async def get_unspent_asset_coin_ids(db: Database, p2_puzzle_hash: Optional[bytes]=None):
    query = select(Asset.coin_id).where(Asset.spent_height == 0)
    if p2_puzzle_hash:
        query = query.where(Asset.p2_puzzle_hash == p2_puzzle_hash)
    coin_ids = []
    for row in await db.fetch_all(query):
        coin_ids.append(row.coin_id)
    return coin_ids


async def get_nft_metadata_by_hash(db: Database, hash: bytes):
    query = select(NftMetadata).where(NftMetadata.hash == hash)
    return await db.fetch_val(query)


async def save_metadata(db: Database, metadata: NftMetadata):
    async with db.transaction():
        return await db.execute(insert(NftMetadata).values(metadata.to_dict()).prefix_with('OR REPLACE'))


async def get_metadata_by_hashes(db: Database, hashes: List[bytes]):
    query = select(NftMetadata).where(NftMetadata.hash.in_(hashes))
    return await db.fetch_all(query)


async def get_singelton_spend_by_id(db: Database, singleton_id):
    query = select(SingletonSpend).where(SingletonSpend.singleton_id == singleton_id)
    return await db.fetch_one(query)


async def delete_singleton_spend_by_id(db: Database, singleton_id):
    query = delete(SingletonSpend).where(SingletonSpend.singleton_id == singleton_id)
    async with db.transaction():
        return await db.execute(query)


async def save_singleton_spend(db: Database, item: SingletonSpend):
    async with db.transaction():
        return await db.execute(insert(SingletonSpend).values(item.to_dict()).prefix_with('OR REPLACE'))



async def get_latest_tx_block_number(db: Database):
    query = select(Block.height).where(Block.is_tx == True).order_by(Block.height.desc()).limit(1)
    return await db.fetch_val(query)


async def get_latest_blocks(db: Database, num):
    query = select(Block).order_by(Block.height.desc()).limit(num)
    return await db.fetch_all(query)


async def save_block(db: Database, block: Block):
    async with db.transaction():
        return await db.execute(insert(Block).values(block.to_dict()))

async def get_block_by_height(db: Database, height):
    query = select(Block).where(Block.height == height)
    return await db.fetch_one(query)


async def delete_block_after_height(db: Database, height):
    query = delete(Block).where(Block.height > height)
    async with db.transaction():
        return await db.execute(query)


async def save_address_sync_height(db: Database, address: bytes, height: int):
    async with db.transaction():
        return await db.execute(insert(AddressSync).values(address=address, height=height).prefix_with('OR REPLACE'))


async def get_address_sync_height(db: Database, address: bytes):
    query = select(AddressSync).where(AddressSync.address == address)
    return await db.fetch_one(query)


async def reorg(db: Database, block_height: int):
    # block_height is correct, +1 is error
    async with db.transaction():
        # delete confiremd_height > block_height
        await db.execute(delete(Asset).where(Asset.confirmed_height > block_height))

        # make spent_height = 0 where spent_height > block_height
        await db.execute(update(Asset).where(Asset.spent_height > block_height).values(spent_height=0))

        # update address sync height
        await db.execute(update(AddressSync).where(AddressSync.height > block_height).values(height=block_height))

        # delete block > block_height
        await db.execute(delete(Block).where(Block.height > block_height))