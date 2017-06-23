#!/usr/bin/python
# coding:UTF8
# author :zhaohui mail:zhaohui-sol@foxmail.com

import re
import threading

import tornado.ioloop
import tornado.web
from circuits import Component
from circuits import handler
from tornado import httpclient


class Handler(tornado.web.RequestHandler):

    def __init__(self, *args, **kwargs):
        super(Handler, self).__init__(*args, **kwargs)

    @tornado.gen.coroutine
    @tornado.web.asynchronous
    def get(self):
        headers = dict()
        resource_url = self.request.path[7:-4]
        resource_url = resource_url.decode('hex') if resource_url and len(resource_url) > 4 else None
        if resource_url:
            for header_name in self.request.headers:
                if header_name in ("Accept", "Range"):
                    headers[header_name] = self.request.headers[header_name]
            client = httpclient.AsyncHTTPClient()
            request = httpclient.HTTPRequest(resource_url, header_callback=self.on_header, streaming_callback=self.on_chunk, headers=headers)
            client.fetch(request)
        else:
            self.send_error(404)

    def on_header(self, header):
        override_headers = ("Accept-Ranges", "Last-Modified", "Etag", "Content-Type", "Content-Range")
        if header.startswith("HTTP/1"):
            status_code = re.search(r"HTTP/1\.\d\s(\d+)\s[A-Z]+", header, re.I).group(1)
            self.set_status(int(status_code))
        else:
            if header.find(":") > 0:
                index = header.find(":")
                header_name, header_value = header[0:index], header[index + 1:].strip()
                if header_name in override_headers:
                    self.set_header(header_name, header_value)
            else:
                pass

    def on_chunk(self, chunk):
        self.write(chunk)
        self.flush()


class ProxyServer(Component):

    def __init__(self, host='0.0.0.0', port=18080):
        super(ProxyServer, self).__init__()
        self.host = host
        self.port = port

    def _start_web(self):
        app = tornado.web.Application([
            (r"/proxy/.*\.mp3", Handler),
        ])
        app.listen(self.port, self.host)
        tornado.ioloop.IOLoop.current().start()

    def _stop_web(self):
        tornado.ioloop.IOLoop.current().stop()

    @handler("started", channel="application")
    def _on_started(self, component):
        threading.Thread(target=self._start_web).start()

    @handler("stopped", channel="*")
    def _on_stopped(self, event, component):
        self._stop_web()

if __name__ == "__main__":
    app = tornado.web.Application([
        (r"/proxy/.*\.mp3", Handler),
    ])
    app.listen(18080)
    tornado.ioloop.IOLoop.current().start()
