; Flash-ready example: GPIO write/readback, user SPI exchange and I2C write.
; Compile with: python assembler.py examples/peripheral_smoke.s -o smoke.bin
.bank 0
bra main
.org 1
bir
.org 16
main:
ldconst r0, 0x80
ldconst r1, 0x0a
st r1, (r0)
ld r2, (r0)

ldconst r0, 0x98
ldconst r1, 0xa5
st r1, (r0)
ld r3, (r0+1)

ldconst r0, 0x90
st r1, (r0)
wait_start:
ld r7, (r0+5)
and r7,r7,r7
bne wait_start
ldconst r1, 0xa0
st r1, (r0+1)
wait_address:
ld r7, (r0+5)
and r7,r7,r7
bne wait_address
ld r4, (r0+7)
ldconst r1, 0x55
st r1, (r0+1)
wait_data:
ld r7, (r0+5)
and r7,r7,r7
bne wait_data
st r1, (r0+4)
wait_stop:
ld r7, (r0+5)
and r7,r7,r7
bne wait_stop
done:bra done
