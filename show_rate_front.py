# get rate from all VMs.

import asyncio
import websockets
import tornado.ioloop
import tornado.web
import tornado.httpserver as httpserver
import tornado.websocket as websocket
import json
import time
import sys
import curses
# from curses import wrapper
import signal
from threading import Lock
from tornado.websocket import WebSocketClosedError

# hostname to bandwidth
host_usage = {}
usage_lock = Lock()
# hostname to line
host_line = {}

# cnn tf result
cnn_current = {}
speed_his = {}
cnn_dict = {
    'step': '0',
    'speed_mean': '0',
    'speed_uncertainty': '0',
    'speed_jitter': '0',
    'total_loss': '0',
    'top_1_accuracy': '0',
    'top_5_accuracy': '0'
}
cnn_lock = Lock()


class PrintCurses:
    stdscr = curses.initscr()
    scrlock = Lock()

    @staticmethod
    def init():
        curses.noecho()
        PrintCurses.stdscr.clear()
        PrintCurses.stdscr.addstr(0, 0, "hostname\t\ttx\t\trx\t\tcpu\t\tmem\n")
        PrintCurses.stdscr.refresh()

    @staticmethod
    def print(line, info):
        output = '{}\t\t{}\t\t{}\t\t{}\t\t{}\n'.format(info['hostname'], info['tx'], info['rx'], info['cpu_usage'], info['mem_util'])
        PrintCurses.stdscr.addstr(line, 0, output)
        PrintCurses.stdscr.refresh()


def signal_handler(sig, frame):
    PrintCurses.stdscr.clear()
    curses.echo()
    curses.endwin()
    sys.exit(0)


timestap = lambda: int(time.time() * 1000)


class UsageHistory:
    def __init__(self):
        self.usage_history = []

    def push(self, bw_data):
        if len(self.usage_history) >= 10:
            self.usage_history.pop(0)
        self.usage_history.append(bw_data)

    def dump(self):
        return json.dumps(self.usage_history)

    def get_latest(self):
        return self.usage_history[-1]

    def latest_bw(self):
        if len(self.usage_history) == 0:
            return 0.0
        else:
            return self.usage_history[-1]['rx']

    def latest_cpu(self):
        if len(self.usage_history) == 0:
            return 0.0
        else:
            return self.usage_history[-1]['cpu_usage']


"""
async def show_usage(websocket, path):
    ip_addr = path.strip('/').strip().replace('-', '.')
    uri = 'ws://{}:9999'.format(ip_addr)
    if ip_addr not in host_bw:
        host_bw[ip_addr] = BwHistory()
    async with websockets.connect(uri) as the_socket:
        while True:
            msg = await the_socket.recv()
            usage = json.loads(msg)
            time = timestap()
            host_bw[ip_addr].push({'x': time, 'y': float(usage['tx'])})
            msg = json.dumps({'chart': host_bw[ip_addr].dump()})
            await websocket.send(msg)
"""


def print_bw(stdscr):
    stdscr.clear()
    stdscr.addstr(0, 0, "hostname\t\ttx\t\trx\t\tcpu\t\tmem\n")
    for host in host_usage:
        info = host_usage[host].get_latest()
        output = '{}\t\t{}\t\t{}\t\t{}\t\t{}\n'.format(info['hostname'], info['tx'], info['rx'], info['cpu_usage'], info['mem_util'])
        stdscr.addstr(host_line[host], 0, output)
        stdscr.refresh()


class VMPostHandler(tornado.web.RequestHandler):
    def post(self):
        vm_info = json.loads(self.request.body.decode('utf-8'))
        # print('received:', vm_info)
        hostname = vm_info['hostname']
        if hostname not in host_usage:
            host_usage[hostname] = UsageHistory()
            host_line[hostname] = len(host_usage)

        usage_lock.acquire()
        try:
            host_usage[hostname].push(vm_info)
        finally:
            usage_lock.release()
        output = '{}\t\t{}\t\t{}\t\t{}\t\t{}\n'.format(vm_info['hostname'], vm_info['tx'], vm_info['rx'],
                                                       vm_info['cpu_usage'], \
                                                       vm_info['mem_util'])
        # print(output, end="")
        # wrapper(print_bw)
        PrintCurses.scrlock.acquire()
        try:
            PrintCurses.print(host_line[hostname], vm_info)
        finally:
            PrintCurses.scrlock.release()
        self.set_status(200)
        self.finish()


