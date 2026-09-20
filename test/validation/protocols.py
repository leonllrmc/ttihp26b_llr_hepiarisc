"""Pin-level peers. Their decoded events double as protocol scoreboards."""
from collections import deque
from cocotb.utils import get_sim_time
from common import value


class SharedSPI:
    """Mode-0 READ-03 flash plus user SPI peer sharing MISO and MOSI.

    No internal RTL state is used to decide the flash response. Chip select,
    clocks and serialized address bytes are decoded from package pins only.
    """
    def __init__(self,dut,trace,image,read_bytes=()):
        self.dut,self.trace,self.image=dut,trace,image
        self.responses=deque(read_bytes)
        self.user_rx=[];self.user_tx=[];self.fetches=[];self.frames=[]
        self.previous_cs=1;self.previous_sck=0;self.previous_user=0
        self.bits=0;self.rx=0;self.octets=[];self.address=0;self.reading=False
        self.user_bits=0;self.user_byte=0;self.response=self.responses.popleft() if self.responses else 0xff

    def drive_miso(self,bit):
        # Preserve external IRQ and GPI driven by other test actors.
        self.dut.ui_in.value=(value(self.dut.ui_in)&0xfe)|int(bit)

    def sample(self):
        d=self.dut;pins=value(d.uo_out)
        cs=(pins>>2)&1;sck=pins&1;mosi=(pins>>1)&1;user=(pins>>3)&1
        if not value(d.rst_n):
            self.previous_cs=cs;self.previous_sck=sck;self.previous_user=user
            self.bits=self.rx=self.user_bits=self.user_byte=0;self.octets=[];self.reading=False
            self.drive_miso(1);return
        if cs!=self.previous_cs:
            self.trace.event("spi_cs",device="flash",active=not cs,clock=sck)
            if not cs:
                assert sck==0,"Flash CS asserted with SCLK high"
                self.bits=self.rx=0;self.octets=[];self.address=0;self.reading=False
            else:
                assert self.bits==0,f"Flash CS ended mid-byte ({self.bits} bits)"
                assert len(self.octets)==6,f"Instruction fetch requires command+3 address+2 data bytes, saw {self.octets}"
                self.frames.append(list(self.octets))
                self.drive_miso((self.response>>7)&1)
        if not cs and sck and not self.previous_sck:
            self.rx=(self.rx<<1)|mosi;self.bits+=1
            if self.bits==8:
                byte=self.rx;index=len(self.octets);self.octets.append(byte)
                self.trace.event("spi_byte",device="flash",direction="mosi",index=index,data=byte)
                if index==0:assert byte==3,f"Unexpected flash command 0x{byte:02x}"
                elif 1<=index<=3:
                    self.address=(self.address<<8)|byte
                    if index==3:
                        assert self.address<len(self.image),f"Flash address out of image: 0x{self.address:06x}"
                        assert self.address%2==0,"Instruction fetch at odd byte address"
                        self.fetches.append(self.address);self.reading=True
                        self.trace.event("spi_address",address=self.address,bank=self.address//512,pc=(self.address%512)//2)
                else:
                    assert byte==0xff,f"Fetch dummy byte must be FF, got {byte:02x}"
                    self.trace.event("spi_byte",device="flash",direction="miso",address=self.address,data=self.image[self.address])
                    self.address+=1
                self.bits=self.rx=0
        if not cs and not sck and self.previous_sck:
            bit=((self.image[self.address]>>(7-self.bits))&1) if self.reading and self.address<len(self.image) else 1
            self.drive_miso(bit)
        if user and not self.previous_user:
            # SCLK is intentionally shared: the flash sees the clock too,
            # but must be deselected for every user transfer.
            assert cs==1,"User SPI clocks occurred while flash CS was active"
            assert sck==1,"User SPI clock does not follow the shared clock"
            self.user_byte=(self.user_byte<<1)|mosi;self.user_bits+=1
            if self.user_bits==8:
                self.user_rx.append(self.user_byte);self.user_tx.append(self.response)
                self.trace.event("spi_byte",device="user",mosi=self.user_byte,miso=self.response)
                self.user_bits=self.user_byte=0
                self.response=self.responses.popleft() if self.responses else 0xff
        if cs and not user:
            self.drive_miso((self.response>>(7-self.user_bits))&1)
        if user and not cs:raise AssertionError("User SPI active during flash fetch")
        self.previous_cs,self.previous_sck,self.previous_user=cs,sck,user


class I2CPeer:
    """Open-drain addressed slave with ACK/NAK, RX/TX and clock stretching.

    Inputs/outputs are resolved in the HDL wrapper: slave drive=1 pulls low.
    SDA changes are driven at falling SCL edges, never sampled-edge races.
    """
    def __init__(self,dut,trace,address=0x50,read_bytes=(),nack_indices=(),stretch=0,quarter_cycles=None,clock_period_ns=20):
        self.dut,self.trace,self.address=dut,trace,address
        self.read_bytes=list(read_bytes);self.nack_indices=set(nack_indices)
        self.stretch=stretch;self.stretch_remaining=0;self.force_scl_low=False
        self.previous_scl=self.previous_sda=1
        self.active=False;self.read_mode=False;self.expect_address=True
        self.bits=0;self.rx=0;self.ack_this=False;self.switch_read=False
        self.received=[];self.transmitted=[];self.acks=[];self.starts=0;self.stops=0
        self.tx_index=0;self.tx_byte=self.read_bytes[0] if self.read_bytes else 0xff
        self.stretch_events=0;self.sample_times=[];self.byte_periods=[]
        self.quarter_cycles=quarter_cycles
        self.clock_period_ns=clock_period_ns
        self.sda_low=0
        dut.slave_scl_low.value=0;dut.slave_sda_low.value=0

    def master_scl_low(self):
        return value(self.dut.scl_oe) if hasattr(self.dut,"scl_oe") else value(self.dut.uio_oe)&1

    def sample(self):
        d=self.dut
        if not value(d.rst_n):
            self.active=False;self.bits=self.rx=0;self.read_mode=False;self.expect_address=True
            self.sda_low=0;self.stretch_remaining=0;self.sample_times=[]
            d.slave_sda_low.value=0;d.slave_scl_low.value=int(self.force_scl_low)
            self.previous_scl=0 if self.force_scl_low else 1;self.previous_sda=1
            return
        scl,sda=value(d.scl),value(d.sda)
        if hasattr(d,"uio_out"):
            assert value(d.uio_out)&value(d.uio_oe)&3==0,"I2C attempted to drive a high level"
        start=scl and self.previous_scl and self.previous_sda and not sda
        stop=scl and self.previous_scl and not self.previous_sda and sda
        if start:
            self.trace.event("i2c_start",repeated=self.active)
            self.starts+=1;self.active=True;self.read_mode=False;self.expect_address=True
            self.bits=self.rx=0;self.sda_low=0;self.switch_read=False;self.sample_times=[]
        elif stop:
            self.trace.event("i2c_stop")
            self.stops+=1;self.active=False;self.bits=self.rx=0;self.sda_low=0
        elif self.active and scl and not self.previous_scl:
            self.bits+=1
            self.sample_times.append(float(get_sim_time(unit="ns")))
            self.trace.event("i2c_bit",bit=self.bits,sda=sda,direction="slave" if self.read_mode else "master")
            if self.bits<=8:
                self.rx=(self.rx<<1)|sda
                if self.bits==8:
                    if self.read_mode:
                        self.transmitted.append(self.rx)
                        self.trace.event("i2c_byte",direction="slave",data=self.rx)
                    else:
                        index=len(self.received);self.received.append(self.rx)
                        self.ack_this=index not in self.nack_indices
                        if self.expect_address:
                            self.ack_this &= self.rx>>1==self.address
                            self.switch_read=bool(self.rx&1) and self.ack_this
                        self.trace.event("i2c_byte",direction="master",data=self.rx,address=self.expect_address)
            elif self.bits==9:
                self.acks.append(("master" if self.read_mode else "slave",sda))
                self.trace.event("i2c_ack",by=self.acks[-1][0],ack=sda==0)
                periods=[b-a for a,b in zip(self.sample_times,self.sample_times[1:])]
                self.byte_periods.append(periods)
                self.trace.event("i2c_byte_timing",periods_ns=periods,stretched=bool(self.stretch))
                if self.quarter_cycles and not self.stretch:
                    assert all(abs(t-4*self.clock_period_ns*self.quarter_cycles)<0.01 for t in periods),f"I2C bit period: {periods}"
            else:raise AssertionError("I2C byte has more than nine sampled bits")
        if self.active and not scl and self.previous_scl:
            if self.quarter_cycles and not self.stretch and self.bits and self.sample_times:
                high=float(get_sim_time(unit="ns"))-self.sample_times[-1]
                assert abs(high-2*self.clock_period_ns*self.quarter_cycles)<0.01,f"I2C high width {high} ns"
            if self.bits==8:
                self.sda_low=0 if self.read_mode else int(self.ack_this)
            elif self.bits==9:
                if self.read_mode:self.tx_index+=1
                elif self.expect_address:
                    self.read_mode=self.switch_read;self.expect_address=False
                self.bits=self.rx=0;self.sample_times=[]
                self.tx_byte=self.read_bytes[self.tx_index] if self.tx_index<len(self.read_bytes) else 0xff
                self.sda_low=int(not ((self.tx_byte>>7)&1)) if self.read_mode else 0
            elif self.read_mode:
                self.sda_low=int(not ((self.tx_byte>>(7-self.bits))&1))
            if self.stretch and self.master_scl_low():self.stretch_remaining=self.stretch
        was_stretch=value(d.slave_scl_low)
        if self.stretch_remaining and not self.master_scl_low():
            self.stretch_remaining-=1
            if not self.stretch_remaining:
                self.stretch_events+=1;self.trace.event("i2c_stretch_end")
        pull_scl=int(self.force_scl_low or self.stretch_remaining>0)
        if pull_scl and not was_stretch:self.trace.event("i2c_stretch_start")
        d.slave_sda_low.value=self.sda_low
        d.slave_scl_low.value=pull_scl
        self.previous_scl,self.previous_sda=scl,sda
