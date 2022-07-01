import importlib
import inspect
import os
import pathlib
from typing import Union

from clvm_tools.clvmc import compile_clvm
from .types import Program


# Helper function that allows for packages to be decribed as a string, Path, or package string
def string_to_path(pkg_or_path: Union[str, pathlib.Path]) -> pathlib.Path:
    as_path = pathlib.Path(pkg_or_path)
    if as_path.exists():
        if as_path.is_dir():
            return as_path
        else:
            raise ValueError("Cannot search for includes or CLVM in a file")
    elif isinstance(pkg_or_path, pathlib.Path):
        raise ModuleNotFoundError(f"Cannot find a path matching {pkg_or_path}")
    else:
        path = importlib.import_module(pkg_or_path).__file__
        if path is None:
            raise ModuleNotFoundError(f"Cannot find a package at {pkg_or_path}")
        else:
            return pathlib.Path(path).parent


def load_serialized_clvm(
    clvm_filename,
    package_or_requirement=None,
    search_paths=["openapi.clsp.include"],
) -> str:
    """
    This function takes a chialisp file in the given package and compiles it to a
    .hex file if the .hex file is missing or older than the chialisp file, then
    returns the contents of the .hex file as a `SerializedProgram`.
    clvm_filename: file name
    package_or_requirement: Defaults to the module from which the function was called
    search_paths: A list of paths to search for `(include` files.  Defaults to a standard chia-blockchain module.
    """
    if package_or_requirement is None:
        module_name = inspect.getmodule(inspect.stack()[1][0])
        if module_name is not None:
            package_or_requirement = module_name.__name__
        else:
            raise ModuleNotFoundError("Couldn't find the module that load_clvm was called from")
    package_or_requirement = string_to_path(package_or_requirement)

    path_list = [str(string_to_path(search_path)) for search_path in search_paths]

    full_path = package_or_requirement.joinpath(clvm_filename)
    hex_filename = package_or_requirement.joinpath(f"{clvm_filename}.hex")

    if full_path.exists():
        compile_clvm(
            str(full_path),
            str(hex_filename),
            search_paths=[str(full_path.parent), *path_list],
        )

    clvm_hex = "".join(open(hex_filename, "r").read().split())  # Eliminate whitespace
    return clvm_hex


def load_clvm(clvm_filename, package_or_requirement="openapi.clsp", search_paths=["openapi.clsp.include"]) -> Program:
    if package_or_requirement is None:
        module_name = inspect.getmodule(inspect.stack()[1][0])
        if module_name is not None:
            package_or_requirement = module_name.__name__
        else:
            raise ModuleNotFoundError("Couldn't find the module that load_clvm was called from")
    return Program.fromhex(load_serialized_clvm(
                clvm_filename, package_or_requirement=package_or_requirement, search_paths=search_paths
            )
        )


SINGLETON_TOP_LAYER_MOD = load_clvm("singleton_top_layer_v1_1.clvm")
SINGLETON_TOP_LAYER_MOD_HASH = SINGLETON_TOP_LAYER_MOD.get_tree_hash()
SINGLETON_LAUNCHER_MOD = load_clvm("singleton_launcher.clvm")
SINGLETON_LAUNCHER_MOD_HASH = SINGLETON_LAUNCHER_MOD.get_tree_hash()
NFT_STATE_LAYER_MOD = load_clvm("nft_state_layer.clvm")
NFT_OWNERSHIP_LAYER = load_clvm("nft_ownership_layer.clvm")
DID_INNERPUZ_MOD = load_clvm("did_innerpuz.clvm")