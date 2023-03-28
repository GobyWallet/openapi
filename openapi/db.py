from typing import Optional, List, Any
from databases import Database
import sqlalchemy
from sqlalchemy import inspect, Column, ForeignKey, Integer, String, BINARY, BLOB, JSON
from sqlalchemy import select, update, insert, func
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


async def update_asset_coin_spent_height(db: Database, coin_id: bytes, spent_height: int):
    sql = update(Asset)\
        .where(Asset.coin_id == coin_id)\
        .values(spent_height=spent_height)
    async with db.transaction():
        await db.execute(sql)


async def save_asset(db: Database, asset: Asset):
    async with db.transaction():
        return await db.execute(insert(Asset).values(asset.to_dict()).prefix_with('OR REPLACE'))



async def get_sync_height_from_db(db: Database, address: bytes):
    query = select(func.max(Asset.confirmed_height)).where(Asset.p2_puzzle_hash == address)
    max_sync_height = await db.fetch_val(query)
    return (max_sync_height or 0) + 1


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
    return await db.execute(query)


async def save_singleton_spend(db: Database, item: SingletonSpend):
    async with db.transaction():
        return await db.execute(insert(SingletonSpend).values(item.to_dict()).prefix_with('OR REPLACE'))
