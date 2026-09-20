"""Independent encoding anchors from the repository ISA/customasm examples."""
import unittest
from assembler import assemble, AssemblyError


class AssemblerTests(unittest.TestCase):
    def test_published_encoding_anchors(self):
        # These literals are verification anchors, never hand-authored firmware.
        anchors = {"add r3,r2,r2":0x0690,"sub r2,r2,r1":0x1488,
                   "lsl r4,r3":0x28c0,"and r0,r3,r3":0x50d8,
                   "not r1,r1":0x7240,"ldconst r1,0x42":0x8242,
                   "ld r3,(r2+5)":0xc685,"st r1,(r2+5)":0xd285,
                   "bl r7,12":0xee0c,"br r7":0xfe00,"bir":0xf001,
                   "bnk 15,0x42":0x9f42,"bkr":0xf003,"nop":0x5000}
        for source, expected in anchors.items():
            with self.subTest(source=source): self.assertEqual(assemble(source).at(0,0).word, expected)

    def test_labels_signed_offsets_big_endian_and_bank_placement(self):
        program = assemble(""".equ value, -1
            bra begin
            .org 16
            begin: ldconst r1,value
            bnk 3,worker
            done: bra done
            .bank 3
            .org 254
            worker: st r1,(r2-32)
            bkr
        """)
        self.assertEqual(program.address("worker"),(3,254))
        self.assertEqual(program.at(0,0).args,(16,))
        self.assertEqual(program.image()[0:2],bytes([0xb0,0x10]))
        self.assertEqual(program.image()[32:34],bytes([0x82,0xff]))
        self.assertEqual(program.at(3,254).args,(1,2,-32))
        self.assertEqual(len(program.image()),8192)

    def test_branches_are_relative_to_current_pc_and_wrap(self):
        p=assemble("start: bra tail\n.org 255\ntail: bra start")
        self.assertEqual(p.at(0,0).word & 255,255)
        self.assertEqual(p.at(0,255).word & 255,1)

    def test_reject_invalid_programs(self):
        invalid=["ldconst r8,1","ldconst r0,256","ld r0,(r1+32)","st r0,(r1-33)",
                 "bnk 16,0","brcond 16,0","bra missing",".org 255\nnop\nnop",
                 ".bank -1",".org 256","x:nop\nx:nop","nop\n.org 0\nnop",
                 "bra remote\n.bank 1\nremote:nop","bnk 2,remote\n.bank 1\nremote:nop",
                 "ldconst r0,__import__('os')","add r0,r1",".word 0xffff",".equ broken","bad.label:nop"]
        for source in invalid:
            with self.subTest(source=source), self.assertRaises(AssemblyError): assemble(source)


if __name__ == "__main__": unittest.main()
