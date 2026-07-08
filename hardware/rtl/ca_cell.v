// ca_cell.v
//
// One cell of the cellular automaton, meant to be instantiated once per
// cell across the grid in Phase 3. This is the hardware twin of
// `update(alive, neighbors)` in golden_rule.py / cellnet_console.html --
// same rule (Conway's Life, B3/S23), same truth table, just expressed as
// gates instead of an if-statement.
//
// Design choice worth being explicit about: neighbors arrive as 8
// separate 1-bit wires, not a pre-summed count. That's deliberate --
// in the real grid (Phase 3), each of those 8 wires is a direct
// connection to one neighboring cell's `state` output. Summing them
// into a count happens *inside* this module, in hardware, because that's
// what the real wiring will actually look like: this cell doesn't know
// "3 neighbors are alive", it knows 8 individual wire states and computes
// the count itself. Keeping that boundary honest here makes Phase 3
// (wiring N^2 of these together) a mechanical copy-paste, not a redesign.
//
// The `load`/`seed_bit` pair lets an initial pattern be written into the
// cell's register: when `load` is high on a clock edge, the cell takes
// `seed_bit` instead of the computed rule result. That's how the grid gets
// seeded with a glider, a random soup, etc. before free-running.

module ca_cell (
    input  wire       clk,
    input  wire       rst_n,      // active-low async reset
    input  wire [7:0] neighbors,  // 8 neighbor states, one bit each
    input  wire       load,       // when high, take seed_bit instead of the rule
    input  wire       seed_bit,   // initial value to load
    output reg        state       // this cell's current (registered) state
);

    // --- neighbor count: an 8-input popcount, done with plain addition.
    // Synthesizes to an adder tree; this is the "read 8 wires, get a
    // number 0-8" step that has no equivalent in the naive software loop
    // (there, you'd literally loop and increment a counter one at a time).
    wire [3:0] count;
    assign count = neighbors[0] + neighbors[1] + neighbors[2] + neighbors[3] +
                   neighbors[4] + neighbors[5] + neighbors[6] + neighbors[7];

    // --- the rule itself: B3/S23, i.e. golden_rule.py's
    //   alive -> stays alive if count is 2 or 3
    //   dead  -> becomes alive if count is exactly 3
    // Written as a truth table over `count` rather than a chain of
    // if/else specifically so a different ruleset (HighLife, Day & Night,
    // Seeds, Maze -- same ones in the console's rule bank) is a one-line
    // change to the two comparisons below, not a redesign.
    wire rule_next = state ? (count == 4'd2 || count == 4'd3)
                           : (count == 4'd3);

    // load mux: seeding takes priority over the rule when `load` is high.
    wire next_state = load ? seed_bit : rule_next;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            state <= 1'b0;
        else
            state <= next_state;
    end

endmodule
