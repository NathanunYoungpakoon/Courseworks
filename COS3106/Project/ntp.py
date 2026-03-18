"""
Code Explainations are in the code comments, also in Google Docs file.
To run, type "python ntp.py" command in the current directory.
required python 3.10+ to run.

"""

import socket
import struct
import secrets
import datetime
import time


JAN_1900 = datetime.datetime(1900, 1, 1)
RID_CODES = {
    'LOCL': 'uncalibrated local clock',
    'CESM': 'calibrated Cesium clock',
    'RBDM': 'calibrated Rubidium clock',
    'PPS': 'calibrated quartz clock or other pulse-per-second source',
    'IRIG': 'Inter-Range Instrumentation Group',
    'ACTS': 'NIST telephone modem service',
    'USNO': 'USNO telephone modem service',
    'PTB': 'PTB (Germany) telephone modem service',
    'TDF': 'Allouis (France) Radio 164 kHz',
    'DCF': 'Mainflingen (Germany) Radio 77.5 kHz',
    'MSF': 'Rugby (UK) Radio 60 kHz',
    'WWV': 'Ft. Collins (US) Radio 2.5, 5, 10, 15, 20 MHz',
    'WWVB': 'Boulder (US) Radio 60 kHz',
    'WWVH': 'Kauai Hawaii (US) Radio 2.5, 5, 10, 15 MHz',
    'CHU': 'Ottawa (Canada) Radio 3330, 7335, 14670 kHz',
    'LORC': 'LORAN-C radionavigation system',
    'OMEG': 'OMEGA radionavigation system',
    'GPS': 'Global Positioning Service'
}


def main():
    host = 'pool.ntp.org'

    addr = socket.getaddrinfo(host, 'ntp')[0][-1]  # port: ntp=123

    query = bytearray(48)
    query[0] = 0x23  # version=4, mode=3 (client)
    query[40:48] = secrets.token_bytes(8)

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.settimeout(1)

        local_t1 = time.time()
        assert s.sendto(query, addr) == 48
        data = s.recv(48)
        local_t2 = time.time()
    finally:
        s.close()

    ##################

    x = struct.unpack('!BBBbiIIQQQQ', data)
    leap_ind = x[0] >> 6  # Leap Indicator: 0=no warning, 1=high, 2=low, 3=alarm
    version = (x[0] >> 3) & 0x7  # Version Number: current=4
    mode = x[0] & 0x7            # Mode: 3=client, 4=server

    strat = x[1]    # Stratum
    poll = x[2]     # Poll Interval
    prec = x[3]     # Precision
    r_delay = x[4]  # Root  Delay
    r_disp = x[5]   # Root  Dispersion
    ref_id = x[6]   # Reference Identifier
    ref_t = x[7]    # Reference Timestamp
    orig_t = x[8]   # Originate Timestamp
    recv_t = x[9]   # Receive Timestamp
    tran_t = x[10]  # Transmit Timestamp

    assert leap_ind != 3, 'alarm condition (clock not synchronized)'
    assert version == 4, 'version number does not match the request\'s'
    assert mode == 4, 'expected mode: server'

    assert strat >= 0 and strat <= 15, 'invalid stratum'
    assert orig_t.to_bytes(8, 'big') == query[40:48]

    # an impending leap second to be inserted/deleted in the last minute of the current day.
    if leap_ind == 1:
        print('Leap Indicator: last minute has 61 seconds')
    elif leap_ind == 2:
        print('Leap Indicator: last minute has 59 seconds')

    # the NTP/SNTP version number, currently 4.
    print(f'Version Number: {version}')

    # the stratum.
    print(f'Stratum: {strat} ', end='')
    match strat:
        case 0:
            print('(kiss-o\'-death)')
        case 1:
            print('(primary reference)')
        case _:
            print('(secondary reference)')

    # the maximum interval between successive messages in seconds.
    print(f'Poll Interval: {2**poll} s')

    # the precision of the system clock in seconds.
    print(f'Precision: {2**prec * 1e6:.6f} us')

    # the total roundtrip delay to the primary reference source.
    print(f'Root Delay: {r_delay/2**16:.6f} s')

    # the maximum error due to the clock frequency tolerance.
    print(f'Root Dispersion: {r_disp/2**16 * 1e3:.6f} ms')

    # for stratum 0 (kiss-o'-death message) and 1 (primary server),
    # the value is an ASCII string, For IPv4 secondary servers,
    # the value is the IPv4 address of the synchronization source.
    print(f'Reference Identifier: ', end='')
    rid = ref_id.to_bytes(4, 'big')
    if strat < 2:
        rid = rid.replace(b'\x00', b'').decode()
        print(f'{rid} ({RID_CODES.get(rid)})')
    else:
        rid = '.'.join([str(rid[i]) for i in range(3, -1, -1)])
        print(rid)

    # the time the system clock was last set or corrected.
    print(f'Reference Timestamp: {ref_t/2**32}')

    # the time at which the request arrived at the server.
    print(f'Receive Timestamp: {recv_t/2**32}')

    # the time at which the reply departed the server.
    print(f'Transmit Timestamp: {tran_t/2**32}')

    recv_dt = JAN_1900 + datetime.timedelta(seconds=recv_t/2**32)
    tran_dt = JAN_1900 + datetime.timedelta(seconds=tran_t/2**32)
    print(f"UTC: {tran_dt.strftime('%c')}")

    print(f'Server latency: {(tran_t - recv_t)/2**32 * 1e3:.6f} ms')

    rt_delay = (local_t2 - local_t1) - (tran_t - recv_t)/2**32
    print(f'Roundtrip delay: {rt_delay * 1e3:.3f} ms')

    print(f'Last update: {(tran_t - ref_t)/2**32:.3f} seconds ago')

    offset = ((recv_dt.timestamp() + 25200 - local_t1) + (tran_dt.timestamp() + 25200 - local_t2)) / 2
    print(f'System clock offset (7hr. adjusted): {offset * 1e3:.3f} ms')


if __name__ == '__main__':
    main()
