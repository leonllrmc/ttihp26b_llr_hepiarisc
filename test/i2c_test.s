#bank rstvec
Reset:
; do not change
bra $10

#bank irqvec
Irq_Vector:
bir ; always add BIR at end
nop ; always put nop after to be sure nothing bad happends

#bank programstart
Start:


ldconst R0, 0x90
ldconst R1, 0xa0
st R1, (R0+0) ; start

w0:
ld R2, (R0 + 5)
and r2, r2, r2
bzc w0

st R1, (R0+1) ; write addr

w1:
ld R2, (R0 + 5)
and r2, r2, r2
bzc w1

ldconst R1, 0x38
st R1, (R0+1); write data
w2:
ld R2, (R0 + 5)
and r2, r2, r2
bzc w2


st R1, (R0+4) ; stop

w6:
ld R2, (R0 + 5)
and r2, r2, r2
bzc w6

st R1, (R0+0) ; start

w7:
ld R2, (R0 + 5)
and r2, r2, r2
bzc w7

ldconst R1, 0xa1
st R1, (R0+1) ; write

w8:
ld R2, (R0 + 5)
and r2, r2, r2
bzc w8

st R1, (R0+3) ; request read
w3:
ld R2, (R0 + 5)
and r2, r2, r2
bzc w3

ld R1, (R0+6) ; read data

st R1, (R0+4) ; stop

infloop:
bra infloop