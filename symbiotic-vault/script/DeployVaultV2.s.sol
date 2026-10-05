// SPDX-License-Identifier: MIT
pragma solidity ^0.8.25;

import "./base/DeployVaultV2Base.sol";

// forge script script/DeployVaultV2.s.sol:DeployVaultV2Script --rpc-url=RPC --broadcast
//
// reAmplify WBTC Vault V2 (Ethereum mainnet)
// - ASSET: WBTC
// - OWNER: all role holders
// - No adapters at launch (idle capital OK; add later via Universal Delegator)

contract DeployVaultV2Script is DeployVaultV2Base {
    // Configurations - reAmplify

    // Name of the ERC20 representing shares in the vault
    string NAME = "reAmplify WBTC";
    // Symbol of the ERC20 representing shares in the vault
    string SYMBOL = "raWBTC";
    // Address of the owner of the vault who can migrate the vault to new versions whitelisted by Symbiotic
    address OWNER = 0xa2163bff0F2EBD4894aF901C642E88dCe9FC3574;
    // Address of the vault asset token (WBTC mainnet)
    address ASSET = 0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599;

    // Optional

    // Deposit limit (maximum amount of assets allowed in the vault); 0 = unlimited
    uint256 DEPOSIT_LIMIT = 0;
    // Whether deposits are restricted to whitelisted depositors
    bool DEPOSIT_WHITELIST = false;
    // Initial whitelisted depositor (used only when DEPOSIT_WHITELIST is true)
    address DEPOSITOR_TO_WHITELIST = 0x0000000000000000000000000000000000000000;

    function run() public {
        runBase(
            DeployVaultV2Params({
                owner: OWNER,
                vaultParams: VaultV2Params({
                    baseParams: IVaultV2.InitParams({
                        name: NAME,
                        symbol: SYMBOL,
                        asset: ASSET,
                        depositWhitelist: DEPOSIT_WHITELIST,
                        depositorToWhitelist: DEPOSITOR_TO_WHITELIST,
                        depositLimit: DEPOSIT_LIMIT,
                        isDepositLimit: DEPOSIT_LIMIT != 0,
                        defaultAdminRoleHolder: OWNER,
                        managementFeeRoleHolder: OWNER,
                        performanceFeeRoleHolder: OWNER,
                        depositLimitSetRoleHolder: OWNER,
                        depositorWhitelistRoleHolder: OWNER,
                        isDepositLimitSetRoleHolder: OWNER,
                        depositWhitelistSetRoleHolder: OWNER,
                        delegatorParams: abi.encode(
                            IUniversalDelegator.InitParams({
                                allocateRoleHolder: OWNER,
                                deallocateRoleHolder: OWNER,
                                forceDeallocateRoleHolder: OWNER,
                                addAdapterRoleHolder: OWNER,
                                swapAdaptersRoleHolder: OWNER,
                                defaultAdminRoleHolder: OWNER,
                                removeAdapterRoleHolder: OWNER,
                                setAdapterLimitsRoleHolder: OWNER,
                                setAutoAllocateAdaptersRoleHolder: OWNER
                            })
                        )
                    })
                })
            })
        );
    }
}
