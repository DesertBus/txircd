# -*- coding: utf-8 -*-

from twisted.internet import reactor
from twisted.python import log
from twisted.words.protocols import irc
from twisted.internet.defer import Deferred
from txircd.channel import IRCChannel
from txircd.utils import irc_lower, now, epoch, CaseInsensitiveDictionary, chunk_message
import socket, hashlib

class IRCUser(object):
	
	def __init__(self, parent):
		# Mask the IP
		ip = parent.transport.getPeer().host
		if ip in parent.factory.servconfig["client_vhosts"]:
			hostname = parent.factory.servconfig["client_vhosts"][ip]
		else:
			try:
				hostname = socket.gethostbyaddr(ip)[0]
				if ip == socket.gethostbyname(hostname):
					index = hostname.find(ip)
					index = hostname.find(".") if index < 0 else index + len(ip)
					if index < 0:
						# Give up
						hostname = "tx{}.IP".format(hashlib.md5(ip).hexdigest()[12:20])
					else:
						mask = "tx{}".format(hashlib.md5(hostname[:index]).hexdigest()[12:20])
						hostname = "{}{}".format(mask, hostname[index:])
				else:
					hostname = "tx{}.IP".format(hashlib.md5(ip).hexdigest()[12:20])
			except IOError:
				hostname = "tx{}.IP".format(hashlib.md5(ip).hexdigest()[12:20])
		"""
		geo_data = parent.factory.geo_db.record_by_addr(ip) if parent.factory.geo_db else None
		if not geo_data:
			geo_data = {"latitude":None,"longitude":None,"country_name":None}
		"""
		
		# Set attributes
		self.ircd = parent.factory
		self.socket = parent
		self.password = None
		self.nickname = None
		self.username = None
		self.realname = None
		self.hostname = hostname
		self.ip = ip
		self.latitude = geo_data["latitude"]
		self.longitude = geo_data["longitude"]
		self.country = geo_data["country_name"]
		self.server = parent.factory.servconfig["server_name"]
		self.signon = now()
		self.lastactivity = now()
		self.lastpong = now()
		self.mode = {}
		self.channels = CaseInsensitiveDictionary()
		self.disconnected = Deferred()
		self.registered = 2
		self.cap = {}
		self.metadata = { # split into metadata key namespaces, see http://ircv3.atheme.org/specification/metadata-3.2
			"server": {},
			"user": {},
			"client": {},
			"ext": {},
			"private": {}
		}
		self.cache = {}
		self.cmd_extra = False # used by the command handler to determine whether the extras hook was called during processing
	
	def register(self):
		if self.nickname in self.ircd.users:
			return
		tryagain = []
		for action in self.ircd.actions:
			outCode = action.onRegister(self)
			if outCode == "again":
				tryagain.append(action.onRegister)
			elif not outCode:
				return self.disconnect(None)
		for action in tryagain:
			if not action(self):
				return self.disconnect(None)
		
		# Add self to user list
		self.ircd.users[self.nickname] = self
		
		# Send all those lovely join messages
		chanmodelist = "".join(["".join(modedict.keys()) for modedict in self.ircd.channel_modes] + "".join(self.ircd.prefixes.keys()))
		self.sendMessage(irc.RPL_WELCOME, ":Welcome to the Internet Relay Network {}".format(self.prefix()))
		self.sendMessage(irc.RPL_YOURHOST, ":Your host is {}, running version {}".format(self.ircd.servconfig["network_name"], self.ircd.version))
		self.sendMessage(irc.RPL_CREATED, ":This server was created {}".format(self.ircd.created))
		self.sendMessage(irc.RPL_MYINFO, self.ircd.servconfig["network_name"], self.ircd.version, self.mode.allowed(), chanmodelist) # usermodes & channel modes
		self.send_isupport()
		self.send_motd()
	
	def send_isupport(self):
		isupport = [
			"CASEMAPPING=rfc1459",
			"CHANMODES={}".format(",".join(["".join(modedict.keys()) for modedict in self.ircd.channel_modes])),
			"CHANNELLEN=64",
			"CHANTYPES={}".format(self.ircd.channel_prefixes),
			"MODES=20",
			"NETWORK={}".format(self.ircd.servconfig["network_name"]),
			"NICKLEN=32",
			"PREFIX=({}){}".format(self.ircd.prefix_order, "".join([self.ircd.prefix_symbols[mode] for mode in self.ircd.prefix_order])),
			"STATUSMSG={}".format("".join([self.ircd.prefix_symbols[mode] for mode in self.ircd.prefix_order])),
			"TOPICLEN=316"
		]
		prevar_len = len(" ".join([self.ircd.servconfig["server_name"], irc.RPL_ISUPPORT, self.nickname])) + 31 # including ":are supported by this server"
		thisline = []
		while isupport:
			if len(" ".join(thisline)) + len(isupport[0]) + prevar_len > 509:
				self.sendMessage(irc.RPL_ISUPPORT, " ".join(thisline), ":are supported by this server")
				thisline = []
			thisline.append(isupport.pop(0))
		if thisline:
			self.sendMessage(irc.RPL_ISUPPORT, " ".join(thisline), ":are supported by this server")
	
	def disconnect(self, reason):
		if self.nickname in self.ircd.users:
			for action in self.ircd.actions:
				action.onQuit(self, reason)
			quitdest = set()
			for channel in self.channels.iterkeys():
				chanusers = self.ircd.channels[channel].users
				del chanusers[self.nickname]
				for u in chanusers.itervalues():
					quitdest.add(u)
			del self.ircd.users[self.nickname]
			for user in quitdest:
				user.sendMessage("QUIT", ":{}".format(reason), to=None, prefix=self.prefix())
		self.socket.transport.loseConnection()
	
	def checkData(self, data):
		if data > self.ircd.servconfig["client_max_data"] and not self.mode.has("o"):
			log.msg("Killing user '{}' for flooding".format(self.nickname))
			self.irc_QUIT(None,["Killed for flooding"])
	
	def connectionLost(self, reason):
		# TODO: use the proper quit mechanism
		self.irc_QUIT(None,["Client connection lost"])
		self.disconnected.callback(None)
	
	def handleCommand(self, command, prefix, params):
		if command in self.ircd.commands:
			cmd = self.ircd.commands[command]
			cmd.updateActivity(self)
			data = cmd.processParams(self, params)
			if not data:
				return
			permData = self.commandPermission(command, data)
			if permData:
				cmd.onUse(self, permData)
				if not self.cmd_extra:
					self.commandExtraHook(command, permData)
				self.cmd_extra = False
		else:
			self.sendMessage(irc.ERR_UNKNOWNCOMMAND, command, ":Unknown command")
	
	def commandPermission(self, command, data):
		tryagain = set()
		for modfunc in self.ircd.actions["commandpermission"]:
			permData = modfunc(self, command, data)
			if perm == "again":
				tryagain.add(modfunc)
			else:
				data = permData
				if "force" in data and data["force"]:
					return data
				if not data:
					return {}
		if "targetchan" in data:
			for modeset in self.ircd.channel_modes:
				for implementation in modeset.itervalues():
					permData = implementation.checkPermission(self, command, data)
					if permData == "again":
						tryagain.add(implementation.checkPermission)
					else:
						data = permData
						if "force" in data and data["force"]:
							return data
						if not data:
							return {}
		for modeset in self.ircd.user_modes:
			for implementation in modeset.itervalues():
				permData = implementation.checkPermission(self, command, data)
				if permData == "again":
					tryagain.add(implementation.checkPermission)
				else:
					data = permData
					if "force" in data and data["force"]:
						return data
					if not data:
						return {}
		for modfunc in tryagain:
			data = modfunc(self, command, data)
			if "force" in data and data["force"]:
				return data
			if not data:
				return {}
		return data
	
	def commandExtraHook(self, command, data):
		self.cmd_extra = True
		for modfunc in self.ircd.actions["commandextra"]:
			modfunc(command, data)
	
	def sendMessage(self, command, *parameter_list, **kw):
		if "prefix" not in kw:
			kw["prefix"] = self.ircd.servconfig["server_name"]
		if not kw["prefix"]:
			del kw["prefix"]
		if "to" not in kw:
			kw["to"] = self.nickname
		if kw["to"]:
			arglist = [command, kw["to"]] + list(parameter_list)
		else:
			arglist = [command] + list(parameter_list)
		self.socket.sendMessage(*arglist, **kw)
	
	#=====================
	#== Utility Methods ==
	#=====================
	def prefix(self):
		return "{}!{}@{}".format(self.nickname, self.username, self.hostname)
	
	# TODO: consider making these take channel objects instead of names; would be more efficient in many cases where we don't have
	# to look up the channel again
	def accessLevel(self, channel):
		if channel not in self.channels or channel not in self.ircd.channels or self.nickname not in self.ircd.channels[channel].users:
			return 0
		modes = self.ircd.channels[channel].mode
		max = len(self.ircd.prefix_order)
		for level, mode in enumerate(self.ircd.prefix_order):
			if not modes.has(mode):
				continue
			if self.nickname in modes.get(mode):
				return max - level
		return 0
	
	def hasAccess(self, channel, level):
		if channel not in self.channels or channel not in self.ircd.channels or level not in self.ircd.prefix_order:
			return None
		if self.nickname not in self.ircd.channels[channel].users:
			return False
		access = len(self.ircd.prefix_order) - self.ircd.prefix_order.index(level)
		return self.accessLevel(channel) >= access
	
	def status(self, channel):
		if channel not in self.channels or channel not in self.ircd.channels or self.nickname not in self.ircd.channels[channel].users:
			return ""
		status = ""
		modes = self.ircd.channels[channel].mode
		for mode in self.ircd.prefix_order:
			if not modes.has(mode):
				continue
			if self.nickname in modes.get(mode):
				status += mode
		return status
	
	def modeString(self, user):
		modes = [] # Since we're appending characters to this string, it's more efficient to store the array of characters and join it rather than keep making new strings
		params = []
		for mode, param in self.mode.iteritems():
			modetype = self.ircd.user_mode_type[mode]
			if modetype > 0:
				modes.append(mode)
				if param:
					params.append(self.ircd.user_modes[modetype][mode].showParam(user, param))
		return ("+{} {}".format("".join(modes), " ".join(params)) if params else "".join(modes))
	
	def send_motd(self):
		if "server_motd" in self.ircd.servconfig and self.ircd.servconfig["server_motd"]:
			chunks = chunk_message(self.ircd.servconfig["server_motd"], self.ircd.servconfig["server_motd_line_length"])
			self.sendMessage(irc.RPL_MOTDSTART, ":- {} Message of the day - ".format(self.ircd.servconfig["network_name"]))
			for chunk in chunks:
				line = ":- {{:{!s}}} -".format(self.ircd.servconfig["server_motd_line_length"]).format(chunk) # Dynamically inject the line length as a width argument for the line
				self.sendMessage(irc.RPL_MOTD, line)
			self.sendMessage(irc.RPL_ENDOFMOTD, ":End of MOTD command")
		else:
			self.sendMessage(irc.ERR_NOMOTD, ":MOTD File is missing")
	
	def report_names(self, channel):
		# TODO: check whether user is in channel
		# TODO: check for usermode +i
		# TODO: check for chanmode +ps
		# TODO: Possibly think of a modular way to do those last two
		userlist = []
		"""
		if self.cap["multi-prefix"]:
			for user in cdata.users.itervalues():
				ranks = user.status(cdata.name)
				name = ""
				for p in ranks:
					name += self.ircd.PREFIX_SYMBOLS[p]
				name += user.nickname
				userlist.append(name)
		else:
		"""
		for user in channel.users.itervalues():
			ranks = user.status(channel.name)
			representation = (self.ircd.prefix_symbols[ranks[0]] + user.nickname) if ranks else user.nickname
			newRepresentation = self.listname(channel, user, representation)
			if newRepresentation:
				userlist.append(newRepresentation)
		# Copy of irc.IRC.names
		prefixLength = len(self.ircd.servconfig["server_name"]) + len(irc.RPL_NAMREPLY) + len(cdata.name) + len(self.nickname) + 10 # 10 characters for CRLF, =, : and spaces
		namesLength = 512 - prefixLength # May get messed up with unicode
		lines = chunk_message(" ".join(userlist), namesLength)
		for l in lines:
			self.sendMessage(irc.RPL_NAMREPLY, "=", cdata.name, ":{}".format(l))
		self.sendMessage(irc.RPL_ENDOFNAMES, cdata.name, ":End of /NAMES list")
	
	def listname(self, channel, listingUser, representation):
		for mode in channel.mode.iterkeys():
			representation = self.ircd.channel_modes[self.ircd.channel_mode_type[mode]].namesListEntry(self, channel, listingUser, representation)
			if not representation:
				return representation
		for mode in listingUser.mode.iterkeys():
			representation = self.ircd.user_modes[self.ircd.user_mode_type[mode]].namesListEntry(self, channel, listingUser, representation)
			if not representation:
				return representation
		for modfunc in self.ircd.actions["nameslistentry"]:
			representation = modfunc(self, channel, listingUser, representation)
			if not representation:
				return representation
		return representation
	
	def join(self, channel):
		channel = channel[:64] # Limit channel names to 64 characters
		if channel in self.channels:
			return
		if channel not in self.ircd.channels:
			self.ircd.channels[channel] = IRCChannel(self.ircd, channel)
		cdata = self.ircd.channels[channel]
		hostmask = irc_lower(self.prefix())
		self.channels[cdata.name] = {"status":""}
		cdata.users.add(self)
		for u in cdata.users:
			u.sendMessage("JOIN", to=cdata.name, prefix=self.prefix())
		if cdata.topic is None:
			self.sendMessage(irc.RPL_NOTOPIC, cdata.name, ":No topic is set")
		else:
			self.sendMessage(irc.RPL_TOPIC, cdata.name, ":{}".format(cdata.topic))
			self.sendMessage(irc.RPL_TOPICWHOTIME, cdata.name, cdata.topicSetter, str(epoch(cdata.topicTime)))
		self.report_names(cdata)
		for modfunc in self.ircd.actions["join"]:
			modfunc(cdata, self)
	
	def leave(self, channel):
		cdata = self.ircd.channels[channel]
		del self.channels[cdata.name]
		cdata.users.remove(self) # remove channel user entry
		if not cdata.users:
			del self.ircd.channels[cdata.name] # destroy the empty channel
	
	def nick(self, newNick):
		oldNick = self.nickname
		del self.ircd.users[self.nickname]
		self.ircd.users[newNick] = user
		notify = set()
		notify.add(user)
		for chan in self.channels.iterkeys():
			cdata = self.ircd.channels[chan]
			for cuser in cdata.users:
				notify.add(cuser)
		oldprefix = user.prefix()
		user.nickname = newNick
		for u in notify:
			u.sendMessage("NICK", to=params[0], prefix=oldprefix)
		for modfunc in self.ircd.actions["nick"]:
			modfunc(self, oldNick)