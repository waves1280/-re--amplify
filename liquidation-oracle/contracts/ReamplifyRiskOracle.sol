// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {IReamplifyRiskOracle} from "./IReamplifyRiskOracle.sol";

/**
 * @title ReamplifyRiskOracle
 * @notice Ownable monitoring oracle: keepers publish Internal HF / zone snapshots.
 *
 * This is reAmplify's *monitoring* oracle for Cell ops and downstream app
 * consumers. It does NOT replace Spoke / Babylon / Chainlink liquidation pricing.
 * Do not inherit Chainlink Aggregator interfaces here — that would imply a fake
 * price-feed role this contract does not have.
 *
 * @dev B.1 Zero-Borrow: `internalHF == type(uint256).max` means infinite / no debt.
 */
contract ReamplifyRiskOracle is IReamplifyRiskOracle {
    address public owner;

    mapping(address => bool) private _keepers;
    mapping(bytes32 => RiskSnapshot) private _byVault;
    mapping(address => RiskSnapshot) private _byDepositor;

    error NotOwner();
    error NotKeeper();
    error LengthMismatch();
    error ZeroAddress();

    modifier onlyOwner() {
        if (msg.sender != owner) revert NotOwner();
        _;
    }

    modifier onlyKeeper() {
        if (msg.sender != owner && !_keepers[msg.sender]) revert NotKeeper();
        _;
    }

    constructor(address initialOwner) {
        if (initialOwner == address(0)) revert ZeroAddress();
        owner = initialOwner;
        _keepers[initialOwner] = true;
        emit KeeperUpdated(initialOwner, true);
    }

    function transferOwnership(address newOwner) external onlyOwner {
        if (newOwner == address(0)) revert ZeroAddress();
        owner = newOwner;
    }

    function setKeeper(address keeper, bool allowed) external onlyOwner {
        if (keeper == address(0)) revert ZeroAddress();
        _keepers[keeper] = allowed;
        emit KeeperUpdated(keeper, allowed);
    }

    function isKeeper(address account) external view returns (bool) {
        return _keepers[account] || account == owner;
    }

    /// @inheritdoc IReamplifyRiskOracle
    function updateRisk(
        bytes32 vaultId,
        address depositor,
        uint256 internalHF,
        RiskZone zone,
        uint256 btcRefPriceUsd,
        bool recommendSuspendNewPolicies,
        uint64 indexerBlock
    ) external onlyKeeper {
        _write(
            vaultId,
            depositor,
            internalHF,
            zone,
            btcRefPriceUsd,
            recommendSuspendNewPolicies,
            indexerBlock
        );
    }

    /// @inheritdoc IReamplifyRiskOracle
    function updateRiskBatch(
        bytes32[] calldata vaultIds,
        address[] calldata depositors,
        uint256[] calldata internalHFs,
        RiskZone[] calldata zones,
        uint256[] calldata btcRefPriceUsds,
        bool[] calldata recommendSuspendNewPolicies,
        uint64[] calldata indexerBlocks
    ) external onlyKeeper {
        uint256 n = vaultIds.length;
        if (
            depositors.length != n ||
            internalHFs.length != n ||
            zones.length != n ||
            btcRefPriceUsds.length != n ||
            recommendSuspendNewPolicies.length != n ||
            indexerBlocks.length != n
        ) {
            revert LengthMismatch();
        }
        for (uint256 i = 0; i < n; ) {
            _write(
                vaultIds[i],
                depositors[i],
                internalHFs[i],
                zones[i],
                btcRefPriceUsds[i],
                recommendSuspendNewPolicies[i],
                indexerBlocks[i]
            );
            unchecked {
                ++i;
            }
        }
    }

    /// @inheritdoc IReamplifyRiskOracle
    function getRisk(bytes32 vaultId) external view returns (RiskSnapshot memory) {
        return _byVault[vaultId];
    }

    /// @inheritdoc IReamplifyRiskOracle
    function getRiskByDepositor(address depositor) external view returns (RiskSnapshot memory) {
        return _byDepositor[depositor];
    }

    function _write(
        bytes32 vaultId,
        address depositor,
        uint256 internalHF,
        RiskZone zone,
        uint256 btcRefPriceUsd,
        bool recommendSuspendNewPolicies,
        uint64 indexerBlock
    ) internal {
        uint64 updatedAt = uint64(block.timestamp);
        RiskSnapshot memory snap = RiskSnapshot({
            vaultId: vaultId,
            depositor: depositor,
            internalHF: internalHF,
            zone: zone,
            btcRefPriceUsd: btcRefPriceUsd,
            recommendSuspendNewPolicies: recommendSuspendNewPolicies,
            updatedAt: updatedAt,
            indexerBlock: indexerBlock
        });

        if (vaultId != bytes32(0)) {
            _byVault[vaultId] = snap;
        }
        if (depositor != address(0)) {
            _byDepositor[depositor] = snap;
        }

        emit RiskUpdated(
            vaultId,
            depositor,
            internalHF,
            zone,
            btcRefPriceUsd,
            recommendSuspendNewPolicies,
            updatedAt,
            indexerBlock
        );
    }
}
