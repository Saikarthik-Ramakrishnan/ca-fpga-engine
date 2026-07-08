// grid_streamer.v
//
// Takes a live, constantly-changing grid state and reports it over a
// single UART wire, forever, one snapshot at a time.
//
// The core problem this solves: the grid can change every single clock
// cycle, but sending even one snapshot over UART takes many, many clock
// cycles (a full byte takes CLKS_PER_BIT * 10 cycles: start + 8 data +
// stop). There is no way to report every generation. So this module
// doesn't try: the instant it finishes sending one snapshot, it grabs
// whatever the grid looks like right now and starts sending that. Some
// generations are simply never reported, the same way a camera doesn't
// capture every possible instant of real motion, only frames at whatever
// rate it can manage.
//
// Each transmission is one SYNC_BYTE followed by NUM_BYTES payload bytes
// (the grid, sliced 8 bits at a time, byte 0 = bits [7:0], byte 1 =
// bits [15:8], and so on). The sync byte exists so a receiver on the PC
// side can find the start of a frame even if it started listening
// mid-stream: it just watches for that fixed byte value and knows
// NUM_BYTES payload bytes follow it, every time.

module grid_streamer #(
    parameter NUM_BYTES    = 8,     // grid width in bytes (64 bits = 8 bytes)
    parameter CLKS_PER_BIT = 234
)(
    input  wire                      clk,
    input  wire                      rst_n,
    input  wire [NUM_BYTES*8-1:0]    grid_in,
    output wire                      tx_serial
);

    localparam [7:0] SYNC_BYTE = 8'hAA;

    localparam LATCH          = 3'd0;
    localparam PRESENT_BYTE   = 3'd1;
    localparam WAIT_BUSY_HIGH = 3'd2;
    localparam WAIT_BUSY_LOW  = 3'd3;

    reg [2:0]              state;
    reg [NUM_BYTES*8-1:0]  latched_grid;
    reg [$clog2(NUM_BYTES+1)-1:0] byte_idx;  // 0 = sync byte, 1..NUM_BYTES = payload

    reg [7:0]  tx_byte;
    reg        tx_start;
    wire       tx_busy;

    uart_tx #(
        .CLKS_PER_BIT (CLKS_PER_BIT)
    ) u_uart (
        .clk       (clk),
        .rst_n     (rst_n),
        .tx_start  (tx_start),
        .tx_byte   (tx_byte),
        .tx_serial (tx_serial),
        .tx_busy   (tx_busy)
    );

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state        <= LATCH;
            byte_idx     <= 0;
            latched_grid <= 0;
            tx_byte      <= 8'd0;
            tx_start     <= 1'b0;
        end else begin
            tx_start <= 1'b0;  // default: only asserted for exactly 1 cycle

            case (state)

                LATCH: begin
                    // grab whatever the grid looks like right now, and
                    // start a fresh frame from byte 0 (the sync byte).
                    latched_grid <= grid_in;
                    byte_idx     <= 0;
                    state        <= PRESENT_BYTE;
                end

                PRESENT_BYTE: begin
                    if (!tx_busy) begin
                        tx_byte  <= (byte_idx == 0)
                                    ? SYNC_BYTE
                                    : latched_grid[(byte_idx - 1) * 8 +: 8];
                        tx_start <= 1'b1;
                        state    <= WAIT_BUSY_HIGH;
                    end
                end

                WAIT_BUSY_HIGH: begin
                    // confirm uart_tx has actually started this byte
                    // before we start waiting for it to finish.
                    if (tx_busy)
                        state <= WAIT_BUSY_LOW;
                end

                WAIT_BUSY_LOW: begin
                    if (!tx_busy) begin
                        if (byte_idx == NUM_BYTES) begin
                            state <= LATCH;  // full frame sent, grab a fresh one
                        end else begin
                            byte_idx <= byte_idx + 1'b1;
                            state    <= PRESENT_BYTE;
                        end
                    end
                end

                default: state <= LATCH;
            endcase
        end
    end

endmodule
