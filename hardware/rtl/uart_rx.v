// uart_rx.v
//
// Receives one byte at a time over a single wire: the mirror image of
// uart_tx.v. The wire idles high; a byte is 1 start bit (low), 8 data
// bits (LSB first), 1 stop bit (high).
//
// Two problems a receiver has that a transmitter doesn't:
//
// 1. The incoming wire is asynchronous. It comes from a different chip
//    with a different clock, so it can change at any instant, including
//    exactly on our clock edge. Feeding that straight into a state
//    machine risks metastability (a flip-flop caught mid-transition,
//    outputting garbage). The fix is standard: pass the wire through two
//    back-to-back flip-flops before anything looks at it. Costs two
//    clocks of delay, buys a clean signal.
//
// 2. We have to decide WHEN to look at the wire. The transmitter holds
//    each bit for CLKS_PER_BIT clocks; the safest instant to sample is
//    the middle of that window, farthest from both edges. So: detect the
//    falling edge of the start bit, wait half a bit period, confirm the
//    wire is still low (a real start bit, not a glitch), then sample
//    every CLKS_PER_BIT clocks after that, landing mid-bit each time.
//
// If the stop bit isn't high when sampled, the byte is framing-broken
// (noise, baud mismatch, unplugged mid-byte) and is silently dropped:
// rx_dv never pulses for it.

module uart_rx #(
    parameter CLKS_PER_BIT = 234   // 27 MHz / 115200 baud = 234
)(
    input  wire       clk,
    input  wire       rst_n,
    input  wire       rx_serial,   // the raw wire from the outside world
    output reg        rx_dv,       // pulses high for 1 cycle when rx_byte is valid
    output reg  [7:0] rx_byte
);

    localparam IDLE  = 3'd0;
    localparam START = 3'd1;
    localparam DATA  = 3'd2;
    localparam STOP  = 3'd3;

    // --- 2-flop synchronizer: everything downstream reads rx_sync only.
    reg rx_meta, rx_sync;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            rx_meta <= 1'b1;   // reset to the wire's idle level
            rx_sync <= 1'b1;
        end else begin
            rx_meta <= rx_serial;
            rx_sync <= rx_meta;
        end
    end

    reg [2:0]  state;
    reg [15:0] clk_count;
    reg [2:0]  bit_index;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state     <= IDLE;
            clk_count <= 0;
            bit_index <= 0;
            rx_dv     <= 1'b0;
            rx_byte   <= 8'd0;
        end else begin
            rx_dv <= 1'b0;  // default: only asserted for exactly 1 cycle

            case (state)

                IDLE: begin
                    clk_count <= 0;
                    bit_index <= 0;
                    if (rx_sync == 1'b0)      // falling edge: possible start bit
                        state <= START;
                end

                START: begin
                    // wait to the middle of the start bit, then confirm
                    // the wire is still low. If it bounced back high this
                    // was a glitch, not a byte: go back to idle.
                    if (clk_count == (CLKS_PER_BIT - 1) / 2) begin
                        clk_count <= 0;
                        if (rx_sync == 1'b0)
                            state <= DATA;
                        else
                            state <= IDLE;
                    end else begin
                        clk_count <= clk_count + 1;
                    end
                end

                DATA: begin
                    // from mid-start, every CLKS_PER_BIT clocks lands
                    // mid-bit on each data bit in turn. LSB first, same
                    // order uart_tx sends them.
                    if (clk_count < CLKS_PER_BIT - 1) begin
                        clk_count <= clk_count + 1;
                    end else begin
                        clk_count          <= 0;
                        rx_byte[bit_index] <= rx_sync;
                        if (bit_index < 7) begin
                            bit_index <= bit_index + 1;
                        end else begin
                            bit_index <= 0;
                            state     <= STOP;
                        end
                    end
                end

                STOP: begin
                    // sample mid-stop-bit. High = clean frame, publish the
                    // byte. Low = framing error, drop it without a word.
                    if (clk_count < CLKS_PER_BIT - 1) begin
                        clk_count <= clk_count + 1;
                    end else begin
                        clk_count <= 0;
                        if (rx_sync == 1'b1)
                            rx_dv <= 1'b1;
                        state <= IDLE;
                    end
                end

                default: state <= IDLE;
            endcase
        end
    end

endmodule
