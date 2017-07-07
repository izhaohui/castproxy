#! /usr/bin/env python
# coding:UTF8
# author :zhaohui mail:zhaohui-sol@foxmail.com
import re
import time
import logging
import requests
import xmltodict
import pychromecast
from circuits import handler
from circuits_bricks.app import Log
from cocy.providers import MediaPlayer, Manifest, evented, combine_events


class GoogleCastRenderer(MediaPlayer):

    def __init__(self, address_or_name, display_name, proxy_base, **kwargs):
        super(GoogleCastRenderer, self).__init__(Manifest("CastProxy", display_name), **kwargs)
        self.player = None
        self.proxy = proxy_base
        self.address = address_or_name

        self.media_state = None
        self.player_state = None
        self.resource = None
        self.resource_state = None

        self.media_album = None
        self.media_title = None
        self.media_artist = None
        self.media_album_image = None

        if self.player and self.player.status:
            self.player.disconnect()
        if re.match(r"^(\d{1,3}\.){3}\d{1,3}$", self.address):
            self.player = pychromecast.Chromecast(self.address)
        else:
            self.player = next(cc for cc in pychromecast.get_chromecasts() if cc.device.friendly_name == self.address)
        if not self.player.is_idle:
            self.player.quit_app()
            time.sleep(1)
        self.player.register_status_listener(self)
        self.controller = self.player.media_controller
        self.controller.register_status_listener(self)
        self.player.wait()
        self.fire(Log(logging.INFO, "chromecast init."), "logger")

    def supportedMediaTypes(self):
        return ['http-get:*:audio/wav:*', 'http-get:*:audio/wave:*', 'http-get:*:audio/mpeg:*', 'http-get:*:audio/aac:*', 'http-get:*:audio/flac:*', 'http-get:*:audio/ogg:*']

    def new_media_status(self, state):
        self.media_state = state
        self.fire(Log(logging.INFO, "new media state, player state is %s." % (self.media_state.player_state if self.media_state else None)), "logger")
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
                self.state = "TRANSITIONING"
        else:
            self.state = "IDLE"
            self.source = None
            self.next_source = None
            self.resource_state = None
            self.source_meta_data = None

    def new_cast_status(self, state):
        self.player_state = state

    def _fetch_location(self, uri):
        response = requests.head(uri, timeout=5)
        if response.ok:
            location_key = "location" if "location" in response.headers else ("Location" if "Location" in response.headers else None)
            if location_key:
                return self._fetch_location(response.headers[location_key])
            else:
                if self.proxy:
                    proxy_uri = self.proxy + uri.encode("hex") + ".mp3" if uri.find("?") > 0 else uri
                else:
                    if uri.find("?") > 0:
                        self.fire(Log(logging.WARNING, "chromecast can not play urls with querystring."), "logger")
                    proxy_uri = uri
                self.fire(Log(logging.INFO, "chromcast play url %s" % proxy_uri), "logger")
                return {
                    'uri': proxy_uri,
                    'content_type': response.headers.get('Content-Type', "audio/mpeg")
                }
        else:
            return None

    @handler("load", override=True)
    @combine_events
    def _on_load(self, uri, meta_data):
        self.source = uri
        self.source_meta_data = meta_data
        self.tracks = 1
        self.current_track = 1
        self.next_source = ""
        self.next_source_meta_data = ""
        if meta_data:
            try:
                media_properties = xmltodict.parse(meta_data)
            except Exception, e:
                media_properties = None
                self.fire(Log(logging.WARNING, e.message), "logger")
            if media_properties:
                media_properties_item = media_properties.get("DIDL-Lite", dict()).get("item", dict())
                self.media_title = media_properties_item.get("dc:title")
                self.media_album = media_properties_item.get("upnp:album")
                self.media_artist = media_properties_item.get("upnp:artist")
                self.media_album_image = media_properties_item.get("upnp:albumArtURI")
        self.resource = self._fetch_location(uri)

    @handler("play", override=True)
    def _on_play(self):
        self.fire(Log(logging.DEBUG, "googlecast play called."), "logger")
        if self.resource and self.controller:
            if self.media_state and self.media_state.player_state == "PAUSED":
                self.controller.play()
            else:
                if not self.player.is_idle:
                    self.player.quit_app()
                    time.sleep(1)
                self.controller.play_media(self.resource['uri'], self.resource['content_type'], self.media_title, self.media_album_image)
                self.controller.block_until_active()
        else:
            self.fire(Log(logging.WARNING, "controller is not available"), "logger")

    @handler("stop", override=True)
    def _on_stop(self):
        if self.player.media_controller and self.player_state.session_id:
            self.player.media_controller.stop()
            self.player.quit_app()
        self.fire(Log(logging.INFO, "call stop."), "logger")

    @handler("pause", override=True)
    def _on_pause(self):
        if self.controller and self.player_state and self.player_state.session_id:
            self.controller.pause()
        else:
            pass

    @handler("seek", override=True)
    def _on_seek(self, target_sec):
        if self.media_state and self.media_state.duration and self.controller and self.player_state.session_id:
            self.controller.seek(target_sec)
        else:
            pass

    @handler("end_of_media", override=True)
    @combine_events
    def _end_media(self):
        self.fire(Log(logging.WARNING, "media end."), "logger")
        self._on_stop()

    @handler("stopped")
    def _stopped(self, event, component):
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
            if self.state == "PLAYING":
                _position = self.resource_state['position'] + (time.time() - self.resource_state['time'])
            elif self.state == "PAUSED":
                _position = self.resource_state['position']
            elif self.state == "TRANSITIONING":
                _position = self.resource_state['position']
            else:
                _position = 0
        else:
            _position = 0
        return _position

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

