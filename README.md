# op-output-root-check

Recomputes an OP Stack output root straight from an L2 node and checks it against the root claim of a dispute game on L1. It answers one question: does the state the proposer claimed on L1 match what my L2 node actually has for that block? It works with the classic FaultDisputeGame (claim = output root at an L2 block number) and with the newer super root games used on OP Mainnet (claim = keccak of a timestamp plus per-chain output roots). Only JSON-RPC is used: `eth_getBlockByNumber`, `eth_getProof` and `eth_call`. No external packages.

## Example

OP Mainnet, latest game in the DisputeGameFactory, run on 2026-10-10:

```
$ python op_output_root_check.py \
    --l2-rpc https://optimism.drpc.org \
    --l1-rpc https://ethereum-rpc.publicnode.com \
    --factory 0xe5965Ab5962eDc7477C8520243A95517CD252fA9
factory:           0xe5965Ab5962eDc7477C8520243A95517CD252fA9 (game index 20473)
game:              0x8fbabae9d4fcbc917fb0c72cc3ba99ebfd1c73d2
game type:         9
status:            IN_PROGRESS
root claim:        0xef135db6dd5da4d726ad3b23c9fc6ee9a11e9eff9b84f39e2574d84cae37e155
claim kind:        super_root
claim timestamp:   1791621081
chain id:          10
expected root:     0xe7553e82bd795a79b6995a65694e18ec31fbd1caeac6c44f616dfd03c4bb32bb
l2 block:          158011152
l2 block hash:     0x1c93f9c353b6910358a75e765f0af540448914ed9edbfb88c936331ecf243ffb
l2 state root:     0x4a9d264aa999678b4c64d10ec7304ceb88f65d167f945ee5706f1f0dbd408317
passer storage:    0xe24ef2f454bb2f26062af27fd989dca2d88b9039adb6c98aded7a7536f061aeb
computed root:     0xe7553e82bd795a79b6995a65694e18ec31fbd1caeac6c44f616dfd03c4bb32bb
result:            MATCH
```

Base, game 23897 (a game type whose claim is a plain output root):

```
$ python op_output_root_check.py \
    --l2-rpc https://base.drpc.org \
    --l1-rpc https://ethereum-rpc.publicnode.com \
    --factory 0x43edB88C4B80fDD2AdFF2412A7BebF9dF42cB40e --game-index 23897
factory:           0x43edB88C4B80fDD2AdFF2412A7BebF9dF42cB40e (game index 23897)
game:              0x4010f976216116507c0f867209c293834631db75
game type:         621
status:            IN_PROGRESS
root claim:        0x5063efa99ce628642dfb1d6d35d39399865dc32fe43251f186a45dca43e30c5c
claim kind:        output_root
expected root:     0x5063efa99ce628642dfb1d6d35d39399865dc32fe43251f186a45dca43e30c5c
l2 block:          52415760
l2 block hash:     0x30ac00af84ae67dca46c628d2b8a9daca5ca397d8fe1f6a95d821552153ca5cf
l2 state root:     0x62404994a224a1745cd2591b6b53ff468e353b46d3baaae122d84807fff2901c
passer storage:    0x899ea9ab5b56644e90e9711e04aa53d9726ae00ad8e8d3f0024fb69b513e3455
computed root:     0x5063efa99ce628642dfb1d6d35d39399865dc32fe43251f186a45dca43e30c5c
result:            MATCH
```

Just compute the root for one block, no L1 needed:

```
$ python op_output_root_check.py --l2-rpc https://mainnet.optimism.io --block 158011152
block_number:                  158011152
block_hash:                    0x1c93f9c353b6910358a75e765f0af540448914ed9edbfb88c936331ecf243ffb
timestamp:                     1791621081
state_root:                    0x4a9d264aa999678b4c64d10ec7304ceb88f65d167f945ee5706f1f0dbd408317
message_passer_storage_root:   0xe24ef2f454bb2f26062af27fd989dca2d88b9039adb6c98aded7a7536f061aeb
output_root:                   0xe7553e82bd795a79b6995a65694e18ec31fbd1caeac6c44f616dfd03c4bb32bb
```

## Usage

```
python op_output_root_check.py --l2-rpc URL --l1-rpc URL --factory ADDR [--game-index N] [--json]
python op_output_root_check.py --l2-rpc URL --l1-rpc URL --game ADDR [--json]
python op_output_root_check.py --l2-rpc URL --block N [--json]
```

- `--l2-rpc` L2 JSON-RPC URL. It must answer `eth_getProof` for the target block, so for anything older than a few minutes you need an archive-capable endpoint.
- `--l1-rpc` L1 JSON-RPC URL (Ethereum for OP Mainnet and Base).
- `--factory` DisputeGameFactory address on L1. The latest game is used unless `--game-index` is given.
- `--game` check one specific game proxy instead of going through the factory.
- `--block` only compute and print the output root for that L2 block.
- `--json` machine-readable output.

Exit code is 0 on MATCH and 1 on MISMATCH or error.

## How it works

1. Reads `rootClaim()`, `gameType()`, `status()` and `extraData()` from the game with `eth_call`.
2. If `extraData` is a super root preimage (`0x01 ++ uint64 timestamp ++ (chainId ++ outputRoot)*`) and its keccak-256 equals the root claim, it picks the output root for the L2 chain id (`eth_chainId`) and finds the L2 block with exactly that header timestamp. Otherwise the first 32 bytes of `extraData` are the L2 block number and the root claim itself is the expected output root.
3. Fetches the L2 block header and `eth_getProof` for the L2ToL1MessagePasser predeploy (`0x4200...0016`) at that block.
4. Computes `keccak256(bytes32(0) ++ stateRoot ++ messagePasserStorageRoot ++ blockHash)` and compares it with the expected root.

keccak-256 is implemented in the file because `hashlib.sha3_256` uses different padding.

## Tests

```
python -m unittest -v
```

Tests run offline against recorded RPC responses and check that the computed roots equal the roots actually claimed on L1 for OP Mainnet block 158011152 and Base block 52415760.
