#!/usr/bin/env python3
"""Recompute an OP Stack L2 output root from the L2 node and compare it with
the root claim of a fault dispute game on L1.

Only JSON-RPC is used (eth_getBlockByNumber, eth_getProof, eth_call).
Python 3.10+, standard library only.
"""

import argparse
import json
import sys
import urllib.request

MESSAGE_PASSER = "0x4200000000000000000000000000000000000016"
OUTPUT_ROOT_VERSION = b"\x00" * 32
SUPER_ROOT_VERSION = 0x01

GAME_STATUS = {0: "IN_PROGRESS", 1: "CHALLENGER_WINS", 2: "DEFENDER_WINS"}


# ---------------------------------------------------------------------------
# keccak-256 (hashlib.sha3_256 uses a different padding, so roll our own)
# ---------------------------------------------------------------------------

_RC = [
    0x0000000000000001, 0x0000000000008082, 0x800000000000808A, 0x8000000080008000,
    0x000000000000808B, 0x0000000080000001, 0x8000000080008081, 0x8000000000008009,
    0x000000000000008A, 0x0000000000000088, 0x0000000080008009, 0x000000008000000A,
    0x000000008000808B, 0x800000000000008B, 0x8000000000008089, 0x8000000000008003,
    0x8000000000008002, 0x8000000000000080, 0x000000000000800A, 0x800000008000000A,
    0x8000000080008081, 0x8000000000008080, 0x0000000080000001, 0x8000000080008008,
]
_ROT = [
    [0, 36, 3, 41, 18],
    [1, 44, 10, 45, 2],
    [62, 6, 43, 15, 61],
    [28, 55, 25, 21, 56],
    [27, 20, 39, 8, 14],
]
_MASK = (1 << 64) - 1


def _rol(x, n):
    n %= 64
    if n == 0:
        return x
    return ((x << n) | (x >> (64 - n))) & _MASK


def _keccak_f(s):
    for rc in _RC:
        c = [s[x][0] ^ s[x][1] ^ s[x][2] ^ s[x][3] ^ s[x][4] for x in range(5)]
        d = [c[(x - 1) % 5] ^ _rol(c[(x + 1) % 5], 1) for x in range(5)]
        s = [[s[x][y] ^ d[x] for y in range(5)] for x in range(5)]
        b = [[0] * 5 for _ in range(5)]
        for x in range(5):
            for y in range(5):
                b[y][(2 * x + 3 * y) % 5] = _rol(s[x][y], _ROT[x][y])
        s = [[b[x][y] ^ ((~b[(x + 1) % 5][y]) & b[(x + 2) % 5][y]) for y in range(5)]
             for x in range(5)]
        s[0][0] ^= rc
    return s


