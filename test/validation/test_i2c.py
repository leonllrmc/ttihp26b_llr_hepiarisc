import cocotb
from common import Case,Clocked,value
from protocols import I2CPeer


class I2C(Clocked):
    def __init__(self,dut,trace,**peer_options):
        super().__init__(dut,trace)
        for name in ("start","stop","send_byte","recv_byte","set_ack","set_nak"):getattr(dut,name).value=0
        dut.din.value=0
        self.peer=I2CPeer(dut,trace,quarter_cycles=4,**peer_options);self.peers=[self.peer]

    async def command(self,cmd,data=0):
        assert not value(self.dut.busy),"Test issued a command before idle"
        self.dut.din.value=data;getattr(self.dut,cmd).value=1
        await self.tick();getattr(self.dut,cmd).value=0
        if cmd in ("set_ack","set_nak"):
            await self.tick();return
        completion="start_done" if cmd=="start" else "stop_done" if cmd=="stop" else "byte_done"
        await self.until(lambda:value(getattr(self.dut,completion)),5000,f"I2C {cmd} completion")
        assert value(self.dut.busy)==0
        await self.tick()
        assert value(getattr(self.dut,completion))==0,"Completion is not a one-cycle pulse"


@cocotb.test(timeout_time=5,timeout_unit="ms")
async def i2c_transmit_all_bytes_and_ack(dut):
    with Case(dut,"i2c_transmit_all_bytes_and_ack") as c:
        bus=I2C(dut,c.trace);await bus.reset();await bus.command("start");await bus.command("send_byte",0xa0)
        for byte in range(256):
            await bus.command("send_byte",byte)
            assert value(dut.ack_bit)==0
        await bus.command("stop")
        assert bus.peer.received==[0xa0]+list(range(256))
        assert bus.peer.starts==1 and bus.peer.stops==1
        assert value(dut.scl)==value(dut.sda)==1


@cocotb.test(timeout_time=1,timeout_unit="ms")
async def i2c_nack_and_repeated_start(dut):
    with Case(dut,"i2c_nack_and_repeated_start") as c:
        bus=I2C(dut,c.trace,nack_indices={1},read_bytes=[0x96,0x5a]);await bus.reset()
        await bus.command("start");await bus.command("send_byte",0xa0)
        assert value(dut.ack_bit)==0
        await bus.command("send_byte",0x55);assert value(dut.ack_bit)==1
        await bus.command("start");await bus.command("send_byte",0xa1)
        await bus.command("set_ack");await bus.command("recv_byte");assert value(dut.dout)==0x96
        await bus.command("set_nak");await bus.command("recv_byte");assert value(dut.dout)==0x5a
        await bus.command("stop")
        assert bus.peer.starts==2 and bus.peer.stops==1
        assert bus.peer.transmitted==[0x96,0x5a]
        assert [v for who,v in bus.peer.acks if who=="master"]==[0,1]


@cocotb.test(timeout_time=5,timeout_unit="ms")
async def i2c_receive_all_bytes(dut):
    with Case(dut,"i2c_receive_all_bytes") as c:
        bus=I2C(dut,c.trace,read_bytes=range(256));await bus.reset()
        await bus.command("start");await bus.command("send_byte",0xa1)
        for byte in range(256):
            if byte==255:await bus.command("set_nak")
            await bus.command("recv_byte");assert value(dut.dout)==byte
        await bus.command("stop")
        assert bus.peer.transmitted==list(range(256))
        assert [v for who,v in bus.peer.acks if who=="master"]==[0]*255+[1]


@cocotb.test(timeout_time=1,timeout_unit="ms")
async def i2c_clock_stretching_start_data_and_stop(dut):
    with Case(dut,"i2c_clock_stretching_start_data_and_stop") as c:
        bus=I2C(dut,c.trace,read_bytes=[0xa5],stretch=19);await bus.reset()
        bus.peer.force_scl_low=True;await bus.tick(2)
        dut.start.value=1;await bus.tick();dut.start.value=0
        await bus.tick(100)
        assert value(dut.busy)==1 and value(dut.start_done)==0
        bus.peer.force_scl_low=False
        await bus.until(lambda:value(dut.start_done),500,"stretched START")
        await bus.tick()
        await bus.command("send_byte",0xa1);await bus.command("set_nak")
        await bus.command("recv_byte");assert value(dut.dout)==0xa5
        await bus.command("stop")
        assert bus.peer.stretch_events>=18
        assert bus.peer.stops==1 and value(dut.scl)==value(dut.sda)==1


@cocotb.test(timeout_time=1,timeout_unit="ms")
async def i2c_busy_command_ignored_and_ack_preset_priority(dut):
    with Case(dut,"i2c_busy_command_ignored_and_ack_preset_priority") as c:
        bus=I2C(dut,c.trace,read_bytes=[0x3c]);await bus.reset()
        await bus.command("start");await bus.command("send_byte",0xa1)
        dut.recv_byte.value=1;await bus.tick();dut.recv_byte.value=0
        await bus.tick(20)
        dut.stop.value=1;dut.send_byte.value=1;dut.din.value=0x99
        dut.set_ack.value=1;dut.set_nak.value=1
        await bus.tick()
        dut.stop.value=0;dut.send_byte.value=0;dut.set_ack.value=0;dut.set_nak.value=0
        await bus.until(lambda:value(dut.byte_done),500,"RX after ignored commands")
        await bus.tick()
        assert value(dut.dout)==0x3c and bus.peer.stops==0
        assert bus.peer.acks[-1]==("master",0),"set_ack must win simultaneous ACK/NAK preset"
        await bus.command("stop")


@cocotb.test(timeout_time=5,timeout_unit="ms")
async def i2c_reset_during_start_byte_stretch_and_stop(dut):
    with Case(dut,"i2c_reset_during_start_byte_stretch_and_stop") as c:
        for operation in ("start","send_byte","recv_byte","stop"):
            for delay in (0,1,4,8,12,31,63,100):
                bus=I2C(dut,c.trace,read_bytes=[0xa5],stretch=7);await bus.reset()
                if operation!="start":
                    await bus.command("start")
                    if operation=="recv_byte":await bus.command("send_byte",0xa1)
                dut.din.value=0x96;getattr(dut,operation).value=1
                await bus.tick();getattr(dut,operation).value=0;await bus.tick(delay)
                await bus.reset()
                assert value(dut.busy)==0
                assert value(dut.byte_done)==value(dut.start_done)==value(dut.stop_done)==0
                assert value(dut.scl_oe)==value(dut.sda_oe)==0
                await bus.command("start");await bus.command("send_byte",0xa0);await bus.command("stop")
