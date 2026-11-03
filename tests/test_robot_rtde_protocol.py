"""Run the pinned official client against a loopback-only RTDE protocol peer."""
import socket
import struct
import time
from threading import Thread
import unittest
from unittest.mock import patch
from src.robot.ur5.rtde_channel import RTDEChannel,BASE_FIELDS


class ProtocolTests(unittest.TestCase):
    def test_official_client_negotiates_fields_reads_and_writes(self):
        import rtde.rtde
        real=rtde.rtde.RTDE
        server=socket.socket();server.bind(('127.0.0.1',0));server.listen();server.settimeout(3)
        received=[];errors=[]
        def exact(sock,size):
            result=b''
            while len(result)<size:
                part=sock.recv(size-len(result))
                if not part:raise EOFError()
                result+=part
            return result
        def packet(sock,cmd,payload):sock.sendall(struct.pack('>HB',len(payload)+3,ord(cmd))+payload)
        def peer():
            try:
                with server.accept()[0] as sock:
                    sock.settimeout(3);outputs=[]
                    while True:
                        size,command=struct.unpack('>HB',exact(sock,3));payload=exact(sock,size-3);cmd=chr(command)
                        if cmd=='V':packet(sock,'V',b'\x01')
                        elif cmd=='v':packet(sock,'v',struct.pack('>IIII',3,15,8,0))
                        elif cmd=='O':
                            outputs=payload[8:].decode().split(',')
                            types={**BASE_FIELDS,'tcp_offset':'VECTOR6D'}
                            packet(sock,'O',b'\x01'+','.join(types[n] for n in outputs).encode())
                        elif cmd=='I':packet(sock,'I',b'\x02INT32,INT32,INT32,UINT8,UINT8,UINT32,DOUBLE')
                        elif cmd=='S':
                            packet(sock,'S',b'\x01');data=b'\x01'
                            for field in outputs:
                                if field in {'actual_q','actual_qd','actual_TCP_pose','actual_TCP_speed','tcp_offset'}:data+=struct.pack('>6d',*([0.]*6))
                                elif field in {'timestamp','speed_scaling','target_speed_fraction'}:data+=struct.pack('>d',1.)
                                elif field=='actual_digital_output_bits':data+=struct.pack('>Q',0)
                                elif field=='runtime_state':data+=struct.pack('>I',1)
                                else:data+=struct.pack('>i',7 if field=='robot_mode' else 1 if field=='safety_mode' else 0)
                            time.sleep(.05)
                            packet(sock,'U',data)
                        elif cmd=='U':received.append(payload);break
            except Exception as exc:errors.append(exc)
        thread=Thread(target=peer,daemon=True);thread.start()
        channel=RTDEChannel('127.0.0.1')
        try:
            with patch.object(rtde.rtde,'RTDE',side_effect=lambda host,port:real('127.0.0.1',server.getsockname()[1])):
                self.assertEqual(channel.open(control=True),(3,15,8,0))
                sample=channel.receive();self.assertEqual(sample['runtime_state'],1)
                channel.send(heartbeat=42,job=99,stop=True,pin=3,speed=.1)
            thread.join(3);self.assertFalse(thread.is_alive());self.assertFalse(errors,errors)
            recipe,hb,job,stop,mask,value,speedmask,speed=struct.unpack('>BiiiBBId',received[0])
            self.assertEqual((hb,job,stop,mask,value,speedmask),(42,99,1,8,0,1));self.assertAlmostEqual(speed,.1)
        finally:channel.close();server.close()


if __name__=='__main__':unittest.main()
