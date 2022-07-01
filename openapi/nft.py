"""
ref https://github.com/Chia-Network/chia-blockchain/blob/main_dids/chia/wallet/nft_wallet/uncurry_nft.py
"""
import logging
from typing import Type, TypeVar, Any, List, Dict, Optional, Tuple
import dataclasses
from dataclasses import dataclass
from clvm.casts import int_from_bytes

from .puzzles import SINGLETON_TOP_LAYER_MOD, NFT_STATE_LAYER_MOD, NFT_OWNERSHIP_LAYER
from .types import Coin, Program, LineageProof


logger = logging.getLogger(__name__)


_T_UncurriedNFT = TypeVar("_T_UncurriedNFT", bound="UncurriedNFT")


NFT_MOD = NFT_STATE_LAYER_MOD
bytes32 = bytes
uint16 = int


@dataclass(frozen=True)
class UncurriedNFT:
    """
    A simple solution for uncurry NFT puzzle.
    Initial the class with a full NFT puzzle, it will do a deep uncurry.
    This is the only place you need to change after modified the Chialisp curried parameters.
    """

    nft_mod_hash: bytes32
    """NFT module hash"""

    nft_state_layer: Program
    """NFT state layer puzzle"""

    singleton_struct: Program
    """
    Singleton struct
    [singleton_mod_hash, singleton_launcher_id, launcher_puzhash]
    """
    singleton_mod_hash: Program
    singleton_launcher_id: bytes32
    launcher_puzhash: Program

    metadata_updater_hash: Program
    """Metadata updater puzzle hash"""

    metadata: Program
    """
    NFT metadata
    [("u", data_uris), ("h", data_hash)]
    """
    data_uris: Program
    data_hash: Program
    meta_uris: Program
    meta_hash: Program
    license_uris: Program
    license_hash: Program
    series_number: Program
    series_total: Program

    inner_puzzle: Program
    """NFT state layer inner puzzle"""

    p2_puzzle: Program
    """p2 puzzle of the owner, either for ownership layer or standard"""

    # ownership layer fields
    owner_did: Optional[bytes32]
    """Owner's DID"""

    supports_did: bool
    """If the inner puzzle support the DID"""

    nft_inner_puzzle_hash: Optional[bytes32]
    """Puzzle hash of the ownership layer inner puzzle """

    transfer_program: Optional[Program]
    """Puzzle hash of the transfer program"""

    transfer_program_curry_params: Optional[Program]
    """
    Curried parameters of the transfer program
    [royalty_address, trade_price_percentage, settlement_mod_hash, cat_mod_hash]
    """
    royalty_address: Optional[bytes32]
    trade_price_percentage: Optional[uint16]

    @classmethod
    def uncurry(cls, puzzle: Program) -> "UncurriedNFT":
        """
        Try to uncurry a NFT puzzle
        :param cls UncurriedNFT class
        :param puzzle: Puzzle program
        :return Uncurried NFT
        """
        mod, curried_args = puzzle.uncurry()
        if mod != SINGLETON_TOP_LAYER_MOD:
            raise ValueError(f"Cannot uncurry NFT puzzle, failed on singleton top layer")
        try:
            (singleton_struct, nft_state_layer) = curried_args.as_iter()
            singleton_mod_hash = singleton_struct.first()
            singleton_launcher_id = singleton_struct.rest().first()
            launcher_puzhash = singleton_struct.rest().rest()
        except ValueError as e:
            raise ValueError(f"Cannot uncurry singleton top layer: Args {curried_args}") from e

        mod, curried_args = curried_args.rest().first().uncurry()
        if mod != NFT_MOD:
            raise ValueError(f"Cannot uncurry NFT puzzle, failed on NFT state layer")
        try:
            # Set nft parameters
            nft_mod_hash, metadata, metadata_updater_hash, inner_puzzle = curried_args.as_iter()
            data_uris = Program.to([])
            data_hash = Program.to(0)
            meta_uris = Program.to([])
            meta_hash = Program.to(0)
            license_uris = Program.to([])
            license_hash = Program.to(0)
            series_number = Program.to(1)
            series_total = Program.to(1)
            # Set metadata
            for kv_pair in metadata.as_iter():
                if kv_pair.first().as_atom() == b"u":
                    data_uris = kv_pair.rest()
                if kv_pair.first().as_atom() == b"h":
                    data_hash = kv_pair.rest()
                if kv_pair.first().as_atom() == b"mu":
                    meta_uris = kv_pair.rest()
                if kv_pair.first().as_atom() == b"mh":
                    meta_hash = kv_pair.rest()
                if kv_pair.first().as_atom() == b"lu":
                    license_uris = kv_pair.rest()
                if kv_pair.first().as_atom() == b"lh":
                    license_hash = kv_pair.rest()
                if kv_pair.first().as_atom() == b"sn":
                    series_number = kv_pair.rest()
                if kv_pair.first().as_atom() == b"st":
                    series_total = kv_pair.rest()
            current_did = None
            transfer_program = None
            transfer_program_args = None
            royalty_address = None
            royalty_percentage = None
            nft_inner_puzzle_mod = None
            mod, ol_args = inner_puzzle.uncurry()
            supports_did = False
            if mod == NFT_OWNERSHIP_LAYER:
                supports_did = True
                _, current_did, transfer_program, p2_puzzle = ol_args.as_iter()
                transfer_program_mod, transfer_program_args = transfer_program.uncurry()
                _, royalty_address_p, royalty_percentage = transfer_program_args.as_iter()
                royalty_percentage = uint16(royalty_percentage.as_int())
                royalty_address = royalty_address_p.atom
                current_did = current_did.atom
                if current_did == b"":
                    # For unassigned NFT, set owner DID to None
                    current_did = None
            else:
                p2_puzzle = inner_puzzle
        except Exception as e:
            raise ValueError(f"Cannot uncurry NFT state layer: Args {curried_args}") from e
        return cls(
            nft_mod_hash=nft_mod_hash,
            nft_state_layer=nft_state_layer,
            singleton_struct=singleton_struct,
            singleton_mod_hash=singleton_mod_hash,
            singleton_launcher_id=singleton_launcher_id.atom,
            launcher_puzhash=launcher_puzhash,
            metadata=metadata,
            data_uris=data_uris,
            data_hash=data_hash,
            p2_puzzle=p2_puzzle,
            metadata_updater_hash=metadata_updater_hash,
            meta_uris=meta_uris,
            meta_hash=meta_hash,
            license_uris=license_uris,
            license_hash=license_hash,
            series_number=series_number,
            series_total=series_total,
            inner_puzzle=inner_puzzle,
            owner_did=current_did,
            supports_did=supports_did,
            transfer_program=transfer_program,
            transfer_program_curry_params=transfer_program_args,
            royalty_address=royalty_address,
            trade_price_percentage=royalty_percentage,
            nft_inner_puzzle_hash=nft_inner_puzzle_mod,
        )

    def get_innermost_solution(self, solution: Program) -> Program:
        state_layer_inner_solution: Program = solution.at("rrff")
        if self.supports_did:
            return state_layer_inner_solution.first()  # type: ignore
        else:
            return state_layer_inner_solution


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


