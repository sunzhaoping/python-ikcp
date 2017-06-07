# -*- coding: utf8 -*-
from __future__ import absolute_import, division, print_function, with_statement
import binascii
import sys
import threading
import os
import errno
import atexit
import logging
import time

from cffi import FFI
from cffi.verifier import Verifier

include_dir = os.path.split(os.path.realpath(__file__))[0]
ffi = FFI()

def _create_modulename(cdef_sources, source, sys_version):
    """
    This is the same as CFFI's create modulename except we don't include the
    CFFI version.
    """
    key = '\x00'.join([sys_version[:3], source, cdef_sources])
    key = key.encode('utf-8')
    k1 = hex(binascii.crc32(key[0::2]) & 0xffffffff)
    k1 = k1.lstrip('0x').rstrip('L')
    k2 = hex(binascii.crc32(key[1::2]) & 0xffffffff)
    k2 = k2.lstrip('0').rstrip('L')
    return '_Ikcp_cffi_{0}{1}'.format(k1, k2)

def _compile_module(*args, **kwargs):
    raise RuntimeError(
        "Attempted implicit compile of a cffi module. All cffi modules should be pre-compiled at installation time."
    )

class LazyLibrary(object):
    def __init__(self, ffi):
        self._ffi = ffi
        self._lib = None
        self._lock = threading.Lock()

    def __getattr__(self, name):
        if self._lib is None:
            with self._lock:
                if self._lib is None:
                    self._lib = self._ffi.verifier.load_library()

        return getattr(self._lib, name)

CDEF="""
typedef int16_t IINT16;
typedef int32_t IINT32;
typedef int64_t IINT64;
typedef uint16_t IUINT16;
typedef uint32_t IUINT32;
typedef uint64_t IUINT64;

struct IQUEUEHEAD {
    struct IQUEUEHEAD *next, *prev;
};

typedef struct IQUEUEHEAD iqueue_head;

//=====================================================================
// SEGMENT
//=====================================================================
struct IKCPSEG
{
    struct IQUEUEHEAD node;
    IUINT32 conv;
    IUINT32 cmd;
    IUINT32 frg;
    IUINT32 wnd;
    IUINT32 ts;
    IUINT32 sn;
    IUINT32 una;
    IUINT32 len;
    IUINT32 resendts;
    IUINT32 rto;
    IUINT32 fastack;
    IUINT32 xmit;
    char data[1];
};


//---------------------------------------------------------------------
// IKCPCB
//---------------------------------------------------------------------
struct IKCPCB
{
    IUINT32 conv, mtu, mss, state;
    IUINT32 snd_una, snd_nxt, rcv_nxt;
    IUINT32 ts_recent, ts_lastack, ssthresh;
    IINT32 rx_rttval, rx_srtt, rx_rto, rx_minrto;
    IUINT32 snd_wnd, rcv_wnd, rmt_wnd, cwnd, probe;
    IUINT32 current, interval, ts_flush, xmit;
    IUINT32 nrcv_buf, nsnd_buf;
    IUINT32 nrcv_que, nsnd_que;
    IUINT32 nodelay, updated;
    IUINT32 ts_probe, probe_wait;
    IUINT32 dead_link, incr;
    struct IQUEUEHEAD snd_queue;
    struct IQUEUEHEAD rcv_queue;
    struct IQUEUEHEAD snd_buf;
    struct IQUEUEHEAD rcv_buf;
    IUINT32 *acklist;
    IUINT32 ackcount;
    IUINT32 ackblock;
    void *user;
    char *buffer;
    int fastresend;
    int nocwnd, stream;
    int logmask;
    int (*output)(const char *buf, int len, struct IKCPCB *kcp, void *user);
    void (*writelog)(const char *log, struct IKCPCB *kcp, void *user);
};


typedef struct IKCPCB ikcpcb;

#define IKCP_LOG_OUTPUT            1
#define IKCP_LOG_INPUT            2
#define IKCP_LOG_SEND            4
#define IKCP_LOG_RECV            8
#define IKCP_LOG_IN_DATA        16
#define IKCP_LOG_IN_ACK            32
#define IKCP_LOG_IN_PROBE        64
#define IKCP_LOG_IN_WINS        128
#define IKCP_LOG_OUT_DATA        256
#define IKCP_LOG_OUT_ACK        512
#define IKCP_LOG_OUT_PROBE        1024
#define IKCP_LOG_OUT_WINS        2048

//---------------------------------------------------------------------
// interface
//---------------------------------------------------------------------

// create a new kcp control object, 'conv' must equal in two endpoint
// from the same connection. 'user' will be passed to the output callback
// output callback can be setup like this: 'kcp->output = my_udp_output'
ikcpcb* ikcp_create(IUINT32 conv, void *user);

// release kcp control object
void ikcp_release(ikcpcb *kcp);

// set output callback, which will be invoked by kcp^M
void ikcp_setoutput(ikcpcb *kcp, int (*output)(const char *buf, int len, ikcpcb *kcp, void *user));

// user/upper level recv: returns size, returns below zero for EAGAIN
int ikcp_recv(ikcpcb *kcp, char *buffer, int len);

// user/upper level send, returns below zero for error
int ikcp_send(ikcpcb *kcp, const char *buffer, int len);

// update state (call it repeatedly, every 10ms-100ms), or you can ask
// ikcp_check when to call it again (without ikcp_input/_send calling).
// 'current' - current timestamp in millisec.
void ikcp_update(ikcpcb *kcp, IUINT32 current);

// Determine when should you invoke ikcp_update:
// returns when you should invoke ikcp_update in millisec, if there
// is no ikcp_input/_send calling. you can call ikcp_update in that
// time, instead of call update repeatly.
// Important to reduce unnacessary ikcp_update invoking. use it to
// schedule ikcp_update (eg. implementing an epoll-like mechanism,
// or optimize ikcp_update when handling massive kcp connections)
IUINT32 ikcp_check(const ikcpcb *kcp, IUINT32 current);

// when you received a low level packet (eg. UDP packet), call it
int ikcp_input(ikcpcb *kcp, const char *data, long size);

// flush pending data
void ikcp_flush(ikcpcb *kcp);

// check the size of next message in the recv queue
int ikcp_peeksize(const ikcpcb *kcp);

// change MTU size, default is 1400
int ikcp_setmtu(ikcpcb *kcp, int mtu);

// set maximum window size: sndwnd=32, rcvwnd=32 by default
int ikcp_wndsize(ikcpcb *kcp, int sndwnd, int rcvwnd);

// get how many packet is waiting to be sent
int ikcp_waitsnd(const ikcpcb *kcp);

// fastest: ikcp_nodelay(kcp, 1, 20, 2, 1)
// nodelay: 0:disable(default), 1:enable
// interval: internal update timer interval in millisec, default is 100ms
// resend: 0:disable fast resend(default), 1:enable fast resend
// nc: 0:normal congestion control(default), 1:disable congestion control
int ikcp_nodelay(ikcpcb *kcp, int nodelay, int interval, int resend, int nc);

//int ikcp_rcvbuf_count(const ikcpcb *kcp);
//int ikcp_sndbuf_count(const ikcpcb *kcp);

void ikcp_log(ikcpcb *kcp, int mask, const char *fmt, ...);

// setup allocator
void ikcp_allocator(void* (*new_malloc)(size_t), void (*new_free)(void*));

// read conv
IUINT32 ikcp_getconv(const void *ptr);
"""
SOURCE = """
#include <ikcp.c>
"""
ffi.cdef(CDEF)
ffi.verifier = Verifier(ffi,SOURCE , include_dirs=[include_dir], modulename=_create_modulename(CDEF, SOURCE, sys.version))
ffi.verifier.compile_module = _compile_module
ffi.verifier._compile_module = _compile_module

