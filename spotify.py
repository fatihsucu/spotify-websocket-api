#!/usr/bin/python

import base64, json, time, string, pprint, sys, re
from time import sleep
from ws4py.client.threadedclient import WebSocketClient

sys.path.append("proto")
import mercury_pb2, metadata_pb2, playlist4content_pb2, playlist4meta_pb2

base62 = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"

class Logging():
	log_level = 2

	@staticmethod
	def debug(str):
		if Logging.log_level >= 3:
			print "[DEBUG] " + str

	@staticmethod
	def notice(str):
		if Logging.log_level >= 2:
			print "[NOTICE] " + str

	@staticmethod
	def warn(str):
		if Logging.log_level >= 1:
			print "[WARN] " + str

	@staticmethod
	def error(str):
		if Logging.log_level >= 0:
			print "[ERROR] " + str

class SpotifyClient(WebSocketClient):
	def set_api(self, api):
		self.api_object = api

	def opened(self):
		self.api_object.login()

	def closed(self, code, reason=None):
		Logging.error("Connection closed, code %d reason %s" % (code, reason))

	def received_message(self, m):
		self.api_object.recv_packet(m)

class SpotifyUtil():
	@staticmethod
	def id2uri(uritype, v):
		res = []
		v = int(v, 16)
		while v > 0:
		    res = [v % 62] + res
		    v = v / 62
		id = ''.join([base62[i] for i in res])
		return "spotify:"+uritype+":"+id

	@staticmethod
	def uri2id(uri):
		v = 0
		s = uri.split(":")[2]
		for c in s:
		    v = v *62 + base62.index(c)
		return hex(v)[2:-1]

	@staticmethod
	def metadata_resp_to_obj(metadata_type, resp):
		if metadata_type == "album":
			obj = metadata_pb2.Album()
		elif metadata_type == "track":
			obj = metadata_pb2.Track()
		elif metadata_type == "artist":
			obj = metadata_pb2.Artist()
		else:
			Logging.error("invalid metadata_type given")
			return False

		obj.ParseFromString(base64.decodestring(resp[1]))
		return obj

class SpotifyAPI():
	def __init__(self, username, password, login_callback_func = None):
		self.auth_server = "https://play.spotify.com"

		self.username = username
		self.password = password
		self.settings = None
		self.connected = False

		self.ws = None
		self.seq = 0
		self.cmd_callbacks = {}
		self.login_callback = login_callback_func

	def auth(self):
		if self.settings != None:
			Logging.warn("You must only authenticate once per API object")
			return False

		with open ("settings.json", "r") as myfile:
			data=myfile.read().replace('\n', '')
			self.settings = json.loads(data)

	def login(self):
		Logging.notice("Logging in")
		credentials = self.settings["credentials"][0].split(":", 2)
		credentials[2] = credentials[2].decode("string_escape")
		credentials_enc = json.dumps(credentials, separators=(',',':'))

		self.send_command("connect", credentials, self.login_callback)

	def track_uri(self, id, codec, callback):
		args = [codec, id]
		self.send_command("sp/track_uri", args, callback)

	def metadata_request(self, metadata_type, id, callback):
		mercury_request = mercury_pb2.MercuryRequest()
		mercury_request.body = "GET"
		mercury_request.uri = "hm://metadata/"+metadata_type+"/"+id
		req = base64.encodestring(mercury_request.SerializeToString())
		args = [0, req]
		self.send_command("sp/hm_b64", args, callback)

	def playlist_request(self, playlist_id, fromnum, num, callback):
		mercury_request = mercury_pb2.MercuryRequest()
		mercury_request.body = "GET"
		mercury_request.uri = "hm://playlist/user/geel9/playlist/2ITsmcN6qU9NbotiH02Skn?from=0&length=200"
		req = base64.encodestring(mercury_request.SerializeToString())
		args = [0, req]
		self.send_command("sp/hm_b64", args, callback)

	def send_command(self, name, args, callback = None):
		msg = {
			"name": name,
			"id": str(self.seq),
			"args": args
		}

		if callback:
			self.cmd_callbacks[self.seq] = callback
		self.seq += 1

		self.send_string(msg)

	def send_string(self, msg):
		msg_enc = json.dumps(msg, separators=(',',':'))
		Logging.debug("sent " + msg_enc)
		self.ws.send(msg_enc)

	def recv_packet(self, msg):
		Logging.debug("recv " + str(msg))
		packet = json.loads(str(msg))
		if "error" in packet:
			self.handle_error(packet["error"])
			return
		elif "id" in packet:
			pid = packet["id"]
			if pid in self.cmd_callbacks:
				self.cmd_callbacks[pid](self, packet["result"])
				self.cmd_callbacks.pop(pid)
			else:
				Logging.notice("Unhandled command response with id " + str(pid))

	def handle_error(self, err):
		Logging.error(str(err))

	def connect(self):
		Logging.notice("Connecting to "+self.settings["aps"]["ws"][0])
		
		try:
			self.ws = SpotifyClient(self.settings["aps"]["ws"][0])
			self.ws.set_api(self)
			self.ws.connect()
			while not self.ws.terminated:
				continue
		except KeyboardInterrupt:
			self.ws.close()


def track_uri_callback(sp, result):
	print "URL: "+result["uri"]
	time.sleep(3)

def metadata_callback(sp, result):
	track = SpotifyUtil.metadata_resp_to_obj("track", result)
	print "Title: "+track.name
	print "Artist: "+track.artist[0].name
	sp.track_uri(SpotifyUtil.uri2id("spotify:track:6FjAGZp7c0Z2uaL3eHkXsx"), "mp3160", track_uri_callback)

def playlist_track_listing(sp, playlist_string):
	regex = "\\$(spotify:track:.+)"
	ret = re.findall(regex, playlist_string)
	return ret

def playlist_callback(sp, result):
	#We parse it into this because it seems to be able to get the
	#playlist NAME from the result.
	obj = playlist4content_pb2.ListItems()
	res = base64.decodestring(result[1])
	obj.ParseFromString(res)
	playlistname = obj.items[0].uri

	#We can't use protobuf to parse the playlist URIs (yet) so we need to regex it (I'M SORRY HEXXEH)
	tracks = playlist_track_listing(sp, res)
	print "Playlist name: " + playlistname
	print "There are " + `len(tracks)` + " track in this playlist"
	i = 0
	for track in tracks:
		print track
		id = SpotifyUtil.uri2id(track)
		#print id
		sp.track_uri(id, "mp3160", track_uri_callback)
		#sp.metadata_request("track", SpotifyUtil.uri2id(track), metadata_callback)
		i += 1


def login_callback(sp, result):
	sp.playlist_request("3U679q1vMPEJhFwrqP5RFw", 150, 200, playlist_callback)
	#sp.metadata_request("track", SpotifyUtil.uri2id("spotify:track:6JEK0CvvjDjjMUBFoXShNZ"), metadata_callback)

sp = SpotifyAPI("username", "password", login_callback)
sp.auth()
sp.connect()