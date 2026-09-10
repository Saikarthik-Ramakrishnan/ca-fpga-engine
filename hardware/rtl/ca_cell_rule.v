// ca_cell_rule.v
//
// One cell, same as ca_cell.v, except the rule itself is data instead of
// gates. ca_cell.v hardwires Conway B3/S23 into two comparators. This
// version takes the rule as two 9-bit masks and looks the answer up:
//
//   birth[k]   = 1  ->  a dead cell with k live neighbors becomes alive
//   survive[k] = 1  ->  a live cell with k live neighbors stays alive
//
// Conway is birth = 9'b000001000, survive = 9'b000001100. HighLife,
// Day & Night, Seeds and Maze are four other values of the same 18 bits.
// The console's rule bank and golden_rule.py's RULES dict encode the
// identical masks, so "pick HighLife in the browser" and "run HighLife on
// the fabric" are now the same 18 bits travelling over a wire.
//
// WHY THIS DOES NOT BREAK THE LOCALITY THESIS: birth and survive are
// broadcast constants, in exactly the sense clk, rst_n and load already
// are. They carry no information about any other cell. A cell still reads
// nothing but its own state and eight neighbor wires; there is no shared
// accumulator, no global reduction, no sequential scan. Every cell still
// resolves its next state in the same clock edge as every other cell.
//
// ca_cell.v is deliberately left untouched. It passed exhaustive 512-input
// verification and is still the fabric you build when you want the
// smallest possible cell and only ever need Life.
//
// Cost, structurally: the two `count ==` comparators are replaced by a
// 2-to-1 mux over 9 bits (pick the mask with `state`) feeding a 9-to-1 mux
// (index it with `count`). The popcount adder tree, which dominates the
// cell, is unchanged. Measured LUT4 numbers need a yosys run; see
// hardware/synth/README.md.

module ca_cell_rule (
    input  wire       clk,
    input  wire       rst_n,      // active-low async reset
    input  wire [7:0] neighbors,  // 8 neighbor states, one bit each
    input  wire       load,       // when high, take seed_bit instead of the rule
    input  wire       seed_bit,   // initial value to load
    input  wire [8:0] birth,      // birth[k]: dead cell, k neighbors -> alive
    input  wire [8:0] survive,    // survive[k]: live cell, k neighbors -> alive
    output reg        state       // this cell's current (registered) state
);

    // --- neighbor count: identical to ca_cell.v. 8 separate wires in,
    // one number 0-8 out, computed inside the cell because that is what
    // the physical wiring actually is.
    wire [3:0] count;
    assign count = neighbors[0] + neighbors[1] + neighbors[2] + neighbors[3] +
                   neighbors[4] + neighbors[5] + neighbors[6] + neighbors[7];

    // --- the rule, as a lookup instead of a comparison.
    // Pick the row of the truth table with `state`, then index that row
    // with `count`. Two lines here replace the hardwired B3/S23 in
    // ca_cell.v, and this is the exact structure golden_rule.py's
    // update_masked() mirrors in Python.
    //
    // `count` is 4 bits wide but can only reach 8, so the index never
    // leaves the 9-bit mask. That bound is a property of having exactly
    // 8 neighbor inputs, not an assumption.
    wire [8:0] active_mask = state ? survive : birth;
    wire       rule_next   = active_mask[count];

    // load mux: seeding takes priority over the rule when `load` is high.
    // Same path the generation pacer reuses to hold the grid still.
    wire next_state = load ? seed_bit : rule_next;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            state <= 1'b0;
        else
            state <= next_state;
    end

endmodule
