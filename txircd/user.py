# -*- coding: utf-8 -*-

from twisted.internet import reactor
from twisted.python import log
from twisted.words.protocols import irc
from twisted.internet.defer import Deferred
from txircd.channel import IRCChannel
from txircd.utils import irc_lower, parse_duration, VALID_USERNAME, now, epoch, CaseInsensitiveDictionary, chunk_message, strip_colors, has_CTCP, crypt
import fnmatch, socket, hashlib, collections, os, sys, string, re

class IRCUser(object):
	
	def __init__(self, parent):
		# Mask the IP
		ip = parent.transport.getPeer().host
		if ip in parent.factory.client_vhosts:
			hostname = parent.factory.client_vhosts[ip]
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
		geo_data = parent.factory.geo_db.record_by_addr(ip) if parent.factory.geo_db else None
		if not geo_data:
			geo_data = {"latitude":None,"longitude":None,"country_name":None}
		
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
		self.server = parent.factory.server_name
		self.signon = now()
		self.lastactivity = now()
		self.mode = {}
		self.channels = CaseInsensitiveDictionary()
		self.disconnected = Deferred()
		self.registered = 2
		self.metadata = {}
		self.data_cache = {}
		
		if not self.matches_xline("E"):
			xline_match = self.matches_xline("G")
			if xline_match != None:
				self.sendMessage("NOTICE", ":{}".format(self.ircd.client_ban_msg))
				self.sendMessage("ERROR", ":Closing Link: {} [G:Lined: {}]".format(self.prefix(), xline_match), to=None, prefix=None)
				raise ValueError("Banned user")
			xline_match = self.matches_xline("K") # We're still here, so try the next one
			if xline_match:
				self.sendMessage("NOTICE", ":{}".format(self.ircd.client_ban_msg))
				self.sendMessage("ERROR", ":Closing Link: {} [K:Lined: {}]".format(self.prefix(), xline_match), to=None, prefix=None)
				raise ValueError("Banned user")
	
	def register(self):
		if self.nickname in self.ircd.users:
			return
		for action in self.ircd.actions:
			if not action.onRegister(self):
				return self.disconnect(None)
		
		# Add self to user list
		self.ircd.users[self.nickname] = self
		
		# Send all those lovely join messages
		chanmodelist = "".join(["".join(modedict.keys()) for modedict in self.ircd.channel_modes] + "".join(self.ircd.prefixes.keys()))
		chanmodeseplist = ",".join(["".join(modedict.keys()) for modedict in self.ircd.channel_modes])
		prefixes = "({}){}".format(self.ircd.prefix_order, "".join([self.ircd.prefix_symbols[mode] for mode in self.ircd.prefix_order]))
		statuses = "".join([self.ircd.prefix_symbols[mode] for mode in self.ircd.prefix_order])
		self.sendMessage(irc.RPL_WELCOME, ":Welcome to the Internet Relay Network {}".format(self.prefix()))
		self.sendMessage(irc.RPL_YOURHOST, ":Your host is {}, running version {}".format(self.ircd.network_name, self.ircd.version))
		self.sendMessage(irc.RPL_CREATED, ":This server was created {}".format(self.ircd.created))
		self.sendMessage(irc.RPL_MYINFO, self.ircd.network_name, self.ircd.version, self.mode.allowed(), chanmodelist) # usermodes & channel modes
		self.sendMessage(irc.RPL_ISUPPORT, "CASEMAPPING=rfc1459", "CHANMODES={}".format(chanmodeseplist), "CHANNELLEN=64", "CHANTYPES={}".format(self.ircd.channel_prefixes), "MODES=20", "NETWORK={}".format(self.ircd.network_name), "NICKLEN=32", "PREFIX={}".format(prefixes), "STATUSMSG={}".format(statuses), "TOPICLEN=316", ":are supported by this server")
		self.send_motd()
	
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
		if data > self.ircd.client_max_data and not self.mode.has("o"):
			log.msg("Killing user '{}' for flooding".format(self.nickname))
			self.irc_QUIT(None,["Killed for flooding"])
	
	def connectionLost(self, reason):
		self.irc_QUIT(None,["Client connection lost"])
		self.disconnected.callback(None)
	
	def handleCommand(self, command, prefix, params):
		method = getattr(self, "irc_{}".format(command), None)
		if command != "PING" and command != "PONG":
			self.lastactivity = now()
		if command in self.ircd.commands:
			self.ircd.commands[command].onUse(self, params)
		else:
			self.sendMessage(irc.ERR_UNKNOWNCOMMAND, command, ":Unknown command")
	
	def sendMessage(self, command, *parameter_list, **kw):
		if "prefix" not in kw:
			kw["prefix"] = self.ircd.server_name
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
	
	def add_xline(self, linetype, mask, duration, reason):
		if mask in self.ircd.xlines[linetype]:
			self.sendMessage("NOTICE", ":*** Failed to add line for {}: already exists".format(mask))
		else:
			self.ircd.xlines[linetype][mask] = {
				"created": now(),
				"duration": duration,
				"setter": self.nickname,
				"reason": reason
			}
			self.sendMessage("NOTICE", ":*** Added line {} on mask {}".format(linetype, mask))
			match_mask = irc_lower(mask)
			match_list = []
			for user in self.ircd.users.itervalues():
				usermasks = self.ircd.xline_match[linetype]
				for umask in usermasks:
					usermask = umask.format(nick=irc_lower(user.nickname), ident=irc_lower(user.username), host=irc_lower(user.hostname), ip=irc_lower(user.ip))
					if fnmatch.fnmatch(usermask, match_mask):
						match_list.append(user)
						break # break the inner loop to only match each user once
			applymethod = getattr(self, "applyline_{}".format(linetype), None)
			if applymethod is not None:
				applymethod(match_list, reason)
			self.ircd.save_options()
	
	def remove_xline(self, linetype, mask):
		if mask not in self.ircd.xlines[linetype]:
			self.sendMessage("NOTICE", ":*** Failed to remove line for {}: not found in list".format(mask))
		else:
			del self.ircd.xlines[linetype][mask]
			self.sendMessage("NOTICE", ":*** Removed line {} on mask {}".format(linetype, mask))
			removemethod = getattr(self, "removeline_{}".format(linetype), None)
			if removemethod is not None:
				removemethod()
			self.ircd.save_options()
	
	def applyline_G(self, userlist, reason):
		for user in userlist:
			if not user.mode.has("o") and not user.matches_xline("E"):
				user.sendMessage("NOTICE", ":{}".format(self.ircd.client_ban_msg))
				user.irc_QUIT(None, ["G:Lined: {}".format(reason)])
	
	def applyline_K(self, userlist, reason):
		for user in userlist:
			if not user.mode.has("o") and not user.matches_xline("E"):
				user.sendMessage("NOTICE", ":{}".format(self.ircd.client_ban_msg))
				user.irc_QUIT(None, ["K:Lined: {}".format(reason)])
	
	def applyline_Z(self, userlist, reason):
		for user in userlist:
			if not user.mode.has("o") and not user.matches_xline("E"):
				user.sendMessage("NOTICE", ":{}".format(self.ircd.client_ban_msg))
				user.irc_QUIT(None, ["Z:Lined: {}".format(reason)])
	
	def applyline_Q(self, userlist, reason):
		for user in userlist:
			if not user.mode.has("o"):
				user.sendMessage("NOTICE", ":{}".format(self.ircd.client_ban_msg))
				user.irc_QUIT(None, ["Q:Lined: {}".format(reason)])
	
	def removeline_E(self):
		matching_users = { "G": [], "K": [] }
		for user in self.ircd.users.itervalues():
			if user.matches_xline("E"):
				continue # user still matches different e:lines
			for linetype in matching_users.iterkeys():
				if user.matches_xline(linetype):
					matching_users[linetype].append(user)
		if matching_users["G"]:
			self.applyline_G(matching_users["G"], "Exception removed")
		if matching_users["K"]:
			self.applyline_K(matching_users["K"], "Exception removed")
	
	def matches_xline(self, linetype):
		usermasks = self.ircd.xline_match[linetype]
		expired = []
		matched = None
		for mask, linedata in self.ircd.xlines[linetype].iteritems():
			if linedata["duration"] != 0 and epoch(now()) > epoch(linedata["created"]) + linedata["duration"]:
				expired.append(mask)
				continue
			for umask in usermasks:
				usermask = umask.format(nick=irc_lower(self.nickname), ident=irc_lower(self.username), host=irc_lower(self.hostname), ip=irc_lower(self.ip))
				if fnmatch.fnmatch(usermask, mask):
					matched = linedata["reason"]
					break # User only needs matched once.
			if matched:
				break # If there are more expired x:lines, they'll get removed later if necessary
		for mask in expired:
			del self.ircd.xlines[linetype][mask]
		# let expired lines properly clean up
		if expired:
			removemethod = getattr(self, "removeline_{}".format(linetype), None)
			if removemethod is not None:
				removemethod()
			self.ircd.save_options()
		return matched
	
	def send_motd(self):
		if self.ircd.server_motd:
			chunks = chunk_message(self.ircd.server_motd, self.ircd.server_motd_line_length)
			self.sendMessage(irc.RPL_MOTDSTART, ":- {} Message of the day - ".format(self.ircd.network_name))
			for chunk in chunks:
				line = ":- {{:{!s}}} -".format(self.ircd.server_motd_line_length).format(chunk) # Dynamically inject the line length as a width argument for the line
				self.sendMessage(irc.RPL_MOTD, line)
			self.sendMessage(irc.RPL_ENDOFMOTD, ":End of MOTD command")
		else:
			self.sendMessage(irc.ERR_NOMOTD, ":MOTD File is missing")
	
	def report_names(self, channel):
		cdata = self.ircd.channels[channel]
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
		for user in cdata.users.itervalues():
			ranks = user.status(cdata.name)
			if ranks:
				userlist.append(self.ircd.prefix_symbols[ranks[0]] + user.nickname)
			else:
				userlist.append(user.nickname)
		# Copy of irc.IRC.names
		prefixLength = len(self.ircd.server_name) + len(irc.RPL_NAMREPLY) + len(cdata.name) + len(self.nickname) + 10 # 10 characters for CRLF, =, : and spaces
		namesLength = 512 - prefixLength # May get messed up with unicode
		lines = chunk_message(" ".join(userlist), namesLength)
		for l in lines:
			self.sendMessage(irc.RPL_NAMREPLY, "=", cdata.name, ":{}".format(l))
		self.sendMessage(irc.RPL_ENDOFNAMES, cdata.name, ":End of /NAMES list")
	
	def join(self, channel, params, bypass):
		channel = channel[:64] # Limit channel names to 64 characters
		if channel not in self.ircd.channels:
			self.ircd.channels[channel] = IRCChannel(channel)
		cdata = self.ircd.channels[channel]
		hostmask = irc_lower(self.prefix())
		self.channels[cdata.name] = {"status":""}
		cdata.users[self.nickname] = self
		if not bypass:
			allow = False
			again_mod = []
			again_mode = []
			for module in self.ircd.actions:
				permission = module.onJoinCheck(cdata, self, False)
				if permission == "allow":
					allow = True
					break
				if permission == "block":
					if not cdata.users:
						del self.ircd.channels[channel]
						del cdata
					return
				if permission == "again":
					again_mod.append(module)
			if not allow:
				for mode in self.ircd.channel_modes:
					permission = mode.onJoin(cdata, self, params)
					if permission == "allow":
						allow = True
						break
					if permission == "block":
						if not cdata.users:
							del self.ircd.channels[channel]
							del cdata
						return
					if permission == "again":
						again_mode.append(mode)
			if not allow:
				for module in again_mod:
					permission = module.onJoinCheck(cdata, self, True)
					if permission == "allow":
						allow = True
						break
					if permission == "block":
						if not cdata.users:
							del self.ircd.channels[channel]
							del cdata
						return
			if not allow:
				for mode in again_mode:
					permission = mode.onJoin(cdata, self, params)
					if permission == "allow":
						allow = True
						break
					if permission == "block":
						if not cdata.users:
							del self.ircd.channels[channel]
							del cdata
						return
		for u in cdata.users.itervalues():
			u.sendMessage("JOIN", to=cdata.name, prefix=self.prefix())
		if cdata.topic is None:
			self.sendMessage(irc.RPL_NOTOPIC, cdata.name, "No topic is set")
		else:
			self.sendMessage(irc.RPL_TOPIC, cdata.name, ":{}".format(cdata.topic))
			self.sendMessage(irc.RPL_TOPICWHOTIME, cdata.name, cdata.topicSetter, str(epoch(cdata.topicTime)))
		self.report_names(cdata.name)
		for module in self.ircd.actions:
			action.onJoinComplete(cdata, self)
	
	def leave(self, channel):
		cdata = self.ircd.channels[channel]
		if not cdata.log.closed:
			cdata.log.write("[{:02d}:{:02d}:{:02d}] {} left the channel\n".format(now().hour, now().minute, now().second, self.nickname))
		mode = self.status(cdata.name) # Clear modes
		cdata.mode.combine("-{}".format(mode),[self.nickname for _ in mode],cdata.name)
		del self.channels[cdata.name]
		del cdata.users[self.nickname] # remove channel user entry
		if not cdata.users:
			for user in self.ircd.users.itervalues(): # Remove remaining invites and knocks
				if cdata.name in user.invites:
					user.invites.remove(cdata.name)
				if cdata.name in user.knocked:
					user.knocked.remove(cdata.name)
			del self.ircd.channels[cdata.name] # destroy the empty channel
			cdata.log.close()
	
	def part(self, channel, reason):
		if channel not in self.ircd.channels:
			self.sendMessage(irc.ERR_NOSUCHCHANNEL, channel, ":No such channel")
			return
		cdata = self.ircd.channels[channel]
		if self.nickname not in cdata.users:
			self.sendMessage(irc.ERR_NOTONCHANNEL, channel, ":You're not on that channel")
			return
		for u in cdata.users.itervalues():
			u.sendMessage("PART", ":{}".format(reason), to=cdata.name, prefix=self.prefix())
		self.leave(channel)
	
	def msg_cmd(self, cmd, params):
		if not params:
			return self.sendMessage(irc.ERR_NORECIPIENT, ":No recipient given ({})".format(cmd))
		if len(params) < 2 or not params[1]: # Don't allow an empty string to be sent, either
			return self.sendMessage(irc.ERR_NOTEXTTOSEND, ":No text to send")
		targets = set(params[0].split(","))
		message = params[1]
		if "" in targets:
			targets.remove("")
		if not targets:
			return self.sendMessage(irc.ERR_NORECIPIENT, ":No recipient given ({})".format(cmd))
		if self.ircd.server_badwords and not self.mode.has("o"):
			for mask, replacement in self.ircd.server_badwords.iteritems():
				message = re.sub(mask,replacement if replacement else "",message,flags=re.IGNORECASE)
		# If there's no message after substitution, return an error
		if not message:
			return self.sendMessage(irc.ERR_NOTEXTTOSEND, ":No text to send")
		for target in targets:
			if target in self.ircd.users:
				u = self.ircd.users[target]
				u.sendMessage(cmd, ":{}".format(message), prefix=self.prefix())
			elif target in self.ircd.channels or target[1:] in self.ircd.channels:
				min_status = None
				if target[0] not in self.ircd.channel_prefixes:
					symbol_prefix = {v:k for k, v in self.ircd.prefix_symbols.items()}
					if target[0] not in symbol_prefix:
						self.sendMessage(irc.ERR_NOSUCHNICK, target, ":No such nick/channel")
						continue
					min_status = symbol_prefix[target[0]]
					target = target[1:]
				c = self.ircd.channels[target]
				if c.mode.has("n") and self.nickname not in c.users:
					self.sendMessage(irc.ERR_CANNOTSENDTOCHAN, c.name, ":Cannot send to channel (no external messages)")
					continue
				if c.mode.has("m") and not self.hasAccess(c.name, "v"):
					self.sendMessage(irc.ERR_CANNOTSENDTOCHAN, c.name, ":Cannot send to channel (+m)")
					continue
				banned = self.channels[c.name]["banned"] if c.name in self.channels else False
				exempt = self.channels[c.name]["exempt"] if c.name in self.channels else False
				if c.name not in self.channels: # Detect banned/exempt if user isn't actually in the channel
					hostmask = irc_lower(self.prefix())
					if c.mode.has("b"):
						for pattern in c.mode.get("b").iterkeys():
							if fnmatch.fnmatch(hostmask, pattern):
								banned = True
					if c.mode.has("e"):
						for pattern in c.mode.get("e").iterkeys():
							if fnmatch.fnmatch(hostmask, pattern):
								exempt = True
				if banned and not (exempt or self.mode.has("o") or self.hasAccess(c.name, "v")):
					self.sendMessage(irc.ERR_CANNOTSENDTOCHAN, c.name, ":Cannot send to channel (banned)")
					continue
				if c.mode.has("C") and (not self.hasAccess(c.name, "h") or "C" not in self.ircd.channel_exempt_chanops) and has_CTCP(message):
					self.sendMessage(irc.ERR_NOSERVICEHOST, c.name, ":Can't send CTCP to channel (+C set)") # perhaps a new name?
					continue
				if c.mode.has("S") and (not self.hasAccess(c.name, "h") or "S" not in self.ircd.channel_exempt_chanops):
					message = strip_colors(message)
				if c.mode.has("f") and (not self.hasAccess(c.name, "h") or "f" not in self.ircd.channel_exempt_chanops):
					nowtime = epoch(now())
					self.channels[c.name]["msg_rate"].append(nowtime)
					lines, seconds = c.mode.get("f").split(":")
					lines = int(lines)
					seconds = int(seconds)
					while self.channels[c.name]["msg_rate"] and self.channels[c.name]["msg_rate"][0] < nowtime - seconds:
						self.channels[c.name]["msg_rate"].pop(0)
					if len(self.channels[c.name]["msg_rate"]) > lines:
						for u in c.users.itervalues():
							u.sendMessage("KICK", self.nickname, ":Channel flood triggered ({} lines in {} seconds)".format(lines, seconds), to=c.name)
						self.leave(c.name)
						continue
				# If there's no message after all of this, return an error
				if not message:
					return self.sendMessage(irc.ERR_NOTEXTTOSEND, ":No text to send")
				# store the destination rather than generating it for everyone in the channel; show the entire destination of the message to recipients
				dest = "{}{}".format(self.ircd.prefix_symbols[min_status] if min_status else "", c.name)
				lines = chunk_message(message, 505-len(cmd)-len(dest)-len(self.prefix())) # Split the line up before sending it
				msgto = set()
				for u in c.users.itervalues():
					if u.nickname is not self.nickname and (not min_status or u.hasAccess(c.name, min_status)):
						msgto.add(u)
				for u in msgto:
					for l in lines:
						u.sendMessage(cmd, ":{}".format(l), to=dest, prefix=self.prefix())
				if not c.log.closed:
					c.log.write("[{:02d}:{:02d}:{:02d}] {border_s}{nick}{border_e}: {message}\n".format(now().hour, now().minute, now().second, nick=self.nickname, message=message, border_s=("-" if cmd == "NOTICE" else "<"), border_e=("-" if cmd == "NOTICE" else ">")))
			else:
				self.sendMessage(irc.ERR_NOSUCHNICK, target, ":No such nick/channel")
	
	def add_to_whowas(self):
		if self.nickname not in self.ircd.whowas:
			self.ircd.whowas[self.nickname] = []
		self.ircd.whowas[self.nickname].append({
			"nickname": self.nickname,
			"username": self.username,
			"realname": self.realname,
			"hostname": self.hostname,
			"ip": self.ip,
			"time": now()
		})
		self.ircd.whowas[self.nickname] = self.ircd.whowas[self.nickname][-self.ircd.client_whowas_limit:] # Remove old entries
	
	def stats_xline_list(self, xline_type, xline_numeric):
		for mask, linedata in self.ircd.xlines[xline_type].iteritems():
			self.sendMessage(xline_numeric, ":{} {} {} {} :{}".format(mask, epoch(linedata["created"]), linedata["duration"], linedata["setter"], linedata["reason"]))
	
	def stats_o(self):
		for user in self.ircd.users.itervalues():
			if user.mode.has("o"):
				self.sendMessage(irc.RPL_STATSOPERS, ":{} ({}@{}) Idle: {} secs".format(user.nickname, user.username, user.hostname, epoch(now()) - epoch(user.lastactivity)))
	
	def stats_p(self):
		if isinstance(self.ircd.server_port_tcp, collections.Sequence):
			for port in self.ircd.server_port_tcp:
				self.sendMessage(irc.RPL_STATSPORTS, ":{} (clients, plaintext)".format(port))
		else:
			self.sendMessage(irc.RPL_STATSPORTS, ":{} (clients, plaintext)".format(self.ircd.server_port_tcp))
		if isinstance(self.ircd.server_port_ssl, collections.Sequence):
			for port in self.ircd.server_port_ssl:
				self.sendMessage(irc.RPL_STATSPORTS, ":{} (clients, ssl)".format(port))
		else:
			self.sendMessage(irc.RPL_STATSPORTS, ":{} (clients, ssl)".format(self.ircd.server_port_ssl))
		if isinstance(self.ircd.server_port_web, collections.Sequence):
			for port in self.ircd.server_port_web:
				self.sendMessage(irc.RPL_STATSPORTS, ":{} (clients, web)".format(port))
		else:
			self.sendMessage(irc.RPL_STATSPORTS, ":{} (clients, web)".format(self.ircd.server_port_web))
		# Add server ports here when we get s2s
	
	def stats_u(self):
		uptime = now() - self.ircd.created
		self.sendMessage(irc.RPL_STATSUPTIME, ":Server up {}".format(uptime if uptime.days > 0 else "0 days, {}".format(uptime)))
	
	def stats_G(self):
		self.stats_xline_list("G", irc.RPL_STATSGLINE)
	
	def stats_K(self):
		self.stats_xline_list("K", irc.RPL_STATSKLINE)
	
	def stats_Z(self):
		self.stats_xline_list("Z", irc.RPL_STATSZLINE)
	
	def stats_E(self):
		self.stats_xline_list("E", irc.RPL_STATSELINE)
	
	def stats_Q(self):
		self.stats_xline_list("Q", irc.RPL_STATSQLINE)
	
	def stats_S(self):
		self.stats_xline_list("SHUN", irc.RPL_STATSSHUN)
	
	def stats_B(self):
		if self.ircd.server_badwords:
			for mask, replacement in self.ircd.server_badwords.iteritems():
				self.sendMessage(irc.RPL_STATS, "B", ":{} {}".format(mask, replacement))
	
	#======================
	#== Protocol Methods ==
	#======================
	def irc_PING(self, prefix, params):
		if params:
			self.sendMessage("PONG", ":{}".format(params[0]), to=self.ircd.server_name)
		else:
			self.sendMessage(irc.ERR_NOORIGIN, ":No origin specified")
	
	def irc_PONG(self, prefix, params):
		pass
	
	def irc_OPER(self, prefix, params):
		if len(params) < 2:
			self.sendMessage(irc.ERR_NEEDMOREPARAMS, "OPER", ":Not enough parameters")
		elif self.ip not in self.ircd.oper_ips:
			self.sendMessage(irc.ERR_NOOPERHOST, ":No O-lines for your host")
		elif params[0] not in self.ircd.oper_logins or self.ircd.oper_logins[params[0]] != crypt(params[1],self.ircd.oper_logins[params[0]]):
			self.sendMessage(irc.ERR_PASSWDMISMATCH, ":Password incorrect")
		else:
			self.mode.modes["o"] = True
			self.sendMessage(irc.RPL_YOUREOPER, ":You are now an IRC operator")
	
	def irc_QUIT(self, prefix, params):
		if not self.nickname in self.ircd.users:
			return # Can't quit twice
		self.add_to_whowas()
		reason = params[0] if params else "Client exited"
		quit_to = set()
		for c in self.channels.keys():
			for u in self.ircd.channels[c].users.itervalues():
				quit_to.add(u)
			self.leave(c)
		for user in quit_to:
			user.sendMessage("QUIT", ":{}".format(reason), to=None, prefix=self.prefix())
		del self.ircd.users[self.nickname]
		self.sendMessage("ERROR",":Closing Link: {} [{}]".format(self.prefix(), reason), to=None, prefix=None)
		self.socket.transport.loseConnection()

	def irc_JOIN(self, prefix, params):
		if not params:
			self.sendMessage(irc.ERR_NEEDMOREPARAMS, "JOIN", ":Not enough parameters")
		elif params[0] == "0":
			for c in self.channels.keys():
				self.part(c, "Parting all channels")
		else:
			channels = params[0].split(",")
			keys = params[1].split(",") if len(params) > 1 else []
			for c in channels:
				if not self.mode.has("o"):
					c_lower = irc_lower(c) # Do this once now instead of a bunch later
					whitelist = False
					for entry in self.ircd.server_allowchans:
						if fnmatch.fnmatch(c_lower, entry):
							whitelist = True
							break
					if not whitelist:
						blacklist = False
						for entry in self.ircd.server_denychans:
							if fnmatch.fnmatch(c_lower, entry):
								blacklist = True
								break
						if blacklist:
							self.sendMessage(irc.ERR_CHANNOTALLOWED, c, ":Channel {} is forbidden.".format(c))
							continue # process the rest of the channel list
				if c in self.channels:
					continue # don't join it twice
				k = keys.pop(0) if keys else None
				self.join(c,k)

	def irc_PART(self, prefix, params):
		if not params:
			self.sendMessage(irc.ERR_NEEDMOREPARAMS, "PART", ":Not enough parameters")
		channels = params[0].split(",")
		reason = params[1] if len(params) > 1 else self.nickname
		for c in channels:
			self.part(c, reason)
	
	def irc_MODE(self, prefix, params):
		if not params:
			self.sendMessage(irc.ERR_NEEDMOREPARAMS, "MODE", ":Not enough parameters")
		elif params[0] in self.ircd.users:
			self.irc_MODE_user(params)
		elif params[0] in self.ircd.channels:
			self.irc_MODE_channel(params)
		else:
			self.sendMessage(irc.ERR_NOSUCHNICK, params[0], ":No such nick/channel")

	def irc_MODE_user(self, params):
		user = self.ircd.users[params[0]]
		if user.nickname != self.nickname and not self.mode.has("o"): # Not self and not an OPER
			self.sendMessage(irc.ERR_NEEDMOREPARAMS, ":Can't {} for other users".format("view modes" if len(params) == 1 else "change mode"))
		else:
			if len(params) == 1:
				self.sendMessage(irc.RPL_UMODEIS, user.mode, to=user.nickname)
			else:
				response, bad, forbidden = user.mode.combine(params[1], params[2:], self.nickname)
				if response:
					self.sendMessage("MODE", response, to=user.nickname, prefix=self.prefix())
					if user.nickname != self.nickname: # Also send the mode change to the user if an oper is changing it
						user.sendMessage("MODE", response, prefix=self.prefix())
				for mode in bad:
					self.sendMessage(irc.ERR_UMODEUNKNOWNFLAG, mode, ":is unknown mode char to me", to=user.nickname)
				for mode in forbidden:
					self.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission Denied - Only operators may set user mode {}".format(mode), to=user.nickname)

	def irc_MODE_channel(self, params):
		if len(params) == 1:
			self.irc_MODE_channel_show(params)
		elif len(params) == 2 and ("b" in params[1] or "e" in params[1] or "I" in params[1]):
			self.irc_MODE_channel_bans(params)
		elif self.hasAccess(params[0], "h") or self.mode.has("o"):
			self.irc_MODE_channel_change(params)
		else:
			self.sendMessage(irc.ERR_CHANOPRIVSNEEDED, params[0], ":You must have channel halfop access or above to set channel modes")

	def irc_MODE_channel_show(self, params):
		cdata = self.ircd.channels[params[0]]
		self.sendMessage(irc.RPL_CHANNELMODEIS, cdata.name, "+{!s}".format(cdata.mode))
		self.sendMessage(irc.RPL_CREATIONTIME, cdata.name, str(epoch(cdata.created)))
	
	def irc_MODE_channel_change(self, params):
		cdata = self.ircd.channels[params.pop(0)]
		modes, bad, forbidden = cdata.mode.combine(params[0], params[1:], self.nickname)
		for mode in bad:
			self.sendMessage(irc.ERR_UNKNOWNMODE, mode, ":is unknown mode char to me")
		for mode in forbidden:
			self.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - only operators may set mode {}".format(mode))
		if modes:
			if not cdata.log.closed:
				cdata.log.write("[{:02d}:{:02d}:{:02d}] {} set modes {}\n".format(now().hour, now().minute, now().second, self.nickname, modes))
			for u in cdata.users.itervalues():
				u.sendMessage("MODE", modes, to=cdata.name, prefix=self.prefix())

	def irc_MODE_channel_bans(self, params):
		cdata = self.ircd.channels[params[0]]
		if "b" in params[1]:
			if cdata.mode.has("b"):
				for banmask, settertime in cdata.mode.get("b").iteritems():
					self.sendMessage(irc.RPL_BANLIST, cdata.name, banmask, settertime[0], str(epoch(settertime[1])))
			self.sendMessage(irc.RPL_ENDOFBANLIST, cdata.name, ":End of channel ban list")
		if "e" in params[1]:
			if cdata.mode.has("e"):
				for exceptmask, settertime in cdata.mode.get("e").iteritems():
					self.sendMessage(irc.RPL_EXCEPTLIST, cdata.name, exceptmask, settertime[0], str(epoch(settertime[1])))
			self.sendMessage(irc.RPL_ENDOFEXCEPTLIST, cdata.name, ":End of channel exception list")
		if "I" in params[1]:
			if cdata.mode.has("I"):
				for invexmask, settertime in cdata.mode.get("I").iteritems():
					self.sendMessage(irc.RPL_INVITELIST, cdata.name, invexmask, settertime[0], str(epoch(settertime[1])))
			self.sendMessage(irc.RPL_ENDOFINVITELIST, cdata.name, ":End of channel invite exception list")

	def irc_TOPIC(self, prefix, params):
		if not params:
			self.sendMessage(irc.ERR_NEEDMOREPARAMS, "TOPIC", ":Not enough parameters")
			return
		if params[0] not in self.ircd.channels:
			self.sendMessage(irc.ERR_NOSUCHCHANNEL, params[0], ":No such channel")
			return
		cdata = self.ircd.channels[params[0]]
		if len(params) == 1:
			if cdata.topic["message"] is None:
				self.sendMessage(irc.RPL_NOTOPIC, cdata.name, "No topic is set")
			else:
				self.sendMessage(irc.RPL_TOPIC, cdata.name, ":{}".format(cdata.topic["message"]))
				self.sendMessage(irc.RPL_TOPICWHOTIME, cdata.name, cdata.topic["author"], str(epoch(cdata.topic["created"])))
		else:
			if self.nickname not in cdata.users:
				self.sendMessage(irc.ERR_NOTONCHANNEL, cdata.name, ":You're not in that channel")
			elif not cdata.mode.has("t") or self.hasAccess(params[0],"h") or self.mode.has("o"):
				# If the channel is +t and the user has a rank that is halfop or higher, allow the topic change
				cdata.topic["message"] = params[1][:316] # With the longest possible hostmask and a channel name length of 64, the maximum safe topic length is 316
				cdata.topic["author"] = self.nickname
				cdata.topic["created"] = now()
				for u in cdata.users.itervalues():
					u.sendMessage("TOPIC", ":{}".format(cdata.topic["message"]), to=cdata.name, prefix=self.prefix())
				if not cdata.log.closed:
					cdata.log.write("[{:02d}:{:02d}:{:02d}] {} changed the topic to {}\n".format(now().hour, now().minute, now().second, self.nickname, params[1]))
			else:
				self.sendMessage(irc.ERR_CHANOPRIVSNEEDED, cdata.name, ":You do not have access to change the topic on this channel")
	
	def irc_KICK(self, prefix, params):
		if not params or len(params) < 2:
			self.sendMessage(irc.ERR_NEEDMOREPARAMS, "KICK", ":Not enough parameters")
			return
		if len(params) == 2:
			params.append(self.nickname) # default reason used on many IRCds
		if params[0] not in self.ircd.channels:
			self.sendMessage(irc.ERR_NOSUCHCHANNEL, params[0], ":No such channel")
			return
		if params[1] not in self.ircd.users:
			self.sendMessage(irc.ERR_NOSUCHNICK, params[1], ":No such nick")
			return
		cdata = self.ircd.channels[params[0]]
		udata = self.ircd.users[params[1]]
		if self.nickname not in cdata.users and not self.mode.has("o"):
			self.sendMessage(irc.ERR_NOTONCHANNEL, cdata["names"], ":You're not on that channel!")
			return
		if udata.nickname not in cdata.users:
			self.sendMessage(irc.ERR_USERNOTINCHANNEL, udata.nickname, cdata.name, ":They are not on that channel")
			return
		if (not self.hasAccess(params[0], "h") or not self.accessLevel(params[0]) > udata.accessLevel(params[0])) and not self.mode.has("o"):
			self.sendMessage(irc.ERR_CHANOPRIVSNEEDED, cdata.name, ":You must be a channel half-operator")
			return
		for u in cdata.users.itervalues():
			u.sendMessage("KICK", udata.nickname, ":{}".format(params[2]), to=cdata.name, prefix=self.prefix())
		udata.leave(params[0])

	def irc_WHO(self, prefix, params):
		# When server-to-server is implemented, replace self.ircd.hostname in the replies with a way to get the (real or masked) server name for each user
		# We don't need to worry about fixing the hopcount since most IRCds always send 0
		if not params:
			for u in self.ircd.users.itervalues():
				if u.mode.has("i"):
					continue
				common_channel = False
				for c in self.channels.iterkeys():
					if c in u.channels:
						common_channel = True
						break
				if not common_channel:
					self.sendMessage(irc.RPL_WHOREPLY, "*", u.username, u.hostname, self.ircd.server_name, u.nickname, "{}{}".format("G" if u.mode.has("a") else "H", "*" if u.mode.has("o") else ""), ":0 {}".format(u.realname))
			self.sendMessage(irc.RPL_ENDOFWHO, self.nickname, "*", ":End of /WHO list.")
		else:
			filters = ""
			if len(params) >= 2:
				filters = params[1]
			if params[0] in self.ircd.channels:
				cdata = self.ircd.channels[params[0]]
				in_channel = cdata.name in self.channels # cache this value instead of searching self.channels every iteration
				for user in cdata.users.itervalues():
					if (in_channel or not user.mode.has("i")) and ("o" not in filters or user.mode.has("o")):
						self.sendMessage(irc.RPL_WHOREPLY, cdata.name, user.username, user.hostname, self.ircd.server_name, user.nickname, "{}{}{}".format("G" if user.mode.has("a") else "H", "*" if user.mode.has("o") else "", self.ircd.prefix_symbols[self.ircd.prefix_order[len(self.ircd.prefix_order) - user.accessLevel(cdata.name)]] if user.accessLevel(cdata.name) > 0 else ""), ":0 {}".format(user.realname))
				self.sendMessage(irc.RPL_ENDOFWHO, cdata.name, ":End of /WHO list.")
			elif params[0][0] in self.ircd.channel_prefixes:
				self.sendMessage(irc.RPL_ENDOFWHO, params[0], ":End of /WHO list.")
			else:
				for user in self.ircd.users.itervalues():
					if not user.mode.has("i") and (fnmatch.fnmatch(irc_lower(user.nickname), irc_lower(params[0])) or fnmatch.fnmatch(irc_lower(user.hostname), irc_lower(params[0]))):
						self.sendMessage(irc.RPL_WHOREPLY, params[0], user.username, user.hostname, self.ircd.server_name, user.nickname, "{}{}".format("G" if user.mode.has("a") else "H", "*" if user.mode.has("o") else ""), ":0 {}".format(user.realname))
				self.sendMessage(irc.RPL_ENDOFWHO, params[0], ":End of /WHO list.")
				# params[0] is used here for the target so that the original glob pattern is returned
	
	def irc_WHOIS(self, prefix, params):
		if not params:
			self.sendMessage(irc.ERR_NONICKNAMEGIVEN, ":No nickname given")
			return
		users = params[0].split(",")
		for uname in users:
			if uname not in self.ircd.users:
				self.sendMessage(irc.ERR_NOSUCHNICK, uname, ":No such nick/channel")
				self.sendMessage(irc.RPL_ENDOFWHOIS, "*", ":End of /WHOIS list.")
				continue
			udata = self.ircd.users[uname]
			self.sendMessage(irc.RPL_WHOISUSER, udata.nickname, udata.username, udata.ip if self.mode.has("o") else udata.hostname, "*", ":{}".format(udata.realname))
			if udata.channels:
				chanlist = []
				for channel in udata.channels.iterkeys():
					cdata = self.ircd.channels[channel]
					if cdata.name in self.channels or (not cdata.mode.has("s") and not cdata.mode.has("p")):
						level = udata.accessLevel(cdata.name)
						if level == 0:
							chanlist.append(cdata.name)
						else:
							symbol = self.ircd.prefix_symbols[self.ircd.prefix_order[len(self.ircd.prefix_order) - level]]
							chanlist.append("{}{}".format(symbol, cdata.name))
				if chanlist:
					self.sendMessage(irc.RPL_WHOISCHANNELS, udata.nickname, ":{}".format(" ".join(chanlist)))
			self.sendMessage(irc.RPL_WHOISSERVER, udata.nickname, self.ircd.server_name, ":{}".format(self.ircd.network_name))
			if udata.mode.has("a"):
				self.sendMessage(irc.RPL_AWAY, udata.nickname, ":{}".format(udata.mode.get("a")))
			if udata.mode.has("o"):
				self.sendMessage(irc.RPL_WHOISOPERATOR, udata.nickname, ":is an IRC operator")
			if udata.account:
				self.sendMessage(irc.RPL_WHOISACCOUNT, udata.nickname, udata.account, ":is logged in as")
			if udata.socket.secure:
				self.sendMessage(irc.RPL_WHOISSECURE, udata.nickname, ":is using a secure connection")
			self.sendMessage(irc.RPL_WHOISIDLE, udata.nickname, str(epoch(now()) - epoch(udata.lastactivity)), str(epoch(udata.signon)), ":seconds idle, signon time")
			self.sendMessage(irc.RPL_ENDOFWHOIS, udata.nickname, ":End of /WHOIS list.")
	
	def irc_WHOWAS(self, prefix, params):
		if not params:
			self.sendMessage(irc.ERR_NONICKNAMEGIVEN, self.nickname, ":No nickname given")
			return
		users = params[0].split(",")
		for uname in users:
			if uname not in self.ircd.whowas:
				self.sendMessage(irc.ERR_WASNOSUCHNICK, self.nickname, uname, ":No such nick")
				self.sendMessage(irc.RPL_ENDOFWHOWAS, self.nickname, "*", ":End of /WHOWAS list.")
				continue
			history = self.ircd.whowas[uname]
			for u in history:
				self.sendMessage(irc.RPL_WHOISUSER, u["nickname"], u["username"], u["ip"] if self.mode.has("o") else u["hostname"], "*", ":{}".format(u["realname"]))
				self.sendMessage(irc.RPL_WHOISSERVER, u["nickname"], self.ircd.server_name, ":{}".format(u["time"]))
			self.sendMessage(irc.RPL_ENDOFWHOWAS, uname, ":End of /WHOWAS list.")
			
	def irc_PRIVMSG(self, prefix, params):
		self.msg_cmd("PRIVMSG", params)
	
	def irc_NOTICE(self, prefix, params):
		self.msg_cmd("NOTICE", params)
	
	def irc_NAMES(self, prefix, params):
		#params[0] = channel list, params[1] = target server. We ignore the target
		channels = self.channels.keys()
		if params:
			channels = params[0].split(",")
		channels = filter(lambda x: x in self.channels and x in self.ircd.channels, channels)
		for c in channels:
			self.report_names(c)
	
	def irc_LIST(self, prefix, params):
		#params[0] = channel list, params[1] = target server. We ignore the target
		channels = []
		if params:
			channels = filter(lambda x: x in self.ircd.channels, params[0].split(","))
		if not channels:
			channels = self.ircd.channels.keys()
		for c in channels:
			cdata = self.ircd.channels[c]
			if self.nickname in cdata.users or (not cdata.mode.has("s") and not cdata.mode.has("p")):
				self.sendMessage(irc.RPL_LIST, cdata.name, str(len(cdata.users)), ":{}".format(cdata.topic["message"]))
			elif cdata.mode.has("p") and not cdata.mode.has("s"):
				self.sendMessage(irc.RPL_LIST, "*", str(len(cdata.users)), ":")
		self.sendMessage(irc.RPL_LISTEND, ":End of /LIST")
	
	def irc_INVITE(self, prefix, params):
		if len(params) < 2:
			self.sendMessage(irc.ERR_NEEDMOREPARAMS, "INVITE", ":Not enough parameters")
		elif params[0] not in self.ircd.users:
			self.sendMessage(irc.ERR_NOSUCHNICK, params[0], ":No such nick/channel")
		elif params[1] not in self.ircd.channels:
			self.sendMessage(irc.ERR_NOSUCHNICK, params[1], ":No such nick/channel")
		
		udata = self.ircd.users[params[0]]
		cdata = self.ircd.channels[params[1]]
		if cdata.name in udata.channels:
			self.sendMessage(irc.ERR_USERONCHANNEL, udata.nickname, cdata.name, ":is already on channel")
		elif cdata.name not in self.channels:
			self.sendMessage(irc.ERR_NOTONCHANNEL, cdata.name, ":You're not on that channel")
		elif cdata.mode.has("i") and not self.hasAccess(cdata.name, "h"):
			self.sendMessage(irc.ERR_CHANOPRIVSNEEDED, cdata.name, ":You're not channel operator")
		elif udata.mode.has("a"):
			self.sendMessage(irc.RPL_AWAY, udata.nickname, ":{}".format(udata.mode.get("a")))
		else:
			self.sendMessage(irc.RPL_INVITING, udata.nickname, cdata.name)
			udata.sendMessage("INVITE", cdata.name, to=udata.nickname, prefix=self.prefix())
			udata.invites.append(cdata.name)
	
	def irc_KNOCK(self, prefix, params):
		if not params or len(params) < 2:
			self.sendMessage(irc.ERR_NEEDMOREPARAMS, "KNOCK", ":Not enough parameters")
			return
		if params[0] not in self.ircd.channels:
			self.sendMessage(irc.ERR_NOSUCHCHANNEL, params[0], ":No such channel")
			return
		cdata = self.ircd.channels[params[0]]
		if self.nickname in cdata.users:
			self.sendMessage(irc.ERR_KNOCKONCHAN, cdata.name, ":You are already on that channel.")
			return
		if not cdata.mode.has("i"):
			self.sendMessage(irc.ERR_CHANOPEN, cdata.name, ":Channel is open.")
			return
		if cdata.name in self.knocked:
			self.sendMessage(irc.ERR_TOOMANYKNOCK, cdata.name, ":Too many KNOCKs (user).")
			return
		if cdata.mode.has("K"):
			self.sendMessage(irc.ERR_TOOMANYKNOCK, cdata.name, ":Channel is +K")
			return
		self.knocked.append(cdata.name)
		self.sendMessage(irc.RPL_KNOCKDLVR, cdata.name, ":Your KNOCK has been delivered.")
		for user in cdata.users.itervalues():
			if user.hasAccess(cdata.name, "h"):
				user.sendMessage(irc.RPL_KNOCK, cdata.name, self.prefix(), ":{}".format(" ".join(params[1:])))
	
	def irc_MOTD(self, prefix, params):
		self.send_motd()
	
	def irc_AWAY(self, prefix, params):
		if not params:
			if self.mode.has("a"):
				del self.mode.modes["a"]
			self.sendMessage(irc.RPL_UNAWAY, ":You are no longer marked as being away")
		else:
			self.mode.modes["a"] = params[0]
			self.sendMessage(irc.RPL_NOWAWAY, ":You have been marked as being away")
	
	def irc_KILL(self, prefix, params):
		if not self.mode.has("o"):
			self.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission Denied - You do not have the required operator privileges")
			return
		if not params or len(params) < 2:
			self.sendMessage(irc.ERR_NEEDMOREPARAMS, "KILL", ":Not enough parameters.")
		elif params[0] not in self.ircd.users:
			self.sendMessage(irc.ERR_NOSUCHNICK, params[0], ":No such nick")
		else:
			udata = self.ircd.users[params[0]]
			if udata.mode.has("o"):
				self.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - You cannot KILL another oper")
			else:
				udata.sendMessage("KILL", ":{} ({})".format(self.nickname, params[1]))
				udata.irc_QUIT(None, ["Killed by {} ({})".format(self.nickname, params[1])])
	
	def irc_GLINE(self, prefix, params):
		if not self.mode.has("o"):
			self.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - You do not have the required operator privileges")
			return
		if not params or (params[0][0] != "-" and len(params) < 3):
			self.sendMessage(irc.ERR_NEEDMOREPARAMS, "GLINE", ":Not enough parameters")
			return
		if params[0][0] == "-":
			banmask = irc_lower(params[0][1:])
			if "@" not in banmask:
				banmask = "*@{}".format(banmask)
			self.remove_xline("G", banmask)
		else:
			banmask = irc_lower(params[0])
			if banmask in self.ircd.users: # banmask is a nick of an active user; user@host isn't a valid nick so no worries there
				user = self.ircd.users[banmask]
				banmask = irc_lower("{}@{}".format(user.username, user.hostname))
			elif "@" not in banmask:
				banmask = "*@{}".format(banmask)
			self.add_xline("G", banmask, parse_duration(params[1]), " ".join(params[2:]))
	
	def irc_KLINE(self, prefix, params):
		if not self.mode.has("o"):
			self.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - You do not have the required operator privileges")
			return
		if not params or (params[0][0] != "-" and len(params) < 3):
			self.sendMessage(irc.ERR_NEEDMOREPARAMS, "KLINE", ":Not enough parameters")
			return
		if params[0][0] == "-":
			banmask = irc_lower(params[0][1:])
			if "@" not in banmask:
				banmask = "*@{}".format(banmask)
			self.remove_xline("K", banmask)
		else:
			banmask = irc_lower(params[0])
			if banmask in self.ircd.users: # banmask is a nick of an active user; user@host isn't a valid nick so no worries there
				user = self.ircd.users[banmask]
				banmask = irc_lower("{}@{}".format(user.username, user.hostname))
			elif "@" not in banmask:
				banmask = "*@{}".format(banmask)
			self.add_xline("K", banmask, parse_duration(params[1]), " ".join(params[2:]))
	
	def irc_ZLINE(self, prefix, params):
		if not self.mode.has("o"):
			self.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - You do not have the required operator privileges")
			return
		if not params or (params[0][0] != "-" and len(params) < 3):
			self.sendMessage(irc.ERR_NEEDMOREPARAMS, "ZLINE", ":Not enough parameters")
			return
		if params[0][0] == "-":
			self.remove_xline("Z", params[0][1:])
		else:
			banip = params[0]
			if banip in self.ircd.users:
				banip = self.ircd.users[banip].ip
			self.add_xline("Z", banip, parse_duration(params[1]), " ".join(params[2:]))
	
	def irc_ELINE(self, prefix, params):
		if not self.mode.has("o"):
			self.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - You do not have the required operator privileges")
			return
		if not params or (params[0][0] != "-" and len(params) < 3):
			self.sendMessage(irc.ERR_NEEDMOREPARAMS, "ELINE", ":Not enough parameters")
			return
		if params[0][0] == "-":
			banmask = irc_lower(params[0][1:])
			if "@" not in banmask:
				banmask = "*@{}".format(banmask)
			self.remove_xline("E", params[0][1:])
		else:
			banmask = irc_lower(params[0])
			if banmask in self.ircd.users:
				user = self.ircd.users[banmask]
				banmask = irc_lower("{}@{}".format(user.username, user.hostname))
			elif "@" not in banmask:
				banmask = "*@{}".format(banmask)
			self.add_xline("E", banmask, parse_duration(params[1]), " ".join(params[2:]))
	
	def irc_QLINE(self, prefix, params):
		if not self.mode.has("o"):
			self.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - You do not have the required operator privileges")
			return
		if not params or (params[0][0] != "-" and len(params) < 3):
			self.sendMessage(irc.ERR_NEEDMOREPARAMS, "QLINE", ":Not enough parameters")
			return
		if params[0][0] == "-":
			self.remove_xline("Q", params[0][1:])
		else:
			nickmask = irc_lower(params[0])
			if VALID_USERNAME.match(nickmask.replace("*","").replace("?","a")):
				self.add_xline("Q", nickmask, parse_duration(params[1]), " ".join(params[2:]))
			else:
				self.sendMessage("NOTICE", ":*** Could not set Q:Line: invalid nickmask")
	
	def irc_SHUN(self, prefix, params):
		if not self.mode.has("o"):
			self.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - You do not have the required operator privileges")
			return
		if not params or (params[0][0] != "-" and len(params) < 3):
			self.sendMessage(irc.ERR_NEEDMOREPARAMS, "SHUN", ":Not enough parameters")
			return
		if params[0][0] == "-":
			banmask = irc_lower(params[0][1:])
			if "@" not in banmask:
				banmask = "*@{}".format(banmask)
			self.remove_xline("SHUN", banmask)
		else:
			banmask = irc_lower(params[0])
			if banmask in self.ircd.users:
				user = self.ircd.users[banmask]
				banmask = irc_lower("{}@{}".format(user.username, user.hostname))
			elif "@" not in banmask:
				banmask = "*@{}".format(banmask)
			self.add_xline("SHUN", banmask, parse_duration(params[1]), " ".join(params[2:]))
	
	def irc_VERSION(self, prefix, params):
		self.sendMessage(irc.RPL_VERSION, self.ircd.version, self.ircd.server_name, ":txircd")
	
	def irc_TIME(self, prefix, params):
		self.sendMessage(irc.RPL_TIME, self.ircd.server_name, ":{}".format(now()))
	
	def irc_ADMIN(self, prefix, params):
		self.sendMessage(irc.RPL_ADMINME, self.ircd.server_name, ":Administrative info")
		self.sendMessage(irc.RPL_ADMINLOC1, ":{}".format(self.ircd.admin_info_server))
		self.sendMessage(irc.RPL_ADMINLOC2, ":{}".format(self.ircd.admin_info_organization))
		self.sendMessage(irc.RPL_ADMINEMAIL, ":{}".format(self.ircd.admin_info_person))
	
	def irc_INFO(self, prefix, params):
		self.sendMessage(irc.RPL_INFO, ":txircd")
		self.sendMessage(irc.RPL_ENDOFINFO, ":End of INFO list")
	
	def irc_REHASH(self, prefix, params):
		if not self.mode.has("o"):
			self.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - You do not have the required operator privileges")
			return
		self.ircd.rehash()
		self.sendMessage(irc.RPL_REHASHING, self.ircd.config, ":Rehashing")
	
	def irc_DIE(self, prefix, params):
		if not self.mode.has("o"):
			self.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - You do not have the required operator privileges")
			return
		if not self.ircd.oper_allow_die:
			self.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - Server does not allow use of DIE command")
			return
		reactor.stop()
	
	def irc_RESTART(self, prefix, params):
		if not self.mode.has("o"):
			self.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - You do not have the required operator privileges")
			return
		if not self.ircd.oper_allow_die:
			self.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - Server does not allow use of RESTART command")
			return
		def restart():
			os.execl(sys.executable, sys.executable, *sys.argv)
		reactor.addSystemEventTrigger("after", "shutdown", restart)
		reactor.stop()
	
	def irc_USERHOST(self, prefix, params):
		if not params:
			self.sendMessage(irc.ERR_NEEDMOREPARAMS, "USERHOST", ":Not enough parameters")
			return
		users = params[:5]
		reply_list = []
		for u in users:
			if u in self.ircd.users:
				udata = self.ircd.users[u]
				nick = udata.nickname
				oper = "*" if udata.mode.has("o") else ""
				away = "-" if udata.mode.has("a") else "+"
				host = "{}@{}".format(udata.username, udata.hostname)
				reply_list.append("{}{}={}{}".format(nick, oper, away, host))
		self.sendMessage(irc.RPL_USERHOST, ":{}".format(" ".join(reply_list)))
	
	def irc_ISON(self, prefix, params):
		if not params:
			self.sendMessage(irc.ERR_NEEDMOREPARAMS, "ISON", ":Not enough parameters")
			return
		reply = []
		for user in params:
			if user in self.ircd.users:
				reply.append(self.ircd.users[user].nickname)
		self.sendMessage(irc.RPL_ISON, ":{}".format(" ".join(reply)))
	
	def irc_STATS(self, prefix, params):
		if not params:
			self.sendMessage(irc.ERR_NEEDMOREPARAMS, "STATS", ":Not enough parameters")
			return
		if params[0][0] not in self.ircd.server_stats_public and not self.mode.has("o"):
			self.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - Stats {} requires oper privileges".format(params[0][0]))
			return
		statsmethod = getattr(self, "stats_{}".format(params[0][0]), None)
		if statsmethod is not None:
			statsmethod()
		self.sendMessage(irc.RPL_ENDOFSTATS, params[0][0], ":End of /STATS report")
	
	def irc_SAJOIN(self, prefix, params):
		if not self.mode.has("o"):
			self.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - command SAJOIN requires oper privileges")
			return
		if not params or len(params) < 2:
			self.sendMessage(irc.ERR_NEEDMOREPARAMS, "SAJOIN", ":Not enough parameters")
			return
		if params[0] not in self.ircd.users:
			self.sendMessage(irc.ERR_NOSUCHNICK, params[0], ":No such nick")
			return
		if params[1][0] not in self.ircd.channel_prefixes:
			self.sendMessage(irc.ERR_BADCHANMASK, channel, ":Bad Channel Mask")
			return
		user = self.ircd.users[params[0]]
		if user.mode.has("o"):
			self.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - You cannot SAJOIN another oper")
		else:
			cdata = self.ircd.channels[params[1]]
			if cdata.mode.has("k"):
				user.join(cdata.name, cdata.mode.get("k"))
			else:
				user.join(cdata.name, None)
	
	def irc_SANICK(self, prefix, params):
		if not self.mode.has("o"):
			self.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - command SANICK requires oper privileges")
			return
		if not params or len(params) < 2:
			self.sendMessage(irc.ERR_NEEDMOREPARAMS, "SANICK", ":Not enough parameters")
			return
		if params[0] not in self.ircd.users:
			self.sendMessage(irc.ERR_NOSUCHNICK, params[0], ":No such nick")
			return
		if not VALID_USERNAME.match(params[1]):
			self.sendMessage(irc.ERR_ERRONEUSNICKNAME, params[1], ":Erroneous nickname")
			return
		user = self.ircd.users[params[0]]
		if user.mode.has("o"):
			self.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - you cannot SANICK another oper")
		else:
			user.irc_NICK(None, [params[1]])
	
	def irc_BADWORD(self, prefix, params):
		if not self.mode.has("o"):
			self.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - You do not have the required operator privileges")
			return
		if not params:
			self.sendMessage(irc.ERR_NEEDMOREPARAMS, "BADWORD", ":Not enough parameters")
			return
		if params[0][0] == "-":
			mask = params[0][1:]
			if mask in self.ircd.server_badwords:
				del self.ircd.server_badwords[mask]
				self.sendMessage(irc.RPL_BADWORDREMOVED, mask, ":Badword removed")
				self.ircd.save_options()
			else:
				self.sendMessage(irc.ERR_NOSUCHBADWORD, mask, ":No such badword")
		else:
			mask = params[0]
			replacement = params[1] if len(params) > 1 else ""
			self.ircd.server_badwords[mask] = replacement
			self.sendMessage(irc.RPL_BADWORDADDED, mask, ":{}".format(replacement))
			self.ircd.save_options()
			
	def irc_GLOBOPS(self, prefix, params):
		if not self.mode.has("o"):
			self.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - command GLOBOPS requires oper privileges")
			return
		if not params:
			self.sendMessage(irc.ERR_NEEDMOREPARAMS, "GLOBOPS", ":Not enough parameters")
			return
		message = " ".join(params)
		for user in self.ircd.users.itervalues():
			if user.mode.has("o"):
				user.sendMessage("NOTICE", ":*** GLOBOPS from {}: {}".format(self.nickname, message)) # notice is from server
	
	def irc_WALLOPS(self, prefix, params):
		if not self.mode.has("o"):
			self.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - command WALLOPS requires oper privileges")
			return
		if not params:
			self.sendMessage(irc.ERR_NEEDMOREPARAMS, "WALLOPS", ":Not enough parameters")
			return
		message = " ".join(params)
		for user in self.ircd.users.itervalues():
			if user.mode.has("w"):
				user.sendMessage("WALLOPS", ":{}".format(message), to=None, prefix=self.prefix())