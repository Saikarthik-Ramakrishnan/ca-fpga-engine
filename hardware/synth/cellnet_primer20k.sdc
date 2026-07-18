// cellnet_primer20k.sdc
//
// Timing constraint for the Gowin EDA (vendor) flow. The open flow does
// not need this file: build_bitstream.sh passes --freq 27 to nextpnr,
// which both constrains and verifies the same 27 MHz clock.
//
// 27 MHz dock oscillator on pin H11 -> 37.037 ns period.

create_clock -name clk -period 37.037 -waveform {0 18.518} [get_ports {clk}]
