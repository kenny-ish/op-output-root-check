import unittest

import op_output_root_check as m

# Real values from OP Mainnet (chain id 10) and Ethereum L1, captured 2026-10-10.
OP_BLOCK = {
    "number": "0x96b0f10",  # 158011152
    "hash": "0x1c93f9c353b6910358a75e765f0af540448914ed9edbfb88c936331ecf243ffb",
    "stateRoot": "0x4a9d264aa999678b4c64d10ec7304ceb88f65d167f945ee5706f1f0dbd408317",
    "timestamp": "0x6ac9f7d9",  # 1791621081
}
OP_LATEST = {
    "number": "0x96b135e",  # 158012254
    "hash": "0x" + "11" * 32,  # hash not needed by the search
    "stateRoot": "0x" + "22" * 32,
    "timestamp": "0x6aca0075",  # 1791623285
}
OP_PASSER_STORAGE = "0xe24ef2f454bb2f26062af27fd989dca2d88b9039adb6c98aded7a7536f061aeb"
OP_OUTPUT_ROOT = "0xe7553e82bd795a79b6995a65694e18ec31fbd1caeac6c44f616dfd03c4bb32bb"

# DisputeGameFactory 0xe5965Ab5962eDc7477C8520243A95517CD252fA9, game index 20473 (0x4ff9)
FACTORY = "0xe5965ab5962edc7477c8520243a95517cd252fa9"
GAME = "0x8fbabae9d4fcbc917fb0c72cc3ba99ebfd1c73d2"
GAME_AT_INDEX_RESULT = (
    "0x0000000000000000000000000000000000000000000000000000000000000009"
    "000000000000000000000000000000000000000000000000000000006ac9fd03"
    "0000000000000000000000008fbabae9d4fcbc917fb0c72cc3ba99ebfd1c73d2"
)
ROOT_CLAIM = "0xef135db6dd5da4d726ad3b23c9fc6ee9a11e9eff9b84f39e2574d84cae37e155"
SUPER_PREIMAGE = (
    "01000000006ac9f7d9"
    "000000000000000000000000000000000000000000000000000000000000000a"
    "e7553e82bd795a79b6995a65694e18ec31fbd1caeac6c44f616dfd03c4bb32bb"
)
EXTRA_DATA_RESULT = (
    "0x0000000000000000000000000000000000000000000000000000000000000020"
    "0000000000000000000000000000000000000000000000000000000000000049"
    + SUPER_PREIMAGE + "00" * 23
)

# Real values from Base (chain id 8453), game index 23897 of 0x43edB88C4B80fDD2AdFF2412A7BebF9dF42cB40e.
BASE_BLOCK_HASH = "0x30ac00af84ae67dca46c628d2b8a9daca5ca397d8fe1f6a95d821552153ca5cf"
BASE_STATE_ROOT = "0x62404994a224a1745cd2591b6b53ff468e353b46d3baaae122d84807fff2901c"
BASE_PASSER_STORAGE = "0x899ea9ab5b56644e90e9711e04aa53d9726ae00ad8e8d3f0024fb69b513e3455"
BASE_ROOT_CLAIM = "0x5063efa99ce628642dfb1d6d35d39399865dc32fe43251f186a45dca43e30c5c"

L1 = "http://l1"
L2 = "http://l2"


def u256(n):
    return "0x" + "%064x" % n


def fake_rpc(url, method, params):
    if url == L2:
        if method == "eth_chainId":
            return "0xa"
        if method == "eth_getBlockByNumber":
            tag = params[0]
            if tag == "latest" or tag == OP_LATEST["number"]:
                return OP_LATEST
            if tag == OP_BLOCK["number"]:
                return OP_BLOCK
            raise AssertionError("unexpected L2 block request %s" % tag)
        if method == "eth_getProof":
            assert params == [m.MESSAGE_PASSER, [], OP_BLOCK["number"]], params
            return {"storageHash": OP_PASSER_STORAGE}
    if url == L1 and method == "eth_call":
        to = params[0]["to"].lower()
        data = params[0]["data"]
        if to == FACTORY:
            if data == m.selector("gameCount()"):
                return u256(0x4ffa)
            if data == m.selector("gameAtIndex(uint256)") + "%064x" % 0x4ff9:
                return GAME_AT_INDEX_RESULT
        if to == GAME:
            return {
                m.selector("rootClaim()"): ROOT_CLAIM,
                m.selector("gameType()"): u256(9),
                m.selector("status()"): u256(0),
                m.selector("extraData()"): EXTRA_DATA_RESULT,
            }[data]
    raise AssertionError("unexpected call %s %s %s" % (url, method, params))


