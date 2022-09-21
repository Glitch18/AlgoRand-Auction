from pyteal import *

def approval_program():
    seller_key = Bytes("seller")
    nft_id_key = Bytes("nft_id")
    auction_start_time_key = Bytes("auction_start_time")
    auction_end_time_key = Bytes("auction_end_time")
    base_price_key = Bytes("base_price")
    current_bid_account_key = Bytes("current_bid_account")
    current_bid_amount_key = Bytes("current_bid_amount")

    @Subroutine(TealType.none)
    def transferNFT(receiver: Expr, nftId: Expr):
        nft_balance = AssetHolding.balance(
            Global.current_application_address(), nftId
        )
        return Seq(
            nft_balance,
            If(nft_balance.value() > Int(0)).Then(
                Seq(
                    InnerTxnBuilder.Begin(),
                    InnerTxnBuilder.SetFields(
                        {
                            TxnField.type_enum: TxnType.AssetTransfer,
                            TxnField.xfer_asset: nftId,
                            TxnField.asset_close_to: receiver
                        }
                    ),
                    InnerTxnBuilder.Submit()
                )
            ),
        )

    @Subroutine(TealType.none)
    def transferLeftFunds(account: Expr):
        return If(Balance(Global.current_application_address()) != Int(0)).Then(
            Seq(
                InnerTxnBuilder.Begin(),
                InnerTxnBuilder.SetFields(
                    {
                        TxnField.type_enum: TxnType.Payment,
                        TxnField.close_remainder_to: account
                    }
                ),
                InnerTxnBuilder.Submit()
            )
        )

    @Subroutine(TealType.none)
    def repayLastBidder():
        previous_bidder_account = App.globalGet(current_bid_account_key)
        previous_bidder_amount = App.globalGet(current_bid_amount_key)
        return Seq(
            InnerTxnBuilder.Begin(),
            InnerTxnBuilder.SetFields(
                {
                    TxnField.type_enum: TxnType.Payment,
                    TxnField.receiver: previous_bidder_account,
                    TxnField.amount: previous_bidder_amount,
                }
            ),
            InnerTxnBuilder.Submit()
        )

    on_create = Seq(
        App.globalPut(seller_key, Txn.application_args[0]),
        App.globalPut(nft_id_key, Txn.application_args[1]),
        App.globalPut(auction_start_time_key, Btoi(Txn.application_args[2])),
        App.globalPut(auction_end_time_key, Btoi(Txn.application_args[3])),
        App.globalPut(base_price_key, Txn.application_args[4]),
        App.globalPut(current_bid_account_key, Global.zero_address()),
        App.globalPut(current_bid_amount_key, Txn.application_args[4]),
        Assert(
            And(
                Global.latest_timestamp() < Btoi(Txn.application_args[2]),
                Btoi(Txn.application_args[2]) < Btoi(Txn.application_args[3])
            )
        ),
        Approve()
    )

    on_setup = Seq(
        Assert(Global.latest_timestamp() < App.globalGet(auction_start_time_key)),
        InnerTxnBuilder.Begin(),
        InnerTxnBuilder.SetFields(
            {
                TxnField.type_enum: TxnType.AssetTransfer,
                TxnField.xfer_asset: App.globalGet(nft_id_key),
                TxnField.asset_receiver: Global.current_application_address()
            }
        ),
        InnerTxnBuilder.Submit(),
        Approve(),
    )

    on_bid_txn_index = Txn.group_index() - Int(1)
    on_bid_nft_balance = AssetHolding.balance(
        Global.current_application_address(), App.globalGet(nft_id_key)
    )
    on_bid = Seq(
        on_bid_nft_balance,
        Assert(
            And(
                Global.latest_timestamp() >= App.globalGet(auction_start_time_key),
                Global.latest_timestamp() < App.globalGet(auction_end_time_key),
                on_bid_nft_balance.value() > Int(0),
                Gtxn[on_bid_txn_index].type_enum() == TxnType.Payment,
                Gtxn[on_bid_txn_index].sender() == Txn.sender(),
                Gtxn[on_bid_txn_index].receiver()
                == Global.current_application_address(),
                Gtxn[on_bid_txn_index].amount() >= Global.min_txn_fee(),
            ),
        ),
        If(Gtxn[on_bid_txn_index].amount() >= App.globalGet(current_bid_amount_key)).Then(
            Seq(
                If(App.globalGet(current_bid_account_key) != Global.zero_address()).Then(
                    repayLastBidder(),
                ),
                # Update the top bidder details
                App.globalPut(current_bid_account_key, Gtxn[on_bid_txn_index].sender()),
                App.globalPut(current_bid_amount_key, Gtxn[on_bid_txn_index].amount()),
                Approve(),
            )
        ),
        Reject(),
    )

    on_delete = Seq(
        If(Global.latest_timestamp() < App.globalGet(auction_start_time_key)).Then(
            Seq(
                Assert(Txn.sender() == App.globalGet(seller_key)),
                transferNFT(
                    App.globalGet(seller_key),
                    App.globalGet(nft_id_key),
                ),
                transferLeftFunds(
                    App.globalGet(seller_key),
                ),
                Approve(),
            )
        ),
        If(Global.latest_timestamp() > App.globalGet(auction_end_time_key)).Then(
            Seq(
                If(App.globalGet(current_bid_account_key) == Global.zero_address()).Then(
                    transferNFT(
                        App.globalGet(seller_key),
                        App.globalGet(nft_id_key),
                    ),
                ).Else(
                    transferNFT(
                        App.globalGet(current_bid_account_key),
                        App.globalGet(nft_id_key),
                    )
                ),
                transferLeftFunds(
                    App.globalGet(seller_key)
                ),
                Approve()
            )
        ),
        Reject(),
    )

    on_call = Cond(
        [Txn.application_args[0] == Bytes("setup"), on_setup],
        [Txn.application_args[0] == Bytes("bid"), on_bid]
    )

    program = Cond(
        [Txn.application_id() == Int(0), on_create],
        [Txn.on_completion() == OnComplete.NoOp, on_call],
        [Txn.on_completion() == OnComplete.DeleteApplication, on_delete],
        [
            Or(
                Txn.on_completion() == OnComplete.ClearState,
                Txn.on_completion() == OnComplete.CloseOut,
                Txn.on_completion() == OnComplete.OptIn,
                Txn.on_completion() == OnComplete.UpdateApplication,
            ),
            Reject()
        ],
    )

    return program

def clear_state_program():
    return Approve()

if __name__ == "__main__":
    with open("auction_approval.teal", "w") as f:
        compiled = compileTeal(approval_program(), mode=Mode.Application, version=5)
        f.write(compiled)

    with open("auction_clear_state.teal", "w") as f:
        compiled = compileTeal(clear_state_program(), mode=Mode.Application, version=5)
        f.write(compiled)

