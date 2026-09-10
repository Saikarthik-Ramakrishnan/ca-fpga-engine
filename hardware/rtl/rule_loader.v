// rule_loader.v
//
// Second command on the same wire seed_loader already listens to:
//
//   0x33  <birth[7:0]>  <survive[7:0]>  <{6'b0, survive[8], birth[8]}>
//
// Three payload bytes carry the 18 bits of a totalistic outer-rule. Byte 0
// holds the low 8 birth bits, byte 1 the low 8 survive bits, byte 2 the two
// leftover top bits (bit 0 = birth[8], bit 1 = survive[8]). Low bits in the
// low byte, the same ordering seed_loader and grid_streamer use for grid
// data, so there is one byte-order convention in the whole project.
//
// 0x33 joins 0x55 (seed, in) and 0xAA (frame sync, out). All three are
// far apart in Hamming distance and none is a rotation of another.
//
// SHARING THE BYTE STREAM WITH seed_loader
// ----------------------------------------
// Both modules watch the same rx_dv/rx_byte pair off uart_rx, so each has
// to stay out of the other's payload. Two rules do it, and they are
// symmetric:
//
//   1. This module only recognises 0x33 as a command when seed_loader
//      reports it is NOT mid-transfer (`seed_busy`). A grid seed byte that
//      happens to equal 0x33 is payload, and is left alone.
//
//   2. While this module is eating its own three payload bytes it raises
//      `consuming`, and the top level uses that to gate rx_dv away from
//      seed_loader. A rule byte that happens to equal 0x55 therefore never
//      reaches seed_loader and cannot fake a seed command.
//
// That keeps seed_loader.v byte-for-byte unchanged and still covered by
// its own 4/4 testbench, rather than growing a second command into a
// module that is already verified.
//
// Timeout matches seed_loader's: a transfer that dies halfway is abandoned
// so the next command byte is not swallowed as payload. An abandoned rule
// transfer leaves the previous rule in force; the fabric never runs on a
// half-written rule, because birth/survive are only updated on the clock
// the third byte lands.
//
// Reset default is Conway B3/S23, so a freshly configured chip that is
// never sent a rule behaves exactly like the fixed-rule build.

module rule_loader #(
    parameter TIMEOUT_CLKS = 2700000   // ~100 ms at 27 MHz, same as seed_loader
)(
    input  wire        clk,
    input  wire        rst_n,
    input  wire        rx_dv,       // from uart_rx: byte valid pulse
    input  wire [7:0]  rx_byte,     // from uart_rx: the byte
    input  wire        seed_busy,   // seed_loader.receiving: do not grab mid-seed
    output reg  [8:0]  birth,       // broadcast to every cell
    output reg  [8:0]  survive,     // broadcast to every cell
    output wire        consuming,   // high while eating payload: gate seed_loader
    output reg         rule_load    // 1-cycle pulse: a complete rule landed
);

    localparam [7:0] CMD_RULE  = 8'h33;
    localparam       NUM_BYTES = 3;

    // Conway B3/S23 as 9-bit masks, bit k = "k live neighbors".
    localparam [8:0] BIRTH_CONWAY   = 9'b000001000;  // birth on exactly 3
    localparam [8:0] SURVIVE_CONWAY = 9'b000001100;  // survive on 2 or 3

    localparam WAIT_CMD = 1'b0;
    localparam RECV     = 1'b1;

    reg        state;
    reg [1:0]  byte_idx;
    reg [31:0] idle_clks;

    // staging registers: birth/survive only move when the whole rule is in,
    // so the fabric is never driven by a partially received mask.
    reg [7:0]  b_low;
    reg [7:0]  s_low;

    assign consuming = (state == RECV);

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state     <= WAIT_CMD;
            byte_idx  <= 2'd0;
            idle_clks <= 32'd0;
            b_low     <= 8'd0;
            s_low     <= 8'd0;
            birth     <= BIRTH_CONWAY;
            survive   <= SURVIVE_CONWAY;
            rule_load <= 1'b0;
        end else begin
            rule_load <= 1'b0;   // default: asserted for exactly 1 cycle

            case (state)

                WAIT_CMD: begin
                    idle_clks <= 32'd0;
                    // `!seed_busy` is the whole of guard 1: mid-seed, a 0x33
                    // on the wire is grid data and means nothing here.
                    if (rx_dv && !seed_busy && rx_byte == CMD_RULE) begin
                        byte_idx <= 2'd0;
                        state    <= RECV;
                    end
                end

                RECV: begin
                    if (rx_dv) begin
                        idle_clks <= 32'd0;
                        case (byte_idx)
                            2'd0: begin
                                b_low    <= rx_byte;
                                byte_idx <= 2'd1;
                            end
                            2'd1: begin
                                s_low    <= rx_byte;
                                byte_idx <= 2'd2;
                            end
                            default: begin
                                // third byte completes the rule: commit all
                                // 18 bits on this one clock edge.
                                birth     <= {rx_byte[0], b_low};
                                survive   <= {rx_byte[1], s_low};
                                rule_load <= 1'b1;
                                state     <= WAIT_CMD;
                            end
                        endcase
                    end else if (idle_clks >= TIMEOUT_CLKS - 1) begin
                        state <= WAIT_CMD;   // transfer died: keep the old rule
                    end else begin
                        idle_clks <= idle_clks + 1;
                    end
                end

                default: state <= WAIT_CMD;
            endcase
        end
    end

endmodule
