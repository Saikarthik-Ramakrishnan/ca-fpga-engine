// cellnet_top.v
//
// The whole chip, from the outside: a clock, a reset, a way to seed the
// grid, and one wire out (tx_serial) that a PC's USB-to-serial adapter
// would actually connect to. Everything in between (the grid, the
// streamer, the UART transmitter) is internal.

module cellnet_top #(
    parameter ROWS         = 8,
    parameter COLS         = 8,
    parameter CLKS_PER_BIT = 234
)(
    input  wire                  clk,
    input  wire                  rst_n,
    input  wire                  load,
    input  wire [ROWS*COLS-1:0]  seed,
    output wire                  tx_serial
);

    localparam NUM_BYTES = (ROWS * COLS) / 8;

    wire [ROWS*COLS-1:0] grid_state;

    ca_grid #(
        .ROWS (ROWS),
        .COLS (COLS)
    ) u_grid (
        .clk       (clk),
        .rst_n     (rst_n),
        .load      (load),
        .seed      (seed),
        .grid_out  (grid_state)
    );

    grid_streamer #(
        .NUM_BYTES    (NUM_BYTES),
        .CLKS_PER_BIT (CLKS_PER_BIT)
    ) u_streamer (
        .clk       (clk),
        .rst_n     (rst_n),
        .grid_in   (grid_state),
        .tx_serial (tx_serial)
    );

endmodule
