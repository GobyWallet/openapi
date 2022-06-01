from typing import Dict, Any, Tuple
from dataclasses import dataclass
import io
from clvm import SExp
from clvm.casts import int_from_bytes, int_to_bytes
from clvm.EvalError import EvalError
from clvm.serialize import sexp_from_stream, sexp_to_stream
from clvm_tools.curry import uncurry
from .utils import hexstr_to_bytes, sha256


@dataclass(frozen=True)
class Coin:
    parent_coin_info: bytes
    puzzle_hash: bytes
    amount: int

    def name(self):
        return sha256(self.parent_coin_info + self.puzzle_hash + int_to_bytes(self.amount))

    def to_json_dict(self) -> Dict[str, Any]:
        pass

    @classmethod
    def from_json_dict(cls, json_dict: Dict[str, Any]) -> 'Coin':
        return cls(
            hexstr_to_bytes(json_dict['parent_coin_info']),
            hexstr_to_bytes(json_dict['puzzle_hash']),
            json_dict['amount']
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
        
