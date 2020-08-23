all: Emulate68020.bin NanoKernel.bin HardwareInit.bin

%.c1: %.c *.c *.s
	./wrapcpp $< > $@

%.c2: %.c1
	./prevasm <$< >$@

%.elf: %.c2 vasm/vasmppc_std
	vasm/vasmppc_std -Felf -m601 -o $@ $<

%.bin: %.elf
	./dumpelf $< $@

vasm/:
	curl -O http://sun.hasenbraten.de/vasm/release/vasm.tar.gz
	tar xf vasm.tar.gz

vasm/vasmppc_std: vasm/
	make -C vasm CPU=ppc SYNTAX=std

clean:
	rm -rf *.c1 *.c2 *.elf *.bin # This rule does not delete vasm.
