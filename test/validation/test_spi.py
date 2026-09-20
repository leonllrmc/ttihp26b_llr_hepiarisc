import os
import cocotb
from common import Case,Clocked,value


class SPI(Clocked):
    def __init__(self,dut,trace):
        super().__init__(dut,trace)
        dut.send.value=0;dut.din.value=0;dut.miso.value=0
        self.divider=int(os.getenv("HEPIA_SPI_DIV","4"))

    async def transfer(self,tx,rx,inject_busy=False):
        assert not value(self.dut.busy) and not value(self.dut.sclk)
        self.dut.din.value=tx;self.dut.send.value=1;self.dut.miso.value=(rx>>7)&1
        await self.tick();self.dut.send.value=0
        assert value(self.dut.busy)==1 and value(self.dut.cs_n)==0
        last=0;bits=[];rising=[];done_count=0
        for cycle in range(20*self.divider+12):
            if inject_busy and cycle==3*self.divider:
                self.dut.send.value=1;self.dut.din.value=tx^255
            else:self.dut.send.value=0
            await self.tick()
            sck=value(self.dut.sclk)
            if sck and not last:
                bits.append(value(self.dut.mosi));rising.append(self.cycles)
                self.trace.event("spi_bit",index=len(bits),mosi=bits[-1],miso=value(self.dut.miso))
            if not sck and last and len(bits)<8:self.dut.miso.value=(rx>>(7-len(bits)))&1
            if value(self.dut.done):
                done_count+=1
                assert len(bits)==8 and sck and not last,"done is not aligned with the final sampling edge"
                assert value(self.dut.dout)==rx,f"RX {value(self.dut.dout):02x} != {rx:02x}"
                assert value(self.dut.busy)==0
            last=sck
            if value(self.dut.cs_n):break
        assert len(bits)==8 and done_count==1
        decoded=sum(bit<<(7-i) for i,bit in enumerate(bits))
        assert decoded==tx,f"TX {decoded:02x} != {tx:02x}"
        assert all(b-a==2*self.divider for a,b in zip(rising,rising[1:])),rising
        assert value(self.dut.sclk)==0 and value(self.dut.busy)==0 and value(self.dut.cs_n)==1
        await self.tick();assert value(self.dut.done)==0
        self.trace.event("spi_byte",mosi=decoded,miso=rx,half_period_cycles=self.divider)


@cocotb.test(timeout_time=5,timeout_unit="ms")
async def spi_all_bytes_full_duplex(dut):
    with Case(dut,"spi_all_bytes_full_duplex") as c:
        spi=SPI(dut,c.trace);await spi.reset()
        for tx in range(256):await spi.transfer(tx,((tx*73)^0xa5)&255)


@cocotb.test(timeout_time=1,timeout_unit="ms")
async def spi_send_while_busy_ignored(dut):
    with Case(dut,"spi_send_while_busy_ignored") as c:
        spi=SPI(dut,c.trace);await spi.reset()
        for tx in (0,255,0xa5,0x5a):await spi.transfer(tx,tx^0x96,inject_busy=True)


@cocotb.test(timeout_time=1,timeout_unit="ms")
async def spi_tail_window_back_to_back(dut):
    with Case(dut,"spi_tail_window_back_to_back") as c:
        spi=SPI(dut,c.trace);await spi.reset()
        txs=[0xa5,0x3c,0x81];rxs=[0x96,0x5a,0x7e]
        dut.din.value=txs[0];dut.miso.value=(rxs[0]>>7)&1;dut.send.value=1
        await spi.tick();dut.send.value=0
        frames=[];bits=[];index=0;last=0;dones=0;pending=False
        for _ in range(60*spi.divider+30):
            await spi.tick();sck=value(dut.sclk)
            if pending:dut.send.value=0;pending=False
            if sck and not last:
                bits.append(value(dut.mosi))
                if len(bits)==8:
                    assert value(dut.done)==1 and value(dut.dout)==rxs[index]
                    frames.append(sum(bit<<(7-i) for i,bit in enumerate(bits)));dones+=1
                    c.trace.event("spi_byte",frame=index,mosi=frames[-1],miso=value(dut.dout))
                    if index<2:
                        dut.din.value=txs[index+1];dut.send.value=1;pending=True
            if not sck and last:
                if len(bits)==8:
                    index+=1;bits=[]
                if index<3:dut.miso.value=(rxs[index]>>(7-len(bits)))&1
            last=sck
            if value(dut.cs_n):
                assert index==3,"CS released between queued bytes";break
        assert frames==txs and dones==3


@cocotb.test(timeout_time=1,timeout_unit="ms")
async def spi_reset_each_transfer_phase(dut):
    with Case(dut,"spi_reset_each_transfer_phase") as c:
        spi=SPI(dut,c.trace)
        for delay in range(0,16*spi.divider+1):
            await spi.reset();dut.din.value=0xa5;dut.send.value=1
            await spi.tick();dut.send.value=0;await spi.tick(delay)
            await spi.reset()
            assert value(dut.busy)==0 and value(dut.done)==0 and value(dut.sclk)==0 and value(dut.cs_n)==1
            await spi.transfer(0x5a,0xc3)
