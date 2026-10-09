import struct
import socket
import unittest

from gamers_ping.gamedetect import UdpSniffer, parse_ipv4_udp, is_public
from gamers_ping.monitor import compute_stats
from gamers_ping.netinfo import parse_default_gateway


def udp_packet(src, dst, sport, dport, payload=b"x" * 20):
    udp = struct.pack("!HHHH", sport, dport, 8 + len(payload), 0) + payload
    ip = struct.pack("!BBHHHBBH4s4s", 0x45, 0, 20 + len(udp), 0, 0, 64, 17, 0,
                     socket.inet_aton(src), socket.inet_aton(dst))
    return ip + udp


class Core(unittest.TestCase):
    def test_stats(self):
        s = compute_stats([10, 20, None, 30])
        self.assertEqual(s["avg"], 20)
        self.assertEqual(s["loss"], 25.0)
        self.assertEqual(s["jitter"], 10)

    def test_gateway(self):
        txt = "  0.0.0.0  0.0.0.0  10.0.0.1  10.0.0.5  300\n  0.0.0.0  0.0.0.0  192.168.1.1  192.168.1.5  25\n"
        self.assertEqual(parse_default_gateway(txt), "192.168.1.1")

    def test_sniffer_inbound_and_outbound(self):
        s = UdpSniffer()
        s.ports = frozenset({3074})
        s.feed(udp_packet("34.1.2.3", "192.168.1.5", 3074, 3074))
        s.feed(udp_packet("192.168.1.5", "35.9.9.9", 3074, 3074))
        s.feed(udp_packet("34.1.2.3", "192.168.1.5", 1, 9999))  # unrelated port
        s.feed(udp_packet("192.168.1.9", "192.168.1.5", 1, 3074))  # private peer
        self.assertEqual(set(s.scores), {"34.1.2.3", "35.9.9.9"})

    def test_parse_rejects_tcp(self):
        pkt = bytearray(udp_packet("1.1.1.1", "2.2.2.2", 1, 2))
        pkt[9] = 6
        self.assertIsNone(parse_ipv4_udp(bytes(pkt)))

    def test_public(self):
        self.assertTrue(is_public("8.8.8.8"))
        self.assertFalse(is_public("10.0.0.1"))


if __name__ == "__main__":
    unittest.main()
