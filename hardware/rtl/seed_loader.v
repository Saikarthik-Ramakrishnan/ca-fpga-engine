// seed_loader.v
//
// The protocol layer between uart_rx and the grid. uart_rx hands over
// raw bytes with no idea what they mean; this module gives them meaning:
//
//   0x55  <payload byte 0> ... <payload byte NUM_BYTES-1>
//
// 0x55 is the SEED command. The payload that follows is a full grid
// snapshot in exactly the byte order grid_streamer sends frames out in:
// byte 0 = grid bits [7:0], byte 1 = bits [15:8], and so on. Same
// convention both directions, so the PC-side code that decodes outgoing
// frames can encode seeds with the identical slicing, just reversed.
//
// When the last payload byte lands, `load` pulses high for one clock
// with the assembled snapshot on `seed`. The grid's existing load path
// (built and verified back in Phase 2) does the rest.
//
// Why 0x55 and not just "first byte starts a seed": the wire is not
// trustworthy. If the PC opens the port mid-thought, or a byte gets
// mangled, the loader must not lock onto garbage. 0x55 (01010101) was
// picked to be the bit-inverse of the streamer's 0xAA sync byte:
// related on purpose, impossible to confuse.
//
// And why the timeout: if a seed transfer dies halfway (cable pulled,
// script killed), the loader would otherwise sit waiting for payload
// bytes forever, and the NEXT seed attempt's command byte would get
// swallowed as payload. So: if more than TIMEOUT_CLKS pass mid-transfer
// with no byte, abandon the partial seed and go back to listening for a
// command. Nothing is loaded; the grid never sees the broken transfer.

module seed_loader #(
    parameter NUM_BYTES    = 8,        // grid size in bytes (64 cells = 8)
    parameter TIMEOUT_CLKS = 2700000   // ~100 ms at 27 MHz
)(
    input  wire                   clk,
    input  wire                   rst_n,
    input  wire                   rx_dv,      // from uart_rx: byte valid pulse
    input  wire [7:0]             rx_byte,    // from uart_rx: the byte
    output reg                    load,       // 1-cycle pulse: seed is ready
    output reg  [NUM_BYTES*8-1:0] seed,       // the assembled grid snapshot
    output wire                   receiving   // high mid-transfer (status LED)
);

    localparam [7:0] CMD_SEED = 8'h55;

    localparam WAIT_CMD = 1'b0;
    localparam RECV     = 1'b1;

    reg                            state;
    reg [$clog2(NUM_BYTES+1)-1:0]  byte_idx;
    reg [31:0]                     idle_clks;   // clocks since last byte, in RECV

    assign receiving = (state == RECV);

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state     <= WAIT_CMD;
            byte_idx  <= 0;
            idle_clks <= 0;
            load      <= 1'b0;
            seed      <= 0;
        end else begin
            load <= 1'b0;  // default: only asserted for exactly 1 cycle

            case (state)

                WAIT_CMD: begin
                    idle_clks <= 0;
                    if (rx_dv && rx_byte == CMD_SEED) begin
                        byte_idx <= 0;
                        state    <= RECV;
                    end
                    // any other byte in WAIT_CMD is ignored: line noise,
                    // or leftovers from an aborted transfer.
                end

                RECV: begin
                    if (rx_dv) begin
                        idle_clks               <= 0;
                        seed[byte_idx*8 +: 8]   <= rx_byte;
                        if (byte_idx == NUM_BYTES - 1) begin
                            load  <= 1'b1;      // last byte: fire the seed
                            state <= WAIT_CMD;
                        end else begin
                            byte_idx <= byte_idx + 1'b1;
                        end
                    end else if (idle_clks >= TIMEOUT_CLKS - 1) begin
                        state <= WAIT_CMD;      // transfer died: abandon it
                    end else begin
                        idle_clks <= idle_clks + 1;
                    end
                end

                default: state <= WAIT_CMD;
            endcase
        end
    end

endmodule
