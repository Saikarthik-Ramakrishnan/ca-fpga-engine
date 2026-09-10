// tb_command_stack.v  (simulation harness, not part of the chip)
//
// uart_rx + rule_loader + seed_loader, wired exactly the way cellnet_top
// wires them, with the internal signals brought out so test_rule_loader.py
// can watch the two loaders interact directly.
//
// The one line that matters is `seed_rx_dv`: rule_loader raises
// `consuming` while it is eating its three payload bytes, and that gates
// rx_dv away from seed_loader so a 0x55 inside a rule payload cannot fake
// a seed command. The mirror guard lives inside rule_loader, which only
// recognises 0x33 while seed_loader reports it is not mid-transfer.
//
// This harness must stay in step with cellnet_top.v. The end-to-end proof
// that it does is test_cellnet_rules.py, which drives the real top through
// its real pins and nothing else.

module tb_command_stack #(
    parameter CLKS_PER_BIT = 4,
    parameter NUM_BYTES    = 8,
    parameter TIMEOUT_CLKS = 2000
)(
    input  wire                   clk,
    input  wire                   rst_n,
    input  wire                   rx_serial,

    output wire                   rx_dv,
    output wire [7:0]             rx_byte,

    output wire [8:0]             birth,
    output wire [8:0]             survive,
    output wire                   consuming,
    output wire                   rule_load,

    output wire                   seed_load,
    output wire [NUM_BYTES*8-1:0] seed,
    output wire                   seed_receiving
);

    uart_rx #(
        .CLKS_PER_BIT (CLKS_PER_BIT)
    ) u_rx (
        .clk       (clk),
        .rst_n     (rst_n),
        .rx_serial (rx_serial),
        .rx_dv     (rx_dv),
        .rx_byte   (rx_byte)
    );

    rule_loader #(
        .TIMEOUT_CLKS (TIMEOUT_CLKS)
    ) u_rule (
        .clk       (clk),
        .rst_n     (rst_n),
        .rx_dv     (rx_dv),
        .rx_byte   (rx_byte),
        .seed_busy (seed_receiving),
        .birth     (birth),
        .survive   (survive),
        .consuming (consuming),
        .rule_load (rule_load)
    );

    wire seed_rx_dv = rx_dv && !consuming;

    seed_loader #(
        .NUM_BYTES    (NUM_BYTES),
        .TIMEOUT_CLKS (TIMEOUT_CLKS)
    ) u_seed (
        .clk       (clk),
        .rst_n     (rst_n),
        .rx_dv     (seed_rx_dv),
        .rx_byte   (rx_byte),
        .load      (seed_load),
        .seed      (seed),
        .receiving (seed_receiving)
    );

endmodule