def keccak256(data):
    rate = 136
    buf = bytearray(data) + b"\x01"
    buf += b"\x00" * ((-len(buf)) % rate)
    buf[-1] |= 0x80
    s = [[0] * 5 for _ in range(5)]
    for off in range(0, len(buf), rate):
        block = buf[off:off + rate]
        for i in range(rate // 8):
            s[i % 5][i // 5] ^= int.from_bytes(block[8 * i:8 * i + 8], "little")
        s = _keccak_f(s)
    out = b""
    for i in range(4):
        out += s[i % 5][i // 5].to_bytes(8, "little")
    return out


def selector(signature):
    return "0x" + keccak256(signature.encode()).hex()[:8]


# ---------------------------------------------------------------------------
# JSON-RPC helpers
# ---------------------------------------------------------------------------

def rpc_call(url, method, params):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json", "User-Agent": "op-output-root-check/1.0"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        reply = json.loads(resp.read().decode())
    if "error" in reply:
        raise RuntimeError("%s: %s" % (method, reply["error"]))
    return reply["result"]


def eth_call(url, to, data, rpc=rpc_call):
    return rpc(url, "eth_call", [{"to": to, "data": data}, "latest"])


def hex_to_bytes(h):
    h = h[2:] if h.startswith("0x") else h
    return bytes.fromhex(h)


def word(h, index=0):
    """Return the index-th 32-byte word of a hex string as int."""
    return int(hex_to_bytes(h)[32 * index:32 * (index + 1)].hex(), 16)


def abi_decode_bytes(h):
    """Decode a single ABI-encoded `bytes` return value."""
    raw = hex_to_bytes(h)
    offset = int.from_bytes(raw[0:32], "big")
    length = int.from_bytes(raw[offset:offset + 32], "big")
    return raw[offset + 32:offset + 32 + length]


# ---------------------------------------------------------------------------
# L2 side: compute the output root
# ---------------------------------------------------------------------------

def compute_output_root(state_root, storage_hash, block_hash):
    """Output root v0 = keccak256(version ++ stateRoot ++ messagePasserStorageRoot ++ blockHash)."""
    preimage = OUTPUT_ROOT_VERSION + hex_to_bytes(state_root) + hex_to_bytes(storage_hash) + hex_to_bytes(block_hash)
    return "0x" + keccak256(preimage).hex()


def fetch_output_root(l2_rpc, block_number, rpc=rpc_call):
    tag = hex(block_number)
    block = rpc(l2_rpc, "eth_getBlockByNumber", [tag, False])
    if block is None:
        raise RuntimeError("L2 block %d not found" % block_number)
    proof = rpc(l2_rpc, "eth_getProof", [MESSAGE_PASSER, [], tag])
    storage_hash = proof["storageHash"]
    return {
        "block_number": block_number,
        "block_hash": block["hash"],
        "timestamp": int(block["timestamp"], 16),
        "state_root": block["stateRoot"],
        "message_passer_storage_root": storage_hash,
        "output_root": compute_output_root(block["stateRoot"], storage_hash, block["hash"]),
    }


def find_block_by_timestamp(l2_rpc, timestamp, rpc=rpc_call, max_steps=64):
    """Find the L2 block whose header timestamp equals `timestamp` exactly."""
    latest = rpc(l2_rpc, "eth_getBlockByNumber", ["latest", False])
    latest_num = int(latest["number"], 16)
    latest_ts = int(latest["timestamp"], 16)
    if timestamp > latest_ts:
        raise RuntimeError("timestamp %d is after the latest L2 block (%d)" % (timestamp, latest_ts))
    if timestamp == latest_ts:
        return latest
    # Keep a bracket lo < target < hi (lo == -1 while nothing below the target is
    # known yet). Guess by interpolating the block time inside the bracket; when a
    # guess does not at least halve the bracket, bisect it instead, so a stretch of
    # irregular block times (a sequencer gap, say) cannot stall the search.
    lo, lo_ts = -1, None
    hi, hi_ts = latest_num, latest_ts
    block_time = 2.0
    bisect = False
    while hi - lo > 1 and max_steps > 0:
        max_steps -= 1
        if bisect:
            guess = (lo + hi) // 2
        else:
            guess = hi - int((hi_ts - timestamp) / block_time)
            guess = min(max(guess, lo + 1), hi - 1)
        block = rpc(l2_rpc, "eth_getBlockByNumber", [hex(guess), False])
        ts = int(block["timestamp"], 16)
        if ts == timestamp:
            return block
        width = hi - lo
        if ts < timestamp:
            lo, lo_ts = guess, ts
            est = (hi_ts - lo_ts) / (hi - lo)
        else:
            est = (hi_ts - ts) / (hi - guess)
            hi, hi_ts = guess, ts
        if est > 0:
            block_time = est
        bisect = 2 * (hi - lo) > width
    raise RuntimeError("no L2 block with timestamp %d found" % timestamp)


# ---------------------------------------------------------------------------
# L1 side: read the dispute game
# ---------------------------------------------------------------------------

def parse_super_root_preimage(data):
    """Parse a super root preimage: 0x01 ++ uint64 timestamp ++ (chainId ++ outputRoot)*."""
    if len(data) < 9 or data[0] != SUPER_ROOT_VERSION or (len(data) - 9) % 64 != 0:
        raise ValueError("not a super root preimage (%d bytes)" % len(data))
    timestamp = int.from_bytes(data[1:9], "big")
    chains = []
    for off in range(9, len(data), 64):
        chain_id = int.from_bytes(data[off:off + 32], "big")
        output_root = "0x" + data[off + 32:off + 64].hex()
        chains.append({"chain_id": chain_id, "output_root": output_root})
    return {"version": SUPER_ROOT_VERSION, "timestamp": timestamp, "chains": chains}


def latest_game_address(l1_rpc, factory, index=None, rpc=rpc_call):
    if index is None:
        count = word(eth_call(l1_rpc, factory, selector("gameCount()"), rpc))
        if count == 0:
            raise RuntimeError("factory has no games")
        index = count - 1
    data = selector("gameAtIndex(uint256)") + "%064x" % index
    res = eth_call(l1_rpc, factory, data, rpc)
    game_type = word(res, 0)
    created = word(res, 1)
    proxy = "0x" + ("%064x" % word(res, 2))[24:]
    return {"index": index, "game_type": game_type, "created_at": created, "game": proxy}


def read_game(l1_rpc, game, rpc=rpc_call):
    root_claim = eth_call(l1_rpc, game, selector("rootClaim()"), rpc)
    game_type = word(eth_call(l1_rpc, game, selector("gameType()"), rpc))
    status = word(eth_call(l1_rpc, game, selector("status()"), rpc))
    extra = abi_decode_bytes(eth_call(l1_rpc, game, selector("extraData()"), rpc))
    return {
        "game": game,
        "game_type": game_type,
        "status": GAME_STATUS.get(status, str(status)),
        "root_claim": "0x" + hex_to_bytes(root_claim)[:32].hex(),
        "extra_data": "0x" + extra.hex(),
    }


def resolve_claim(game_info, l2_chain_id):
    """Turn a game's claim into (kind, where, expected output root)."""
    extra = hex_to_bytes(game_info["extra_data"])
    if len(extra) < 32:
        raise RuntimeError("extraData too short (%d bytes)" % len(extra))
    is_super = extra[0] == SUPER_ROOT_VERSION and (len(extra) - 9) % 64 == 0 \
        and "0x" + keccak256(extra).hex() == game_info["root_claim"]
    if not is_super:
        # FaultDisputeGame: extraData is abi.encode(l2BlockNumber). Variants such as
        # OP Succinct append more fields, but the first word is still the block number.
        return {
            "kind": "output_root",
            "l2_block_number": int.from_bytes(extra[:32], "big"),
            "expected_output_root": game_info["root_claim"],
        }
    pre = parse_super_root_preimage(extra)
    for entry in pre["chains"]:
        if entry["chain_id"] == l2_chain_id:
            return {
                "kind": "super_root",
                "timestamp": pre["timestamp"],
                "chain_id": l2_chain_id,
                "expected_output_root": entry["output_root"],
            }
    raise RuntimeError("super root has no entry for chain id %d (chains: %s)"
                       % (l2_chain_id, [c["chain_id"] for c in pre["chains"]]))


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def verify_game(l1_rpc, l2_rpc, game, rpc=rpc_call):
    game_info = read_game(l1_rpc, game, rpc)
    chain_id = int(rpc(l2_rpc, "eth_chainId", []), 16)
    claim = resolve_claim(game_info, chain_id)
    if claim["kind"] == "output_root":
        block_number = claim["l2_block_number"]
    else:
        block = find_block_by_timestamp(l2_rpc, claim["timestamp"], rpc)
        block_number = int(block["number"], 16)
    local = fetch_output_root(l2_rpc, block_number, rpc)
    return {
        "game": game_info,
        "claim": claim,
        "l2": local,
        "match": local["output_root"] == claim["expected_output_root"],
    }


def format_report(result):
    g = result["game"]
    c = result["claim"]
    l2 = result["l2"]
    lines = [
        "game:              %s" % g["game"],
        "game type:         %d" % g["game_type"],
        "status:            %s" % g["status"],
        "root claim:        %s" % g["root_claim"],
        "claim kind:        %s" % c["kind"],
    ]
    if c["kind"] == "super_root":
        lines.append("claim timestamp:   %d" % c["timestamp"])
        lines.append("chain id:          %d" % c["chain_id"])
    lines += [
        "expected root:     %s" % c["expected_output_root"],
        "l2 block:          %d" % l2["block_number"],
        "l2 block hash:     %s" % l2["block_hash"],
        "l2 state root:     %s" % l2["state_root"],
        "passer storage:    %s" % l2["message_passer_storage_root"],
        "computed root:     %s" % l2["output_root"],
        "result:            %s" % ("MATCH" if result["match"] else "MISMATCH"),
    ]
    return "\n".join(lines)


def main(argv=None):
    p = argparse.ArgumentParser(description="Recompute an OP Stack output root and compare it with a dispute game claim on L1.")
    p.add_argument("--l2-rpc", required=True, help="L2 JSON-RPC URL (must support eth_getProof at the target block)")
    p.add_argument("--l1-rpc", help="L1 JSON-RPC URL (needed with --factory or --game)")
    p.add_argument("--factory", help="DisputeGameFactory address on L1")
    p.add_argument("--game-index", type=int, help="game index in the factory (default: latest)")
    p.add_argument("--game", help="dispute game proxy address on L1 (skips the factory lookup)")
    p.add_argument("--block", type=int, help="only compute the output root for this L2 block")
    p.add_argument("--json", action="store_true", help="print JSON")
    a = p.parse_args(argv)

    if a.block is not None:
        res = fetch_output_root(a.l2_rpc, a.block)
        if a.json:
            print(json.dumps(res, indent=2))
        else:
            for k, v in res.items():
                print("%-30s %s" % (k + ":", v))
        return 0

    if not a.l1_rpc or not (a.factory or a.game):
        p.error("need --block, or --l1-rpc together with --factory or --game")

    game = a.game
    picked = None
    if game is None:
        picked = latest_game_address(a.l1_rpc, a.factory, a.game_index)
        game = picked["game"]
    result = verify_game(a.l1_rpc, a.l2_rpc, game)
    if picked is not None:
        result["factory"] = {"address": a.factory, "index": picked["index"], "created_at": picked["created_at"]}
    if a.json:
        print(json.dumps(result, indent=2))
    else:
        if picked is not None:
            print("factory:           %s (game index %d)" % (a.factory, picked["index"]))
        print(format_report(result))
    return 0 if result["match"] else 1


if __name__ == "__main__":
    sys.exit(main())
