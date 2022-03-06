
def int_to_hex(num: int):
    s = "%x" % num
    if len(s) % 2 == 1:
        s = "0" + s
    return "0x" + s

def to_hex(data: bytes):
    return data.hex()