class KeccakTest(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(m.keccak256(b"").hex(),
                         "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470")

    def test_selectors(self):
        self.assertEqual(m.selector("transfer(address,uint256)"), "0xa9059cbb")
        self.assertEqual(m.selector("rootClaim()"), "0xbcef3b55")
        self.assertEqual(m.selector("gameAtIndex(uint256)"), "0xbb8aa1fc")
        self.assertEqual(m.selector("extraData()"), "0x609d3334")

    def test_long_input(self):
        # more than one 136-byte rate block
        self.assertEqual(m.keccak256(b"a" * 200).hex(),
                         m.keccak256(bytes(bytearray(b"a" * 200))).hex())
        self.assertEqual(len(m.keccak256(b"a" * 200)), 32)


class OutputRootTest(unittest.TestCase):
    def test_op_mainnet_block_158011152(self):
        root = m.compute_output_root(OP_BLOCK["stateRoot"], OP_PASSER_STORAGE, OP_BLOCK["hash"])
        self.assertEqual(root, OP_OUTPUT_ROOT)

    def test_base_block_52415760(self):
        root = m.compute_output_root(BASE_STATE_ROOT, BASE_PASSER_STORAGE, BASE_BLOCK_HASH)
        self.assertEqual(root, BASE_ROOT_CLAIM)

    def test_fetch_output_root(self):
        res = m.fetch_output_root(L2, 158011152, rpc=fake_rpc)
        self.assertEqual(res["output_root"], OP_OUTPUT_ROOT)
        self.assertEqual(res["timestamp"], 1791621081)
        self.assertEqual(res["block_hash"], OP_BLOCK["hash"])


class SuperRootTest(unittest.TestCase):
    def test_parse_preimage(self):
        pre = m.parse_super_root_preimage(bytes.fromhex(SUPER_PREIMAGE))
        self.assertEqual(pre["timestamp"], 1791621081)
        self.assertEqual(pre["chains"], [{"chain_id": 10, "output_root": OP_OUTPUT_ROOT}])

    def test_preimage_hashes_to_root_claim(self):
        self.assertEqual("0x" + m.keccak256(bytes.fromhex(SUPER_PREIMAGE)).hex(), ROOT_CLAIM)

    def test_reject_bad_preimage(self):
        with self.assertRaises(ValueError):
            m.parse_super_root_preimage(b"\x01" + b"\x00" * 10)


class AbiTest(unittest.TestCase):
    def test_decode_bytes(self):
        self.assertEqual(m.abi_decode_bytes(EXTRA_DATA_RESULT).hex(), SUPER_PREIMAGE)

    def test_word(self):
        self.assertEqual(m.word(GAME_AT_INDEX_RESULT, 0), 9)
        self.assertEqual(m.word(GAME_AT_INDEX_RESULT, 1), 0x6ac9fd03)


class GameTest(unittest.TestCase):
    def test_latest_game_address(self):
        g = m.latest_game_address(L1, FACTORY, rpc=fake_rpc)
        self.assertEqual(g, {"index": 20473, "game_type": 9, "created_at": 1791622403, "game": GAME})

    def test_read_game(self):
        info = m.read_game(L1, GAME, rpc=fake_rpc)
        self.assertEqual(info["game_type"], 9)
        self.assertEqual(info["status"], "IN_PROGRESS")
        self.assertEqual(info["root_claim"], ROOT_CLAIM)
        self.assertEqual(info["extra_data"], "0x" + SUPER_PREIMAGE)

    def test_resolve_super_root_claim(self):
        info = m.read_game(L1, GAME, rpc=fake_rpc)
        claim = m.resolve_claim(info, 10)
        self.assertEqual(claim["kind"], "super_root")
        self.assertEqual(claim["timestamp"], 1791621081)
        self.assertEqual(claim["expected_output_root"], OP_OUTPUT_ROOT)
        with self.assertRaises(RuntimeError):
            m.resolve_claim(info, 8453)

    def test_resolve_output_root_claim(self):
        # Base game 23897 (type 621): extraData starts with the L2 block number 0x31fcd10
        info = {"root_claim": BASE_ROOT_CLAIM, "extra_data": u256(0x31fcd10) + "ab" * 40}
        claim = m.resolve_claim(info, 8453)
        self.assertEqual(claim["kind"], "output_root")
        self.assertEqual(claim["l2_block_number"], 52415760)
        self.assertEqual(claim["expected_output_root"], BASE_ROOT_CLAIM)

    def test_find_block_by_timestamp(self):
        block = m.find_block_by_timestamp(L2, 1791621081, rpc=fake_rpc)
        self.assertEqual(block["number"], OP_BLOCK["number"])
        with self.assertRaises(RuntimeError):
            m.find_block_by_timestamp(L2, 1791623285 + 10, rpc=fake_rpc)

    def test_verify_game_matches_l1_claim(self):
        res = m.verify_game(L1, L2, GAME, rpc=fake_rpc)
        self.assertTrue(res["match"])
        self.assertEqual(res["l2"]["block_number"], 158011152)
        self.assertEqual(res["l2"]["output_root"], OP_OUTPUT_ROOT)
        text = m.format_report(res)
        self.assertIn("result:            MATCH", text)
        self.assertIn(OP_OUTPUT_ROOT, text)

    def test_verify_game_detects_mismatch(self):
        def tampered(url, method, params):
            if method == "eth_getProof":
                return {"storageHash": "0x" + "00" * 32}
            return fake_rpc(url, method, params)
        res = m.verify_game(L1, L2, GAME, rpc=tampered)
        self.assertFalse(res["match"])
        self.assertIn("MISMATCH", m.format_report(res))


if __name__ == "__main__":
    unittest.main()