class BwHistoryHandler(websocket.WebSocketHandler):

    def check_origin(self, origin):
        return True

    async def on_message(self, message):
        try:
            while True:
                usage_lock.acquire()
                try:
                    history = host_usage.get(message, UsageHistory())
                finally:
                    usage_lock.release()
                msg = {'hostname': message, 'usage': history.dump()}
                await self.write_message(json.dumps(msg))
                await asyncio.sleep(1)
        except WebSocketClosedError:
            pass


class CurBwHandler(websocket.WebSocketHandler):

    def check_origin(self, origin):
        return True

    async def on_message(self, message):
        vm_list = json.loads(message)['vm']
        try:
            while True:
                usage_lock.acquire()
                try:
                    bw_real = {}
                    for vm in vm_list:
                        bw_real[vm] = host_usage.get(vm, UsageHistory()).latest_bw()
                finally:
                    usage_lock.release()
                msg = json.dumps(bw_real)
                await self.write_message(msg)
                await asyncio.sleep(1)
        except WebSocketClosedError:
            pass


class CurCpuHandler(websocket.WebSocketHandler):

    def check_origin(self, origin):
        return True

    async def on_message(self, message):
        vm_list = json.loads(message)['vm']
        try:
            while True:
                usage_lock.acquire()
                try:
                    bw_real = {}
                    for vm in vm_list:
                        bw_real[vm] = host_usage.get(vm, UsageHistory()).latest_cpu()
                finally:
                    usage_lock.release()
                msg = json.dumps(bw_real)
                await self.write_message(msg)
                await asyncio.sleep(1)
        except WebSocketClosedError:
            pass

class CnnHandler(tornado.web.RequestHandler):
    def post(self):
        Cnninfo = json.loads(self.request.body.decode('utf-8'))
        cnn_lock.acquire()
        try:
            cnn_dict['step'] = Cnninfo[0]
            cnn_dict['speed_mean'] = Cnninfo[1]
            cnn_dict['speed_uncertainty'] = Cnninfo[2]
            cnn_dict['speed_jitter'] = Cnninfo[3]
            cnn_dict['total_loss'] = Cnninfo[4]
            cnn_dict['top_1_accuracy'] = Cnninfo[5]
            cnn_dict['top_5_accuracy'] = Cnninfo[6]
            cnn_current.clear()
            cnn_current[Cnninfo[7].strip("'")] = cnn_dict
            if len(speed_his) == 10:
                if speed_his.get('1') != None:
                    speed_his.pop('1')
                else:
                    l = int(Cnninfo[0])-50
                    speed_his.pop(f'{l}')
            speed_his[Cnninfo[0]] = Cnninfo[1]
            print(cnn_current)
            print("--------------")
            print(speed_his)
        finally:
            cnn_lock.release()
        self.set_status(200)
        self.finish()


class CnnRequestHandler(websocket.WebSocketHandler):

    def check_origin(self, origin):
        return True

    def open(self):
        print("WebSocket opened")

    async def on_message(self, message):
        vm_list = json.loads(message)['vm']
        print(cnn_current["172.17.255.211"])
        try:
            # while True:
            cnn_lock.acquire()
            try:
                dict = {}
                for vm in vm_list:
                    print(vm)
                    dict[vm] = cnn_current.get(vm, ' ')
            finally:
                cnn_lock.release()
            msg = json.dumps(dict)
            print(msg)
            await self.write_message(msg)
            await asyncio.sleep(1)
        except WebSocketClosedError:
            pass

class CnnHisHandler(websocket.WebSocketHandler):

    def check_origin(self, origin):
        return True

    def open(self):
        print("WebSocket opened")

    async def on_message(self, message):
        vm_list = json.loads(message)['vm']
        print(cnn_current)
        try:
            # while True:
            cnn_lock.acquire()
            try:
                dict = speed_his
            finally:
                cnn_lock.release()
            msg = json.dumps(dict)
            print(msg)
            await self.write_message(msg)
            await asyncio.sleep(1)
        except WebSocketClosedError:
            pass


if __name__ == '__main__':
    app = tornado.web.Application([
        (r'/', VMPostHandler),
        (r'/usage', BwHistoryHandler),
        (r'/hoseusage', CurBwHandler),
        (r'/cpuusage', CurCpuHandler),
        (r'/cnn_param', CnnHandler),
        (r'/cnn_request', CnnRequestHandler),
        (r'/cnn_his', CnnHisHandler)
    ], debug=True)
    # signal.signal(signal.SIGINT, signal_handler)
    # PrintCurses.init()
    http_server = tornado.httpserver.HTTPServer(app)
    http_server.listen(80, address='0.0.0.0')
    tornado.ioloop.IOLoop.instance().start()

