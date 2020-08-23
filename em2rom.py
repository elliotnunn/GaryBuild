#!/usr/bin/env python

import struct


# 68k registers are not numbered consecutively in PowerPC register space.
# Typically: D0-D7 <-> r8-r15, A0-A6 <-> d17-r22, A7 <-> r1.
# When we increment these fields in a PowerPC instruction, we must account for this,
def increment_insn(insn, increment, times, regmap):
    # Do the complicated operation, leaving the increment var usable for later
    for shift in (21, 16, 11):
        if shift == 11:
            if (insn >> 27) & 0x1f == 10: continue # rlwimi/rlwinm
            if (insn >> 26) & 0x3f == 31: # X-form instruction
                if (insn >> 1) & 0x3ff in (184, 248, 696, 760, 824, 952): continue

        if (increment >> shift) & 0x1f == 1:
            increment &= ~(0x1f << shift) # remove

            field = (insn >> shift) & 0x1f
            newfield = regmap[regmap.index(field) + times]

            insn &= ~(0x1f << shift) # remove
            insn |= (newfield & 0x1f) << shift

    # Do the simple operation
    insn += increment * times

    return insn


# Prevent overflow of the PPC branch offset field into the other fields.
# Hopefully this will allow the opcode table and emulator code to be reversed in order.
def relocate_insn(insn, delta):
    if (insn >> 26) & 0x3f == 18: # 'b'
        offset_bits = 26
    elif (insn >> 26) & 0x3f == 16: # 'bc'
        offset_bits = 16
    else:
        offset_bits = 16

    offset_mask = (1 << offset_bits) - 1
    return (insn & ~offset_mask) | ((insn - delta) & offset_mask)


# Create a 512k emulation dispatch table (2 PPC instructions for each 16-bit 68k opcode)
def make_disptable(init, regmap, loc_delta):
    table = bytearray(0x10000 * 8)
    source_strings = [[] for _ in range (0x10000)]
    ofs = 0

    while 1:
        old_address = ofs # Save this because we will relocate insn1/2, and must adjust them

        insn1, insn2, flags, opcode = struct.unpack_from('>LLHH', init, ofs); ofs += 12

        if flags & 0x8000: break

        if flags & 4:
            l1count, l1opinc, l1i1inc, l1i2inc = struct.unpack_from('>HHLL', init, ofs); ofs += 12
        else:
            l1count = l1opinc = l1i1inc = l1i2inc = 0

        if flags & 8:
            l2count, l2opinc, l2i1inc, l2i2inc = struct.unpack_from('>HHLL', init, ofs); ofs += 12
        else:
            l2count = l2opinc = l2i1inc = l2i2inc = 0

        for l1 in range(l1count + 1):
            for l2 in range(l2count + 1):
                this_opcode = opcode + (l1opinc * l1) + (l2opinc * l2)
                new_address = this_opcode * 8

                this_insn1 = insn1
                this_insn1 = increment_insn(this_insn1, l1i1inc, l1, regmap)
                this_insn1 = increment_insn(this_insn1, l2i1inc, l2, regmap)
                if flags & 1:
                    this_insn1 = relocate_insn(this_insn1, loc_delta + new_address - old_address)
                this_insn1 &= 0xffffffff

                this_insn2 = insn2
                this_insn2 = increment_insn(this_insn2, l1i2inc, l1, regmap)
                this_insn2 = increment_insn(this_insn2, l2i2inc, l2, regmap)
                if flags & 2:
                    this_insn2 = relocate_insn(this_insn2, loc_delta + new_address - old_address)
                this_insn2 &= 0xffffffff

                struct.pack_into('>LL', table, new_address, this_insn1, this_insn2)

                source_strings[this_opcode].append('%04X = %08X %08X, from %04X, iteration %d of 0..%d, iteration %d of 0..%d' %
                    (this_opcode, insn1, insn2, opcode, l1, l1count, l2, l2count))

    return table


if __name__ == '__main__':
    import argparse
    import ast

    parser = argparse.ArgumentParser(description='Insert a 68020 emulator binary into a Power Mac ROM image.')
    parser.add_argument('rom', help='ROM')
    parser.add_argument('emulator', help='Emulator binary (not an ELF)')
    parser.add_argument('--output', '-o', metavar='rom', default=None, help='Output ROM (otherwise will overwrite in-place)')
    args = parser.parse_args()
    if args.output is None: args.output = args.rom

    built = open(args.emulator, 'rb').read()

    built_code_size, built_disptable_base = struct.unpack_from('>LL', built, len(built) - 8)

    built_code = built[:built_code_size]
    built_disptable = built[built_disptable_base:]
    built_regmap = built[-56:-40] # mapping of 68k to PPC registers, needed for the disptable

    rom = open(args.rom, 'rb').read(); rom = bytearray(rom)
    rom_configinfo_base = 0x300000 + struct.unpack_from('>l', rom, 0x300080)[0]
    rom_code_base, rom_code_size, rom_disptable_base, rom_disptable_size = [rom_configinfo_base + x for x in struct.unpack_from('>llll', rom, rom_configinfo_base + 0x54)]

    linked_disptable = make_disptable(built_disptable, built_regmap, rom_disptable_base - rom_code_base - built_disptable_base)

    # Okay, how about a cute little game of "erase the emulator"...

    # rom[rom_code_base:rom_code_base+rom_code_size] = b'\0' * rom_code_size # cut off any nasties trailing the emulator

    rom[rom_code_base:rom_code_base+len(built_code)] = built_code
    rom[rom_disptable_base:rom_disptable_base+len(linked_disptable)] = linked_disptable

    open(args.output, 'wb').write(rom)
