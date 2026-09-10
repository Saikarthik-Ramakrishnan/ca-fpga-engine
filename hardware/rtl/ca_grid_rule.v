// ca_grid_rule.v
//
// The parallel fabric, built from ca_cell_rule instead of ca_cell. Wiring,
// indexing and toroidal wrap are identical to ca_grid.v, cell for cell.
// The only difference: two 9-bit rule masks fan out to every cell.
//
// That fan-out is a broadcast, structurally the same as clk / rst_n /
// load, which already reach every cell. It moves no information between
// cells. Each cell still sees its own state plus eight neighbor wires and
// nothing else, and the whole grid still resolves on one clock edge.
//
// Rectangular grids work; the golden-model cross-check is square only,
// matching ca_grid.v and every other use in this project.

module ca_grid_rule #(
    parameter ROWS = 8,
    parameter COLS = 8
)(
    input  wire                      clk,
    input  wire                      rst_n,     // active-low async reset
    input  wire                      load,      // when high, seed the grid from `seed`
    input  wire [ROWS*COLS-1:0]      seed,      // initial state, one bit per cell
    input  wire [8:0]                birth,     // broadcast rule mask
    input  wire [8:0]                survive,   // broadcast rule mask
    output wire [ROWS*COLS-1:0]      grid_out   // current state, one bit per cell
);

    // flattened index: cell (r, c) lives at bit r*COLS + c, same as ca_grid.v
    genvar r, c;
    generate
        for (r = 0; r < ROWS; r = r + 1) begin : row
            for (c = 0; c < COLS; c = c + 1) begin : col

                localparam integer UP    = ((r + ROWS - 1) % ROWS) * COLS;
                localparam integer DOWN  = ((r + 1)        % ROWS) * COLS;
                localparam integer HERE  = r * COLS;
                localparam integer LEFT  = (c + COLS - 1) % COLS;
                localparam integer RIGHT = (c + 1)        % COLS;

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

                wire cell_state;

                ca_cell_rule u_cell (
                    .clk       (clk),
                    .rst_n     (rst_n),
                    .neighbors (nbrs),
                    .load      (load),
                    .seed_bit  (seed[HERE + c]),
                    .birth     (birth),
                    .survive   (survive),
                    .state     (cell_state)
                );

                assign grid_out[HERE + c] = cell_state;

            end
        end
    endgenerate

endmodule
