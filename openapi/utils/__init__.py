import hashlib


def int_to_hex(num: int):
    s = "%x" % num
    if len(s) % 2 == 1:
        s = "0" + s
    return "0x" + s


def to_hex(data: bytes):
    if data:
        return f"0x{data.hex()}"


def sanitize_hex(s: str):
    if s.startswith("0x"):
        return s
    return "0x" + s


def hexstr_to_bytes(input_str: str) -> bytes:
    if input_str.startswith("0x") or input_str.startswith("0X"):
        return bytes.fromhex(input_str[2:])
    return bytes.fromhex(input_str)


def int_to_bytes(v) -> bytes:
    byte_count = (v.bit_length() + 8) >> 3
    if v == 0:
        return b""
    r = v.to_bytes(byte_count, "big", signed=True)
    while len(r) > 1 and r[0] == (0xFF if r[1] & 0x80 else 0):
        r = r[1:]
    return r


def sha256(data) -> bytes:
    return hashlib.sha256(data).digest()


def coin_name(parent_coin_info: str, puzzle_hash: str, amount: int) -> bytes:
    return sha256(hexstr_to_bytes(parent_coin_info) + hexstr_to_bytes(puzzle_hash) + int_to_bytes(amount))


def sanitize_obj_hex(obj):
    if isinstance(obj, str):
        return sanitize_hex(obj)
    elif isinstance(obj, dict):
        return {k: sanitize_obj_hex(v) for k, v in obj.items()}
    elif isinstance(obj, (tuple, list)):
        return [sanitize_obj_hex(r) for r in obj]
    return obj
