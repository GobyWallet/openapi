import json
import asyncio
from aiocache import caches
from typing import Dict
from .types import Program, Coin, LineageProof
from .puzzles import (
    SINGLETON_TOP_LAYER_MOD, SINGLETON_TOP_LAYER_MOD_HASH,
    SINGLETON_LAUNCHER_MOD_HASH,
    DID_INNERPUZ_MOD
)
from .utils import to_hex


def match_did_puzzle(puzzle: Program):
    try:
        mod, curried_args = puzzle.uncurry()
        if mod == SINGLETON_TOP_LAYER_MOD:
            mod, curried_args = curried_args.rest().first().uncurry()
            if mod == DID_INNERPUZ_MOD:
                return True, curried_args.as_iter()
    except Exception:
        return False, iter(())
    return False, iter(())


def get_did_inner_puzzle_hash(address: bytes, recovery_list_hash: bytes, num_verification: int, singleton_struct, metadata):
    return DID_INNERPUZ_MOD.curry(address,  recovery_list_hash, num_verification, singleton_struct, metadata).get_tree_hash(address)


def to_full_pzh(inner_puzzle_hash: bytes, launcher_id: bytes):
    singleton_struct = Program.to((SINGLETON_TOP_LAYER_MOD_HASH, (launcher_id, SINGLETON_LAUNCHER_MOD_HASH)))
    return SINGLETON_TOP_LAYER_MOD.curry(singleton_struct, inner_puzzle_hash).get_tree_hash(inner_puzzle_hash)


def program_to_metadata(program: Program) -> Dict:
    """
    Convert a program to a metadata dict
    :param program: Chialisp program contains the metadata
    :return: Metadata dict
    """
    metadata = {}
    for key, val in program.as_python():
        metadata[str(key, "utf-8")] = str(val, "utf-8")
    return metadata


def get_did_info_from_coin_spend(coin: Coin, parent_cs: dict, address: bytes):
    parent_coin = Coin.from_json_dict(parent_cs['coin'])
    puzzle = Program.fromhex(parent_cs['puzzle_reveal'])

    try:
        mod, curried_args_pz = puzzle.uncurry()
        if mod != SINGLETON_TOP_LAYER_MOD:
            return
        singleton_inner_puzzle = curried_args_pz.rest().first()
        mod, curried_args_pz = singleton_inner_puzzle.uncurry()
        if mod != DID_INNERPUZ_MOD:
            return
        curried_args = curried_args_pz.as_iter()
    except Exception:
        return 

    solution = Program.fromhex(parent_cs['solution'])

    p2_puzzle, recovery_list_hash, num_verification, singleton_struct, metadata = curried_args
    recovery_list_hash = recovery_list_hash.as_atom()

    p2_puzzle_hash = p2_puzzle.get_tree_hash()

    launcher_id = singleton_struct.rest().first().as_atom()

    full_puzzle_hash = to_full_pzh(get_did_inner_puzzle_hash(address, recovery_list_hash, num_verification, singleton_struct, metadata), bytes(launcher_id))
 

    if coin.puzzle_hash != full_puzzle_hash:
        recovery_list_hash = Program.to([]).get_tree_hash()
        num_verification = 0
        full_empty_puzzle_hash = to_full_pzh(get_did_inner_puzzle_hash(address, recovery_list_hash, num_verification, singleton_struct, metadata), launcher_id)
        if coin.puzzle_hash != full_empty_puzzle_hash:
            # the recovery list was reset by the previous owner
            return None
    
    inner_solution = solution.rest().rest().first()
    recovery_list = []
    if recovery_list_hash != Program.to([]).get_tree_hash():
        for did in inner_solution.rest().rest().rest().rest().rest().as_python():
            recovery_list.append(did[0])

    return {
        'did_id': launcher_id,
        'coin': coin,
        'p2_puzzle_hash': p2_puzzle_hash,
        'recovery_list_hash': recovery_list_hash,
        'recovery_list': recovery_list,
        'num_verification': num_verification.as_int(),
        'metadata': metadata,
        'lineage_proof': LineageProof(parent_coin.parent_coin_info, singleton_inner_puzzle.get_tree_hash(), parent_coin.amount)
    }