ikcp_impl = LazyLibrary(ffi)

@ffi.callback("int(const char *, int , ikcpcb*, void *)")
def ikcp_output(cdata, size, kcp, user_handle):
    buffer = ffi.buffer(cdata = cdata, size = size)
    kcp = ffi.from_handle(user_handle)
    return kcp.output(buffer)

DEFAULT_MODE = 0
NORMAL_MODE = 1
FAST_MODE = 2

class IKcp(object):
    def __init__(self, socket, conv, mode = DEFAULT_MODE):
        user_handle = ffi.new_handle(self)
        self._handle = user_handle
        self._kcp = ikcp_impl.ikcp_create(conv , user_handle)
        self._kcp.output = ikcp_output
        self._socket = socket

        if mode == DEFAULT_MODE:
            ikcp_impl.ikcp_nodelay(self._kcp, 0, 10, 0, 0)
        elif mode == NORMAL_MODE:
            ikcp_impl.ikcp_nodelay(self._kcp, 0, 10, 0, 1)
        else:
            ikcp_impl.ikcp_nodelay(self._kcp, 1, 10, 2, 1)

    def __del__(self):
        if self._kcp != ffi.NULL:
            ikcp_impl.ikcp_release(self._kcp)

    def output(self, buffer):
        self._socket.send(buffer);
        return -1

    @property
    def rx_minrto(self):
        return self._kcp.rx_minrto

    @rx_minrto.setter
    def rx_minrto(self,value):
        self._kcp.rx_minrto = value

    @property
    def waitsnd(self):
        return ikcp_impl.ikcp_waitsnd(self._kcp)

    @property
    def peeksize(self):
        return ikcp_impl.ikcp_peeksize(self._kcp)

    @property
    def mtu(self):
        return self._kcp.mtu

    @mtu.setter
    def mtu(self, value):
        return ikcp_impl.ikcp_setmtu(self._kcp, value)

    @property
    def connected(self):
        return self._kcp.state == 0

    @property
    def sndwnd(self):
        return self._kcp.snd_wnd

    @property
    def rcvwnd(self):
        return self._kcp.rcv_wnd

    def wndsize(self, sndwnd, rcvwnd):
        return ikcp_impl.ikcp_wndsize(self._kcp, sndwnd, rcvwnd)

    def recv(self, buff_size):
        out = ffi.new('uint8_t[%d]' % (buff_size))
        size = ikcp_impl.ikcp_recv(self._kcp, out, buff_size)
        if size < 0:
            return None
        return ffi.buffer(out)[:size]

    def send(self, data):
        return ikcp_impl.ikcp_send(self._kcp, data, len(data))

    def update(self):
        ikcp_impl.ikcp_update(self._kcp,ffi.cast("IUINT32", int(time.time()*1000)))

    def check(self):
        return ikcp_impl.ikcp_check(self._kcp, ffi.cast("IUINT32", int(time.time()*1000)))

    def input(self, data):
        return ikcp_impl.ikcp_input(self._kcp, data, len(data))

    def on_input(self, sock, data, address):
        self.input(data)

    def flush(self):
        ikcp_impl.ikcp_flush(self._kcp)

    def nodelay(self, nodelay, interval, resend, nc):
        return ikcp_impl.ikcp_nodelay(self._kcp, nodelay ,interval ,resend, nc)

    @classmethod
    def get_conv(cls, data):
        return ikcp_impl.ikcp_getconv(data)
