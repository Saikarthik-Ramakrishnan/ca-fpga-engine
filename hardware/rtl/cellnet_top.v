// cellnet_top.v  (Phase 4.5: the flashable chip. Phase 5b: selectable rule)
//
// The whole chip, from the outside, is exactly the physical pins on the
// Tang Primer 20K dock: the 27 MHz oscillator, the reset key, and the two
// UART wires on the USB-serial bridge. No test-only ports.
//
//   PC --(rx_serial)--> uart_rx --+-> seed_loader --> [load/seed] ca_grid*
//                                 `-> rule_loader --> [birth/survive]
//   PC <--(tx_serial)-- uart_tx <---- grid_streamer <-- [state]    ca_grid*
//
// Seed goes in over one wire, frames come back out over the other. That
// closes the loop the console's Live tab has been waiting for.
//
// THE GENERATION PACER, and why it exists: the grid computes one full
// generation per clock edge. At 27 MHz that is 27 million generations a
// second. A glider would cross the board 100,000 times between two UART
// frames; every frame would look like an unrelated random sample. So the
// chip has to deliberately idle between generations, and the interesting
// part is HOW without touching the verified cell:
//
// ca_cell has no enable pin, and adding one would mean re-opening a
// module that passed exhaustive 512-case verification. But it already
// has a load path: when load=1, a cell takes seed_bit instead of the
// rule result. So to freeze the grid, feed its own state back into
// itself: load=1, seed=grid_state means every cell re-loads the value
// it already holds. Nothing changes. Drop load for exactly one clock and
// the whole fabric computes exactly one generation. The pacer below does
// that once every GEN_DIV clocks. Same silicon, zero changes to the
// verified modules, and the "massively parallel single-edge update"
// claim stays literally true: it just happens on a schedule.
//
// Priority: a seed arriving from the PC beats everything. On the clock
// seed_loader pulses load, the mux feeds the loader's snapshot in
// instead of the hold-feedback, and the generation counter restarts so
// the fresh pattern gets a full dwell before its first step.
//
// RULE_CFG picks which fabric gets built:
//
//   RULE_CFG = 1 (default)  ca_grid_rule + rule_loader. The rule is 18 bits
//                           in a register, settable over UART with the 0x33
//                           command, Conway out of reset. All five console
//                           rulesets run on the same bitstream.
//   RULE_CFG = 0            ca_grid, Conway welded into the gates. The
//                           smaller build, and the one to reach for if a
//                           large grid stops fitting.
//
// Both are real builds and both are covered by their own loopback test.

module cellnet_top #(
    parameter ROWS         = 16,
    parameter COLS         = 16,
    parameter CLKS_PER_BIT = 234,       // 27 MHz / 115200 baud
    parameter GEN_DIV      = 2700000,   // clocks per generation: 10 gen/s at 27 MHz
    parameter TIMEOUT_CLKS = 2700000,   // seed transfer timeout: ~100 ms at 27 MHz
    parameter RULE_CFG     = 1          // 1: runtime-selectable rule, 0: fixed Conway
)(
    input  wire       clk,        // H11: 27 MHz dock oscillator
    input  wire       rst_n,      // T5:  dock key, active low
    input  wire       rx_serial,  // T13: from the PC (BL616 USB-serial bridge)
    output wire       tx_serial,  // M11: to the PC
    output wire [1:0] led         // L16, L14: status (assumed active low,
                                  // as on Sipeed docks; if yours light
                                  // inverted, flip the two assigns below)
);

    localparam NUM_BYTES = (ROWS * COLS) / 8;

    // ---- receive path: wire -> bytes ----
    wire       rx_dv;
    wire [7:0] rx_byte;

    uart_rx #(
        .CLKS_PER_BIT (CLKS_PER_BIT)
    ) u_rx (
        .clk       (clk),
        .rst_n     (rst_n),
        .rx_serial (rx_serial),
        .rx_dv     (rx_dv),
        .rx_byte   (rx_byte)
    );

    // ---- rule register: present only in the configurable build ----
    // In the fixed build these collapse to the Conway constants and
    // nothing downstream can tell the difference.
    wire [8:0] birth;
    wire [8:0] survive;
    wire       rule_consuming;
    wire       rule_load;
    wire       seed_receiving;

    generate
        if (RULE_CFG) begin : g_rule
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
                .consuming (rule_consuming),
                .rule_load (rule_load)
            );
        end else begin : g_fixed_rule
            assign birth          = 9'b000001000;  // B3
            assign survive        = 9'b000001100;  // S23
            assign rule_consuming = 1'b0;
            assign rule_load      = 1'b0;
        end
    endgenerate

    // seed_loader must not see the rule command's payload bytes: one of
    // them could legally be 0x55 and would otherwise start a bogus seed.
    // rule_loader raises `consuming` for exactly those three bytes.
    wire seed_rx_dv = rx_dv && !rule_consuming;

    wire                 seed_load;
    wire [ROWS*COLS-1:0] seed_data;

    seed_loader #(
        .NUM_BYTES    (NUM_BYTES),
        .TIMEOUT_CLKS (TIMEOUT_CLKS)
    ) u_loader (
        .clk       (clk),
        .rst_n     (rst_n),
        .rx_dv     (seed_rx_dv),
        .rx_byte   (rx_byte),
        .load      (seed_load),
        .seed      (seed_data),
        .receiving (seed_receiving)
    );

    // ---- generation pacer ----
    reg [31:0] gen_count;
    wire       gen_tick = (gen_count == GEN_DIV - 1);

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            gen_count <= 0;
        else if (seed_load || gen_tick)
            gen_count <= 0;
        else
            gen_count <= gen_count + 1;
    end

    // ---- the grid, held still except one clock per GEN_DIV ----
    wire [ROWS*COLS-1:0] grid_state;

    // load is high (hold or seed) on every clock except the single
    // gen_tick clock, where the rule runs. A seed pulse wins over a
    // tick landing on the same clock.
    wire                 grid_load = seed_load || !gen_tick;
    wire [ROWS*COLS-1:0] grid_seed = seed_load ? seed_data : grid_state;

    generate
        if (RULE_CFG) begin : g_grid_cfg
            ca_grid_rule #(
                .ROWS (ROWS),
                .COLS (COLS)
            ) u_grid (
                .clk      (clk),
                .rst_n    (rst_n),
                .load     (grid_load),
                .seed     (grid_seed),
                .birth    (birth),
                .survive  (survive),
                .grid_out (grid_state)
            );
        end else begin : g_grid_fixed
            ca_grid #(
                .ROWS (ROWS),
                .COLS (COLS)
            ) u_grid (
                .clk      (clk),
                .rst_n    (rst_n),
                .load     (grid_load),
                .seed     (grid_seed),
                .grid_out (grid_state)
            );
        end
    endgenerate

    // ---- transmit path: state -> frames -> wire ----
    grid_streamer #(
        .NUM_BYTES    (NUM_BYTES),
        .CLKS_PER_BIT (CLKS_PER_BIT)
    ) u_streamer (
        .clk       (clk),
        .rst_n     (rst_n),
        .grid_in   (grid_state),
        .tx_serial (tx_serial)
    );

    // ---- status LEDs ----
    // led[0]: latches on after the first accepted command, seed or rule.
    //         "The PC has talked to me at least once."
    // led[1]: lit while any command transfer is in flight (sub-second blink).
    reg talked_to;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            talked_to <= 1'b0;
        else if (seed_load || rule_load)
            talked_to <= 1'b1;
    end

    assign led[0] = ~talked_to;                             // active low
    assign led[1] = ~(seed_receiving || rule_consuming);    // active low

endmodule
