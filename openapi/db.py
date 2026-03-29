from contextlib import asynccontextmanager
from typing import List, Optional

from sqlalchemy import (
    BINARY,
    JSON,
    Boolean,
    Column,
    Integer,
    String,
    delete,
    insert,
    inspect,
    select,
    text,
    update,
)
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, declared_attr

KEY_ENGINES: dict[str, AsyncEngine] = {}
KEY_SESSION_FACTORIES: dict[str, async_sessionmaker[AsyncSession]] = {}


def get_db(key) -> async_sessionmaker[AsyncSession]:
    return KEY_SESSION_FACTORIES[key]


def register_db(key, uri):
    if key in KEY_ENGINES:
        raise ValueError(f"db: {key} has exists")
    engine = create_async_engine(uri)
    KEY_ENGINES[key] = engine
    KEY_SESSION_FACTORIES[key] = async_sessionmaker(engine, expire_on_commit=False)


async def _create_tables(engine: AsyncEngine):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def connect_db(key=None):
    if key is None:
        for engine in KEY_ENGINES.values():
            await _create_tables(engine)
    else:
        engine = KEY_ENGINES[key]
        await _create_tables(engine)
        if "sqlite" in str(engine.url):
            async with KEY_SESSION_FACTORIES[key]() as session:
                await session.execute(text("PRAGMA journal_mode = WAL"))
                await session.commit()


async def disconnect_db(key=None):
    if key is None:
        for engine in KEY_ENGINES.values():
            await engine.dispose()
    else:
        await KEY_ENGINES[key].dispose()


@asynccontextmanager
async def _transaction(db: async_sessionmaker):
    async with db() as session:
        async with session.begin():
            yield session


class Base(DeclarativeBase):
    __abstract__ = True

    @declared_attr.directive
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
    spent_height = Column(Integer, index=True, nullable=False, server_default='0')  # spent record can be deleted
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


async def get_assets(
    db: async_sessionmaker,
    asset_type: Optional[str] = None,
    asset_id: Optional[bytes] = None,
    p2_puzzle_hash: Optional[bytes] = None,
    nft_did_id: Optional[bytes] = None,
    include_spent_coins=False,
    start_height: Optional[int] = None,
    offset: Optional[int] = None,
    limit: Optional[int] = None,
) -> List[Asset]:
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
    if start_height is not None:
        query = query.where(Asset.confirmed_height > start_height)
    if offset is not None:
        query = query.offset(offset)
    if limit is not None:
        query = query.limit(limit)
    async with db() as session:
        return (await session.execute(query)).scalars().all()


async def update_asset_coin_spent_height(db: async_sessionmaker, coin_ids: List[bytes], spent_height: int):
    chunk_size = 200
    async with _transaction(db) as session:
        for i in range(0, len(coin_ids), chunk_size):
            chunk_ids = coin_ids[i: i + chunk_size]
            sql = update(Asset).where(Asset.coin_id.in_(chunk_ids)).values(spent_height=spent_height)
            await session.execute(sql)


async def save_asset(db: async_sessionmaker, asset: Asset):
    async with _transaction(db) as session:
        await session.execute(insert(Asset).values(asset.to_dict()).prefix_with('OR REPLACE'))


async def get_unspent_asset_coin_ids(db: async_sessionmaker, p2_puzzle_hash: Optional[bytes] = None):
    query = select(Asset.coin_id).where(Asset.spent_height == 0)
    if p2_puzzle_hash:
        query = query.where(Asset.p2_puzzle_hash == p2_puzzle_hash)
    async with db() as session:
        rows = (await session.execute(query)).all()
    return [row.coin_id for row in rows]


async def get_nft_metadata_by_hash(db: async_sessionmaker, hash: bytes):
    query = select(NftMetadata).where(NftMetadata.hash == hash)
    async with db() as session:
        return (await session.execute(query)).scalars().first()


async def save_metadata(db: async_sessionmaker, metadata: NftMetadata):
    async with _transaction(db) as session:
        await session.execute(insert(NftMetadata).values(metadata.to_dict()).prefix_with('OR REPLACE'))


async def get_metadata_by_hashes(db: async_sessionmaker, hashes: List[bytes]):
    query = select(NftMetadata).where(NftMetadata.hash.in_(hashes))
    async with db() as session:
        return (await session.execute(query)).scalars().all()


async def get_singelton_spend_by_id(db: async_sessionmaker, singleton_id):
    query = select(SingletonSpend).where(SingletonSpend.singleton_id == singleton_id)
    async with db() as session:
        return (await session.execute(query)).scalars().first()


async def delete_singleton_spend_by_id(db: async_sessionmaker, singleton_id):
    async with _transaction(db) as session:
        await session.execute(delete(SingletonSpend).where(SingletonSpend.singleton_id == singleton_id))


async def save_singleton_spend(db: async_sessionmaker, item: SingletonSpend):
    async with _transaction(db) as session:
        await session.execute(insert(SingletonSpend).values(item.to_dict()).prefix_with('OR REPLACE'))


async def get_latest_tx_block_number(db: async_sessionmaker):
    query = select(Block.height).where(Block.is_tx).order_by(Block.height.desc()).limit(1)
    async with db() as session:
        return (await session.execute(query)).scalar()


async def get_latest_blocks(db: async_sessionmaker, num):
    query = select(Block).order_by(Block.height.desc()).limit(num)
    async with db() as session:
        return (await session.execute(query)).scalars().all()


async def save_block(db: async_sessionmaker, block: Block):
    async with _transaction(db) as session:
        await session.execute(insert(Block).values(block.to_dict()))


async def get_block_by_height(db: async_sessionmaker, height):
    query = select(Block).where(Block.height == height)
    async with db() as session:
        return (await session.execute(query)).scalars().first()


async def delete_block_after_height(db: async_sessionmaker, height):
    async with _transaction(db) as session:
        await session.execute(delete(Block).where(Block.height > height))


async def save_address_sync_height(db: async_sessionmaker, address: bytes, height: int):
    async with _transaction(db) as session:
        await session.execute(insert(AddressSync).values(address=address, height=height).prefix_with('OR REPLACE'))


async def get_address_sync_height(db: async_sessionmaker, address: bytes):
    query = select(AddressSync).where(AddressSync.address == address)
    async with db() as session:
        return (await session.execute(query)).scalars().first()


async def reorg(db: async_sessionmaker, block_height: int):
    async with _transaction(db) as session:
        await session.execute(delete(Asset).where(Asset.confirmed_height > block_height))
        await session.execute(update(Asset).where(Asset.spent_height > block_height).values(spent_height=0))
        await session.execute(
            update(AddressSync).where(AddressSync.height > block_height).values(height=block_height)
        )
        await session.execute(delete(Block).where(Block.height > block_height))
