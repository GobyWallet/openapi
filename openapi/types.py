from typing import Dict, Any, Tuple, Optional
from dataclasses import dataclass, asdict
import io
from clvm import SExp
from clvm import run_program as default_run_program
from clvm.casts import int_from_bytes, int_to_bytes
from clvm.EvalError import EvalError
from clvm.operators import OPERATOR_LOOKUP
from clvm.serialize import sexp_from_stream, sexp_to_stream
from clvm_tools.curry import uncurry

from .utils import hexstr_to_bytes, sha256, to_hex
from .utils.tree_hash import sha256_treehash


def run_program(
    program,
    args,
    max_cost,
    operator_lookup=OPERATOR_LOOKUP,
    pre_eval_f=None,
):
    return default_run_program(
        program,
        args,
        operator_lookup,
        max_cost,
        pre_eval_f=pre_eval_f,
    )

INFINITE_COST = 0x7FFFFFFFFFFFFFFF

@dataclass(frozen=True)
class Coin:
    parent_coin_info: bytes
    puzzle_hash: bytes
    amount: int

    def name(self):
        return sha256(self.parent_coin_info + self.puzzle_hash + int_to_bytes(self.amount))

    def to_json_dict(self) -> Dict[str, Any]:
        return {
            'parent_coin_info': to_hex(self.parent_coin_info),
            'puzzle_hash': to_hex(self.puzzle_hash),
            'amount': self.amount
        }

    @classmethod
    def from_json_dict(cls, json_dict: Dict[str, Any]) -> 'Coin':
        return cls(
            hexstr_to_bytes(json_dict['parent_coin_info']),
            hexstr_to_bytes(json_dict['puzzle_hash']),
            int(json_dict['amount']),
        )


class Program(SExp):
    @classmethod
    def parse(cls, f) -> "Program":
        return sexp_from_stream(f, cls.to)

    def stream(self, f):
        sexp_to_stream(self, f)
    
    @classmethod
    def from_bytes(cls, blob: bytes) -> "Program":
        f = io.BytesIO(blob)
        result = cls.parse(f)  # noqa
        assert f.read() == b""
        return result

    @classmethod
    def fromhex(cls, hexstr: str) -> "Program":
        return cls.from_bytes(hexstr_to_bytes(hexstr))

    def __bytes__(self) -> bytes:
        f = io.BytesIO()
        self.stream(f)  # noqa
        return f.getvalue()

    def __str__(self) -> str:
        return bytes(self).hex()
    
    def curry(self, *args) -> "Program":
        fixed_args: Any = 1
        for arg in reversed(args):
            fixed_args = [4, (1, arg), fixed_args]
        return Program.to([2, (1, self), fixed_args])

    def uncurry(self) -> Tuple["Program", "Program"]:
        r = uncurry(self)
        if r is None:
            return self, self.to(0)
        return r

    def as_int(self) -> int:
        return int_from_bytes(self.as_atom())

    def __deepcopy__(self, memo):
        return type(self).from_bytes(bytes(self))
    
    def get_tree_hash(self, *args: bytes) -> bytes:
        return sha256_treehash(self, set(args))

    def at(self, position: str) -> "Program":
        v = self
        for c in position.lower():
            if c == "f":
                v = v.first()
            elif c == "r":
                v = v.rest()
            else:
                raise ValueError(f"`at` got illegal character `{c}`. Only `f` & `r` allowed")
        return v

    def run_with_cost(self, max_cost: int, args) -> Tuple[int, "Program"]:
        prog_args = Program.to(args)
        cost, r = run_program(self, prog_args, max_cost)
        return cost, Program.to(r)

    def run(self, args) -> "Program":
        cost, r = self.run_with_cost(INFINITE_COST, args)
        return r

@dataclass(frozen=True)
class LineageProof:
    parent_name: Optional[bytes] = None
    inner_puzzle_hash: Optional[bytes] = None
    amount: Optional[int] = None

    def to_json_dict(self):
        return {
            'parent_name': to_hex(self.parent_name),
            'inner_puzzle_hash': to_hex(self.inner_puzzle_hash),
            'amount': self.amount if self.amount else None,
        }
