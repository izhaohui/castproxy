#! /usr/bin/env python
# coding:UTF8
# author :zhaohui mail:zhaohui-sol@foxmail.com


import sys
reload(sys).setdefaultencoding('utf-8')
import re
import time
import requests
import pychromecast
from circuits import Debugger
from circuits import handler
from circuits.tools import graph
from circuits_bricks.app import Application, logging
from cocy.providers import MediaPlayer, Manifest, evented, combine_events
from cocy.upnp import UPnPDeviceServer
from .proxyserver import ProxyServer


class GoogleCastRenderer(MediaPlayer):

    manifest = Manifest("GoogleCast", "Cast Proxy")

    def __init__(self, address_or_name, proxy_base, **kwargs):
        super(GoogleCastRenderer, self).__init__(self.manifest, **kwargs)
        self.proxy = proxy_base
        self.address = address_or_name

        self.media_state = None
        self.player_state = None
        self.resource = None
        self.resource_state = None

        if re.match(r"^(\d{1,3}\.){3}\d{1,3}$", self.address):
            self.player = pychromecast.Chromecast(address_or_name)
        else:
            self.player = next(cc for cc in pychromecast.get_chromecasts() if cc.friendly_name == self.address)

        self.player.register_status_listener(self)
        self.controller = self.player.media_controller
        self.controller.register_status_listener(self)
        self.player.wait()
        logging.warning("chromecast init.")

    def supportedMediaTypes(self):
        return ['http-get:*:audio/wave:*', 'http-get:*:audio/mpeg:*', 'http-get:*:audio/aac:*', 'http-get:*:audio/flac:*']

    def new_media_status(self, state):
        self.media_state = state
        logging.warning("new media state available, player state is %s." %
                        (self.media_state.player_state if self.media_state else None))
        if self.media_state and self.media_state.player_state in ("PLAYING", "PAUSED", "BUFFERING"):
            self.resource_state = {
                "time": time.time(),
                "position": self.media_state.current_time,
                "duration": self.media_state.duration,
                "state": self.media_state.player_state
            }
            if self.media_state.player_state == "PLAYING":
                self.state = "PLAYING"
            elif self.media_state.player_state == "PAUSED":
                self.state = "PAUSED"
            else:
                pass
                # self.state = "TRANSITIONING"
        else:
            self.resource_state = None
            if self.state != "IDLE":
                self.state = "IDLE"
                self.source = None
                self.next_source = None
                self.source_meta_data = None
            else:
                pass

    def new_cast_status(self, state):
        self.player_state = state
        if not state:
            self.reconnect()
        else:
            pass

    def reconnect(self):
        if self.player:
            self.player.quit_app()
            self.player.disconnect()
        else:
            logging.warning("player is not available")
        if re.match(r"^(\d{1,3}\.){3}\d{1,3}$", self.address):
            self.player = pychromecast.Chromecast(self.address)
        else:
            self.player = next(cc for cc in pychromecast.get_chromecasts() if cc.friendly_name == self.address)
        self.player.register_status_listener(self)
        self.controller = self.player.media_controller
        self.controller.register_status_listener(self)
        self.player.wait()
        logging.warning("reconnect chromecast....")

    def transform(self, uri):
        response = requests.head(uri, timeout=5)
        if response.ok:
            location_key = "location" if "location" in response.headers else ("Location" if "Location" in response.headers else None)
            if location_key:
                return self.transform(response.headers[location_key])
            else:
                if self.proxy:
                    proxy_uri = self.proxy + uri.encode("hex") + ".mp3" if uri.find("?") > 0 else uri
                else:
                    if uri.find("?") > 0:
                        logging.warning("chromecast can not play urls with querystring.")
                    proxy_uri = uri
                logging.warning("chromcast play url %s" % proxy_uri)
                return {
                    'uri': proxy_uri,
                    'content_type': response.headers.get('Content-Type', "audio/mpeg")
                }
        else:
            return None

    @handler("load")
    @combine_events
    def _on_load(self, uri, meta_data):
        self.source = uri
        self.source_meta_data = meta_data
        self.tracks = 1
        self.current_track = 1
        self.next_source = ""
        self.next_source_meta_data = ""
        self._on_stop()
        self.resource = self.transform(uri)

    @handler("play")
    def _on_play(self):
        if self.resource and self.controller:
            if self.media_state and self.media_state.player_state == "PAUSED":
                self.controller.play()
            else:
                self.controller.play_media(self.resource['uri'], self.resource['content_type'])
                self.controller.block_until_active()
        else:
            logging.warning("controller is not available")

    @handler("stop")
    def _on_stop(self):
        if self.controller and self.player_state.session_id and self.media_state:
            if self.media_state.player_state != "IDLE":
                self.controller.stop()
                time.sleep(1)
        else:
            pass
        self.player.quit_app()

    @handler("pause")
    def _on_pause(self):
        if self.controller and self.player_state.session_id:
            self.controller.pause()
        else:
            pass

    @handler("seek")
    def _on_seek(self, target_sec):
        if self.media_state and self.media_state.duration and self.controller and self.player_state.session_id:
            self.controller.seek(target_sec)
        else:
            pass

    @handler("end_of_media")
    def _end_media(self):
        self._on_stop()

    @handler("stopped")
    def _stopped(self):
        if self.player:
            self.player.quit_app()
            self.player.disconnect()
        else:
            pass

    @property
    def current_track_duration(self):
        if self.resource_state:
            _duration = self.resource_state['duration']
            return _duration
        else:
            return 0

    def current_position(self):
        if self.resource_state:
            logging.warning("get position when state is %s" % self.resource_state['state'])
            if self.resource_state['state'] == "PLAYING":
                _position = self.resource_state['position'] + (time.time() - self.resource_state['time'])
            elif self.resource_state['state'] == "PAUSED" or self.resource_state['state'] == "BUFFERING":
                _position = self.resource_state['position']
            else:
                _position = 0
            return _position
        else:
            return 0

    @property
    def volume(self):
        if self.player_state:
            return self.player_state.volume_level
        else:
            return 0

    @volume.setter
    @evented(auto_publish=True)
    def volume(self, volume):
        self.player.set_volume(volume)

if __name__ == '__main__':
    application = Application("CastProxy", None)
    upnp_dev_server = UPnPDeviceServer(application.app_dir).register(application)
    web_proxy_server = ProxyServer(host='0.0.0.0', port=18080).register(application)
    # Debugger().register(application)
    media_renderer = GoogleCastRenderer("192.168.33.43", "http://192.168.33.33:18080/proxy/").register(application)
    print graph(application)
    application.run()
