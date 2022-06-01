"""
ref https://github.com/Chia-Network/chia-blockchain/blob/main_dids/chia/wallet/nft_wallet/uncurry_nft.py
"""
from typing import Type, TypeVar, Any, List, Dict
import dataclasses
from dataclasses import dataclass
from clvm.casts import int_from_bytes

from .puzzles import NFT_MOD, SINGLETON_TOP_LAYER_MOD
from .types import Coin, Program


_T_UncurriedNFT = TypeVar("_T_UncurriedNFT", bound="UncurriedNFT")



@dataclass(frozen=True)
class UncurriedNFT:
    """
    A simple solution for uncurry NFT puzzle.
    Initial the class with a full NFT puzzle, it will do a deep uncurry.
    This is the only place you need to change after modified the Chialisp curried parameters.
    """

    nft_mod_hash: Program
    """NFT module hash"""

    nft_state_layer: Program
    """NFT state layer puzzle"""

    singleton_struct: Program
    """
    Singleton struct
    [singleton_mod_hash, singleton_launcher_id, launcher_puzhash]
    """
    singleton_mod_hash: Program
    singleton_launcher_id: Program
    launcher_puzhash: Program

    owner_did: Program
    """Owner's DID"""

    metdata_updater_hash: Program
    """Metadata updater puzzle hash"""

    transfer_program_hash: Program
    """Puzzle hash of the transfer program"""

    transfer_program_curry_params: Program
    """
    Curried parameters of the transfer program
    [royalty_address, trade_price_percentage, settlement_mod_hash, cat_mod_hash]
    """
    royalty_address: Program
    trade_price_percentage: Program
    settlement_mod_hash: Program
    cat_mod_hash: Program

    metadata: Program
    """
    NFT metadata
    [("u", data_uris), ("h", data_hash)]
    """
    data_uris: Program
    data_hash: Program

    inner_puzzle: Program
    """NFT state layer inner puzzle"""

    @classmethod
    def uncurry(cls: Type[_T_UncurriedNFT], puzzle: Program):
        """
        Try to uncurry a NFT puzzle
        :param cls UncurriedNFT class
        :param puzzle: Puzzle program
        :return Uncurried NFT
        """
        mod, curried_args = puzzle.uncurry()
        if mod != SINGLETON_TOP_LAYER_MOD:
            raise ValueError(f"Cannot uncurry NFT puzzle, failed on singleton top layer: Mod {mod}")
        try:
            (singleton_struct, nft_state_layer) = curried_args.as_iter()
            singleton_mod_hash = singleton_struct.first()
            singleton_launcher_id = singleton_struct.rest().first()
            launcher_puzhash = singleton_struct.rest().rest()
        except ValueError as e:
            raise ValueError(f"Cannot uncurry singleton top layer: Args {curried_args}") from e

        mod, curried_args = curried_args.rest().first().uncurry()
        if mod != NFT_MOD:
            raise ValueError(f"Cannot uncurry NFT puzzle, failed on NFT state layer: Mod {mod}")
        try:
            # Set nft parameters
            (nft_mod_hash, metadata, metdata_updater_hash, inner_puzzle) = curried_args.as_iter()

            # Set metadata
            for kv_pair in metadata.as_iter():
                if kv_pair.first().as_atom() == b"u":
                    data_uris = kv_pair.rest()
                if kv_pair.first().as_atom() == b"h":
                    data_hash = kv_pair.rest()
        except Exception as e:
            raise ValueError(f"Cannot uncurry NFT state layer: Args {curried_args}") from e
        return cls(
            nft_mod_hash=nft_mod_hash,
            nft_state_layer=nft_state_layer,
            singleton_struct=singleton_struct,
            singleton_mod_hash=singleton_mod_hash,
            singleton_launcher_id=singleton_launcher_id,
            launcher_puzhash=launcher_puzhash,
            metadata=metadata,
            data_uris=data_uris,
            data_hash=data_hash,
            metdata_updater_hash=metdata_updater_hash,
            inner_puzzle=inner_puzzle,
            # TODO Set/Remove following fields after NFT1 implemented
            owner_did=Program.to([]),
            transfer_program_hash=Program.to([]),
            transfer_program_curry_params=Program.to([]),
            royalty_address=Program.to([]),
            trade_price_percentage=Program.to([]),
            settlement_mod_hash=Program.to([]),
            cat_mod_hash=Program.to([]),
        )




@dataclass(frozen=True)
class NFTInfo:
    launcher_id: str
    nft_coin_id: str
    owner: str
    did_owner: str
    royalty: int
    data_uris: List[str]
    data_hash: str
    metadata_uris: List[str]
    metadata_hash: str
    license_uris: List[str]
    license_hash: str
    version: str
    edition_count: int
    edition_number: int

    def to_dict(self):
        return dataclasses.asdict(self)




def metadata_to_program(metadata: Dict[bytes, Any]) -> Program:
    """
    Convert the metadata dict to a Chialisp program
    :param metadata: User defined metadata
    :return: Chialisp program
    """
    kv_list = []
    for key, value in metadata.items():
        kv_list.append((key, value))
    program: Program = Program.to(kv_list)
    return program


def program_to_metadata(program: Program) -> Dict[bytes, Any]:
    """
    Convert a program to a metadata dict
    :param program: Chialisp program contains the metadata
    :return: Metadata dict
    """
    metadata = {}
    for kv_pair in program.as_iter():
        metadata[kv_pair.first().as_atom()] = kv_pair.rest().as_python()
    return metadata


def update_metadata(metadata: Program, update_condition: Program) -> Program:
    """
    Apply conditions of metadata updater to the previous metadata
    :param metadata: Previous metadata
    :param update_condition: Update metadata conditions
    :return: Updated metadata
    """
    new_metadata = program_to_metadata(metadata)
    # TODO Modify this for supporting other fields
    new_metadata[b"u"].insert(0, update_condition.rest().rest().first().atom)
    return metadata_to_program(new_metadata)



def get_nft_info(nft_coin: Coin, puzzle: Program, solution: Program):    
    solution = solution.rest().rest().first().first()

    uncurried_nft = UncurriedNFT.uncurry(puzzle)
    singleton_id = bytes(uncurried_nft.singleton_launcher_id.atom)
    metadata = uncurried_nft.metadata

    # check metadata update and get owner address
    update_condition = None
    for condition in solution.rest().first().rest().as_iter():
        if condition.list_len() < 2:
            # invalid condition
            continue
        condition_code = int_from_bytes(condition.first().atom)
        if condition_code == -24:
            update_condition = condition
        elif condition_code == 51 and int_from_bytes(condition.rest().rest().first().atom) == 1:
            puzhash = bytes(condition.rest().first().atom)
        

    if update_condition is not None:
        metadata = update_metadata(metadata, update_condition)

    # todo: get full metadata info
    for kv_pair in metadata.as_iter():
        if kv_pair.first().as_atom() == b"u":
            data_uris = kv_pair.rest()
        if kv_pair.first().as_atom() == b"h":
            data_hash = kv_pair.rest()

    data_uris = [str(uri, 'utf-8') for uri in data_uris.as_python()]


    return NFTInfo(
        singleton_id.hex(),
        nft_coin.name().hex(),
        puzhash.hex(),
        "",
        0,
        data_uris,
        data_hash.as_python().hex(),
        [],
        "",
        [],
        "",
        "NFT0",
        1,
        1)