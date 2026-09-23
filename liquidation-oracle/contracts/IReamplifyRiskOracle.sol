// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title IReamplifyRiskOracle
 * @notice Monitoring risk oracle for reAmplify Cell / programme ops.
 *
 * IMPORTANT — this is NOT a Chainlink price feed and does NOT drive Spoke
 * liquidation. Babylon Spoke liquidation still uses Babylon / Chainlink pricing.
 * Consumers of this interface are Cell ops tooling and downstream app readers
 * that need an on-chain snapshot of off-chain Internal HF / zone monitoring.
 *
 * @dev B.1 Zero-Borrow: when there is no debt, `internalHF` MAY be
 *      `type(uint256).max` (infinite / N/A).
 */
interface IReamplifyRiskOracle {
    /// @notice Escalation zone (A.4). ZERO_BORROW = no debt / Zero-Borrow posture.
    enum RiskZone {
        ZERO_BORROW, // 0
        GREEN,       // 1  Internal HF >= 3.0
        RED,         // 2  1.5 <= Internal HF < 3.0
        CRITICAL     // 3  Internal HF < 1.5
    }

    /// @notice Per-vault / per-depositor risk snapshot published by keepers.
    struct RiskSnapshot {
        bytes32 vaultId;
        address depositor;
        /// @dev 1e18 fixed-point HF. type(uint256).max = infinite / no debt (B.1).
        uint256 internalHF;
        RiskZone zone;
        /// @dev BTC reference USD with 8 decimals (Chainlink-style). 0 if unused.
        uint256 btcRefPriceUsd;
        bool recommendSuspendNewPolicies;
        uint64 updatedAt;
        /// @dev Last Babylon Vault Indexer block observed when building the snapshot.
        uint64 indexerBlock;
    }

    event RiskUpdated(
        bytes32 indexed vaultId,
        address indexed depositor,
        uint256 internalHF,
        RiskZone zone,
        uint256 btcRefPriceUsd,
        bool recommendSuspendNewPolicies,
        uint64 updatedAt,
        uint64 indexerBlock
    );

    event KeeperUpdated(address indexed keeper, bool allowed);

    function updateRisk(
        bytes32 vaultId,
        address depositor,
        uint256 internalHF,
        RiskZone zone,
        uint256 btcRefPriceUsd,
        bool recommendSuspendNewPolicies,
        uint64 indexerBlock
    ) external;

    function updateRiskBatch(
        bytes32[] calldata vaultIds,
        address[] calldata depositors,
        uint256[] calldata internalHFs,
        RiskZone[] calldata zones,
        uint256[] calldata btcRefPriceUsds,
        bool[] calldata recommendSuspendNewPolicies,
        uint64[] calldata indexerBlocks
    ) external;

    function getRisk(bytes32 vaultId) external view returns (RiskSnapshot memory);

    function getRiskByDepositor(address depositor) external view returns (RiskSnapshot memory);

    function isKeeper(address account) external view returns (bool);
}
