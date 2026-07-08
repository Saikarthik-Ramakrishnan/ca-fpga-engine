// uart_tx.v
//
// Sends one byte at a time over a single wire, the standard UART way:
// idle high, then for each byte: 1 start bit (low), 8 data bits (LSB
// first), 1 stop bit (high), then back to idle.
//
// CLKS_PER_BIT sets the baud rate: it's how many clock cycles make up one
// bit's worth of time on the wire. Real hardware would set this to
// (system clock frequency) / (baud rate), e.g. 27,000,000 / 115,200 is
// about 234. Simulation uses a much smaller number just to keep the
// waveform short; the logic doesn't care what the number is.
//
// tx_busy tells whoever is feeding us bytes "don't send another one yet,
// I'm still sending this one." That handshake is the entire interface.

module uart_tx #(
    parameter CLKS_PER_BIT = 234
)(
    input  wire       clk,
    input  wire       rst_n,
    input  wire       tx_start,   // pulse high for 1 cycle to send tx_byte
    input  wire [7:0] tx_byte,
    output reg        tx_serial,  // the actual wire, idles high
    output reg        tx_busy
);

    localparam IDLE  = 2'd0;
    localparam START = 2'd1;
    localparam DATA  = 2'd2;
    localparam STOP  = 2'd3;

    reg [1:0]  state;
    reg [15:0] clk_count;   // counts up to CLKS_PER_BIT within one bit period
    reg [2:0]  bit_index;   // which of the 8 data bits we're on
    reg [7:0]  byte_latched;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state        <= IDLE;
            tx_serial    <= 1'b1;   // idle state of the wire is high
            tx_busy      <= 1'b0;
            clk_count    <= 0;
            bit_index    <= 0;
            byte_latched <= 8'd0;
        end else begin
            case (state)

                IDLE: begin
                    tx_serial <= 1'b1;
                    clk_count <= 0;
                    bit_index <= 0;
                    if (tx_start) begin
                        byte_latched <= tx_byte;  // latch it so it can't change mid-send
                        tx_busy      <= 1'b1;
                        state        <= START;
                    end else begin
                        tx_busy <= 1'b0;
                    end
                end

                START: begin
                    tx_serial <= 1'b0;  // start bit: pull the wire low
                    if (clk_count < CLKS_PER_BIT - 1) begin
                        clk_count <= clk_count + 1;
                    end else begin
                        clk_count <= 0;
                        state     <= DATA;
                    end
                end

                DATA: begin
                    tx_serial <= byte_latched[bit_index];  // LSB first
                    if (clk_count < CLKS_PER_BIT - 1) begin
                        clk_count <= clk_count + 1;
                    end else begin
                        clk_count <= 0;
                        if (bit_index < 7) begin
                            bit_index <= bit_index + 1;
                        end else begin
                            bit_index <= 0;
                            state     <= STOP;
                        end
                    end
                end

                STOP: begin
                    tx_serial <= 1'b1;  // stop bit: release the wire high
                    if (clk_count < CLKS_PER_BIT - 1) begin
                        clk_count <= clk_count + 1;
                    end else begin
                        clk_count <= 0;
                        tx_busy   <= 1'b0;
                        state     <= IDLE;
                    end
                end

                default: state <= IDLE;
            endcase
        end
    end

endmodule