def prepend_value(key: bytes, value: Program, metadata: Dict[bytes, Any]) -> None:
    """
    Prepend a value to a list in the metadata
    :param key: Key of the field
    :param value: Value want to add
    :param metadata: Metadata
    :return:
    """

    if value != Program.to(0):
        if metadata[key] == b"":
            metadata[key] = [value.as_python()]
        else:
            metadata[key].insert(0, value.as_python())



def update_metadata(metadata: Program, update_condition: Program) -> Program:
    """
    Apply conditions of metadata updater to the previous metadata
    :param metadata: Previous metadata
    :param update_condition: Update metadata conditions
    :return: Updated metadata
    """
    new_metadata: Dict[bytes, Any] = program_to_metadata(metadata)
    uri: Program = update_condition.rest().rest().first()
    prepend_value(uri.first().as_python(), uri.rest(), new_metadata)
    return metadata_to_program(new_metadata)


def get_metadata_and_phs(unft: UncurriedNFT, solution: Program) -> Tuple[Program, bytes32]:
    conditions = unft.p2_puzzle.run(unft.get_innermost_solution(solution))
    metadata = unft.metadata
    puzhash_for_derivation: Optional[bytes32] = None
    for condition in conditions.as_iter():
        if condition.list_len() < 2:
            # invalid condition
            continue
        condition_code = condition.first().as_int()
        logger.debug("Checking condition code: %r", condition_code)
        if condition_code == -24:
            # metadata update
            metadata = update_metadata(metadata, condition)
            metadata = Program.to(metadata)
        elif condition_code == 51 and condition.rest().rest().first().as_int() == 1:
            # destination puzhash
            if puzhash_for_derivation is not None:
                # ignore duplicated create coin conditions
                continue
            puzhash_for_derivation = condition.rest().first().as_atom()
            logger.debug("Got back puzhash from solution: %s", puzhash_for_derivation)
    assert puzhash_for_derivation
    return metadata, puzhash_for_derivation


def get_new_owner_did(unft: UncurriedNFT, solution: Program) -> Optional[bytes32]:
    conditions = unft.p2_puzzle.run(unft.get_innermost_solution(solution))
    new_did_id = None
    for condition in conditions.as_iter():
        if condition.first().as_int() == -10:
            # this is the change owner magic condition
            new_did_id = condition.at("rf").atom
    return new_did_id
 

def get_nft_info_from_coin_spend(nft_coin: Coin, parent_cs: dict, address: bytes):
    puzzle = Program.fromhex(parent_cs['puzzle_reveal'])
    try:
        uncurried_nft = UncurriedNFT.uncurry(puzzle)
    except Exception as e:
        logger.debug('uncurry nft puzzle: %r', e)
        return
    solution = Program.fromhex(parent_cs['solution'])
    
    # DID ID determines which NFT wallet should process the NFT
    new_did_id = None
    old_did_id = None
    # P2 puzzle hash determines if we should ignore the NFT
    old_p2_puzhash = uncurried_nft.p2_puzzle.get_tree_hash()
    metadata, new_p2_puzhash = get_metadata_and_phs(
        uncurried_nft,
        solution,
    )
    if uncurried_nft.supports_did:
        new_did_id = get_new_owner_did(uncurried_nft, solution)
        old_did_id = uncurried_nft.owner_did
        if new_did_id is None:
            new_did_id = old_did_id
        if new_did_id == b"":
            new_did_id = None

    if new_p2_puzhash != address:
        return
    parent_coin = Coin.from_json_dict(parent_cs['coin'])
    lineage_proof = LineageProof(parent_coin.parent_coin_info, uncurried_nft.nft_state_layer.get_tree_hash(), parent_coin.amount)
    return (uncurried_nft, new_did_id, new_p2_puzhash, lineage_proof)
