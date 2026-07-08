// ca_grid.v
//
// Phase 3: the parallel fabric. This is where the whole thesis of the
// project actually shows up in hardware.
//
// We take ca_cell (one verified cell) and instantiate it once per grid
// position using a `generate` block. `generate` is a build-time construct:
// it is NOT a loop that runs while the chip is powered. It's an instruction
// to the synthesis tool that says "stamp out this hardware ROWS*COLS times,
// and wire each copy up according to these index rules." When it's done,
// there are ROWS*COLS physical copies of ca_cell sitting on the fabric,
// each permanently wired to its 8 neighbors. On every clock edge, all of
// them compute their next state at the same instant -- that simultaneity
// is the thing a CPU structurally cannot do and the FPGA gives for free.
//
// Neighbor wrap is toroidal (the grid is a doughnut: the top row's "up"
// neighbor is the bottom row, the left column's "left" is the right column).
// This matches the % wraparound in golden_rule.py / the JS console exactly,
// so the hardware grid and the software reference evolve identically.

module ca_grid #(
    parameter ROWS = 8,
    parameter COLS = 8
)(
    input  wire                      clk,
    input  wire                      rst_n,     // active-low async reset
    input  wire                      load,      // when high, seed the grid from `seed`
    input  wire [ROWS*COLS-1:0]      seed,      // initial state, one bit per cell
    output wire [ROWS*COLS-1:0]      grid_out   // current state, one bit per cell
);

    // flattened index helper: cell (r, c) lives at bit r*COLS + c
    // (Verilog generate can't call functions for indexing cleanly across
    //  tool versions, so we compute indices inline below.)

    genvar r, c;
    generate
        for (r = 0; r < ROWS; r = r + 1) begin : row
            for (c = 0; c < COLS; c = c + 1) begin : col

                // --- gather this cell's 8 neighbor states, with toroidal
                //     wraparound. (r+ROWS-1)%ROWS is "one row up, wrapping";
                //     (r+1)%ROWS is "one row down, wrapping"; same for cols.
                localparam integer UP    = ((r + ROWS - 1) % ROWS) * COLS;
                localparam integer DOWN  = ((r + 1)        % ROWS) * COLS;
                localparam integer HERE  = r * COLS;
                localparam integer LEFT  = (c + COLS - 1) % COLS;
                localparam integer RIGHT = (c + 1)        % COLS;

                // pack the 8 neighbors into one 8-bit bus for ca_cell.
                // order is arbitrary but must be consistent; ca_cell only
                // counts how many are set, so ordering doesn't affect the rule.
                wire [7:0] nbrs = {
                    grid_out[UP    + LEFT ],   // up-left
                    grid_out[UP    + c    ],   // up
                    grid_out[UP    + RIGHT],   // up-right
                    grid_out[HERE  + LEFT ],   // left
                    grid_out[HERE  + RIGHT],   // right
                    grid_out[DOWN  + LEFT ],   // down-left
                    grid_out[DOWN  + c    ],   // down
                    grid_out[DOWN  + RIGHT]    // down-right
                };

                // per-cell state register, with a load mux so we can seed
                // the grid. When `load` (the grid-level input) is high, the
                // cell takes its bit from `seed` instead of computing the
                // rule -- that's how we set up an initial pattern (a
                // glider, a random soup, etc).
                wire cell_state;

                ca_cell u_cell (
                    .clk       (clk),
                    .rst_n     (rst_n),
                    .neighbors (nbrs),
                    .load      (load),
                    .seed_bit  (seed[HERE + c]),
                    .state     (cell_state)
                );

                assign grid_out[HERE + c] = cell_state;

            end
        end
    endgenerate

endmodule
