# -*- coding: utf-8 -*-
from twisted.enterprise import adbapi
from twisted.internet import reactor
from twisted.internet.defer import DeferredList
from twisted.internet.protocol import Factory
from twisted.internet.task import LoopingCall
from twisted.internet.interfaces import ISSLTransport
from twisted.python import log
from twisted.python.logfile import DailyLogFile
from twisted.words.protocols import irc
from txircd.utils import CaseInsensitiveDictionary, VALID_USERNAME, epoch, now, irc_lower, parse_duration, build_duration
from txircd.user import IRCUser
from txircd.stats import StatFactory
from txircd import __version__
from txsockjs.factory import SockJSFactory
import uuid, socket, collections, yaml, os, fnmatch, datetime, pygeoip, json, imp

# Add additional numerics to complement the ones in the RFC
irc.RPL_STATS = "210"
irc.RPL_STATSOPERS = "249" # Same here.
irc.RPL_STATSPORTS = "249" # And here.
irc.RPL_CREATIONTIME = "329"
irc.RPL_WHOISACCOUNT = "330"
irc.RPL_TOPICWHOTIME = "333"
irc.RPL_WHOISSECURE  = "671"
irc.RPL_KNOCK = "710"
irc.RPL_KNOCKDLVR = "711"
irc.ERR_TOOMANYKNOCK = "712"
irc.ERR_CHANOPEN = "713"
irc.ERR_KNOCKONCHAN = "714"
irc.ERR_CHANNOTALLOWED = "926" # I had to make this one up, too.
# Fix twisted being silly
irc.RPL_ADMINLOC1 = "257"
irc.RPL_ADMINLOC2 = "258"

default_options = {
	# App details
	"app_verbose": False,
	"app_log_dir": "logs",
	"app_ip_log": "ips.json",
	"app_geoip_database": None,
	"app_ssl_key": "test.key",
	"app_ssl_pem": "test.pem",
	# Network details
	"network_name": "txircd",
	# Server details
	"server_name": socket.getfqdn(),
	"server_motd": "Welcome to txIRCD",
	"server_motd_line_length": 80,
	"server_port_tcp": 6667,
	"server_port_ssl": 6697,
	"server_port_web": 8080,
	"server_stats_public": "ou",
	"server_denychans": [],
	"server_allowchans": [],
	"server_badwords": {},
	"server_modules": [],
	"server_password": None,
	"server_xlines_k": {},
	"server_xlines_g": {},
	"server_xlines_q": {},
	"server_xlines_z": {},
	"server_xlines_e": {},
	"server_xlines_shun": {},
	# Client details
	"client_vhosts": {"127.0.0.1":"localhost"},
	"client_max_data": 5000, # Bytes per 5 seconds
	"client_peer_connections": 3,
	"client_peer_exempt": {"127.0.0.1":0},
	"client_ping_interval": 35,
	"client_timeout_delay": 90,
	"client_ban_msg": "You're banned! Email abuse@xyz.com for help.",
	"client_whowas_limit": 10,
	# Oper details
	"oper_ips": ["127.0.0.1"],
	"oper_logins": {"admin":"$p5k2$$gGs8NHIY$ZtbawYVNM63aojnLWXmvkNA33ciJbOfB"},
	"oper_allow_die": True,
	# Database details
	"db_host": "localhost",
	"db_port": 3306,
	"db_library": None,
	"db_marker": "?",
	"db_username": None,
	"db_password": None,
	"db_database": None,
	# Nickserv details
	"nickserv_timeout": 40,
	"nickserv_limit": 5,
	"nickserv_guest_prefix": "Guest",
	# Bidserv details
	"bidserv_display_all_madness": False,
	"bidserv_bid_limit": 1000000,
	"bidserv_auction_item": None,
	"bidserv_auction_name": None,
	"bidserv_auction_state": 0,
	"bidserv_min_increase": 5,
	"bidserv_bids": [],
	"bidserv_admins": [1,3],
	"bidserv_madness_levels": {1000: "Myth Busted"},
	"bidserv_space_bid": "SPACE BID",
	"bidserv_kill_reason": "Being a dick",
	# Chanserv?? details
	"channel_exempt_chanops": "", # list of modes from which channel operators are exempt
	"channel_auto_ops": {1:"q"},
	"channel_founder_mode": "q",
	# Admin details
	"admin_info_server": "Host Corp: 123 example street, Seattle, WA, USA",
	"admin_info_organization": "Umbrella Corp: 123 example street, Seattle, WA, USA",
	"admin_info_person": "Lazy admin <admin@example.com>",
	# Stats details
	"stats_enabled": True,
	"stats_port_tcp": 43789,
	"stats_port_web": 43790,
}

class IRCProtocol(irc.IRC):
	def __init__(self, *args, **kwargs):
		self.dead = False
		self.type = self.factory.types["user"](self)
		self.secure = False
		self.data = 0
		self.data_checker = LoopingCall(self.checkData)
		self.pinger = LoopingCall(self.ping)
		self.last_message = None
	
	def connectionMade(self):
		self.secure = ISSLTransport(self.transport, None) is not None
		self.data_checker.start(5)
		self.last_message = now()
		self.pinger.start(self.factory.client_ping_interval)
		ip = self.transport.getPeer().host

	def dataReceived(self, data):
		if self.dead:
			return
		self.factory.stats_data["bytes_in"] += len(data)
		self.factory.stats_data["total_bytes_in"] += len(data)
		self.data += len(data)
		self.last_message = now()
		if self.pinger.running:
			self.pinger.reset()
		irc.IRC.dataReceived(self, data)
	
	def checkData(self):
		if self.type:
			self.type.checkData(self.data)
		self.data = 0
	
	def ping(self):
		if (now() - self.last_message).total_seconds() > self.factory.client_timeout_delay:
			self.transport.loseConnection()
			self.connectionLost(None)
		else:
			self.sendMessage("PING",":{}".format(self.factory.server_name))
	
	def handleCommand(self, command, prefix, params):
		self.factory.stats_data["lines_in"] += 1
		self.factory.stats_data["total_lines_in"] += 1
		log.msg("handleCommand: {!r} {!r} {!r}".format(command, prefix, params))
		return self.type.handleCommand(command, prefix, params)
	
	def sendLine(self, line):
		if self.dead:
			return
		self.factory.stats_data["lines_out"] += 1
		self.factory.stats_data["total_lines_out"] += 1
		self.factory.stats_data["bytes_out"] += len(line)+2
		self.factory.stats_data["total_bytes_out"] += len(line)+2
		log.msg("sendLine: {!r}".format(line))
		return irc.IRC.sendLine(self, line)
	
	def irc_CAP(self, prefix, params):
		pass
	
	def irc_QUIT(self, prefix, params):
		self.transport.loseConnection()
		
	def connectionLost(self, reason):
		if self.dead:
			return
		self.dead = True
		self.factory.unregisterProtocol(self)
		if self.type:
			self.type.connectionLost(reason)
		if self.data_checker.running:
			self.data_checker.stop()
		if self.pinger.running:
			self.pinger.stop()

class IRCD(Factory):
	protocol = IRCProtocol
	channel_prefixes = "#"
	types = {
		"user": IRCUser,
		#"server": IRCServer,
		#"service": IRCService,
	}

	def __init__(self, config, options = None):
		reactor.addSystemEventTrigger("before", "shutdown", self.cleanup)
		self.dead = False
		
		self.config = config
		self.version = "txircd-{}".format(__version__)
		self.created = now()
		self.token = uuid.uuid1()
		self.servers = CaseInsensitiveDictionary()
		self.users = CaseInsensitiveDictionary()
		self.whowas = CaseInsensitiveDictionary()
		self.channels = CaseInsensitiveDictionary()
		self.peerConnections = {}
		self.modules = {}
		self.actions = {
			"join": [],
			"message": [],
			"part": [],
			"topicchange": [],
			"connect": [],
			"register": [],
			"nick": [],
			"quit": [],
			"nameslistentry": [],
			"chancreate": [],
			"chandestroy": [],
			"commandextra": [],
			"commandunknown": [],
			"commandpermission": [],
			"metadataupdate": [],
			"recvdata": [],
			"senddata": []
		}
		self.commands = {}
		self.channel_modes = [{}, {}, {}, {}]
		self.channel_mode_type = {}
		self.user_modes = [{}, {}, {}, {}]
		self.user_mode_type = {}
		self.prefixes = {}
		self.prefix_symbols = {}
		self.prefix_order = []
		self.db = None
		self.stats = None
		self.stats_timer = LoopingCall(self.flush_stats)
		self.stats_data = {
			"bytes_in": 0,
			"bytes_out": 0,
			"lines_in": 0,
			"lines_out": 0,
			"total_bytes_in": 0,
			"total_bytes_out": 0,
			"total_lines_in": 0,
			"total_lines_out": 0,
			"connections": 0,
			"total_connections": 0
		}
		self.servconfig = {}
		if not options:
			options = {}
		self.load_options(options)
		
		if self.app_ip_log:
			try:
				with open(self.app_ip_log) as f:
					self.unique_ips = set(json.loads(f.read()))
					self.stats_data["total_connections"] = len(self.unique_ips)
			except:
				self.unique_ips = set()
		else:
			self.unique_ips = set()
		
		logfile = "{}/{}".format(self.app_log_dir,"stats")
		if not os.path.exists(logfile):
			os.makedirs(logfile)
		self.stats_log = DailyLogFile("log",logfile)
		self.stats_timer.start(1)
		
		self.all_module_load()
	
	def all_module_load(self):
		# load RFC-required modules
		rfc_spec = [
		            # commands
		            "cmd_user", "cmd_nick", "cmd_pass", # registration
		            "cmd_ping", "cmd_pong", # connection keep-alive
		            "cmd_join", "cmd_part", "cmd_kick", "cmd_topic", "cmd_mode", "cmd_invite", # channels
		            "cmd_quit", # connection end
		            "cmd_privmsg_notice", # messages
		            "cmd_oper", "umode_o", "cmd_rehash", "cmd_wallops", # oper
		            "cmd_admin", "cmd_info", "cmd_motd", "cmd_stats", "cmd_time", "cmd_version", # server info
		            "cmd_away", "cmd_ison", "cmd_userhost", "cmd_who", "cmd_whois", "cmd_whowas", # user info
		            "cmd_names", "cmd_list", # channel info
		            "cmd_kill", "cmd_eline", "cmd_gline", "cmd_kline", "cmd_qline", "cmd_zline", # user management
		            
		            # channel modes
		            "cmode_b", "cmode_i", "cmode_k", "cmode_l", "cmode_m", "cmode_n", "cmode_o", "cmode_p", "cmode_s", "cmode_t", "cmode_v",
		            
		            # user modes
		            "umode_i", "umode_o", "umode_s"
		            ]
		ircv3_spec = [
		              # will be populated when I write the IRCv3 modules
		             ]
		for module in rfc_spec:
			check = self.load_module(module)
			if not check:
				log.msg("An RFC-required capability could not be loaded!")
				reactor.stop()
				return
		if self.servconfig["irc_spec"] == "ircv3":
			for module in ircv3_spec:
				check = self.load_module(module)
				if not check:
					log.msg("IRCv3 compatibility was specified, but a required IRCv3 module could not be loaded!")
					reactor.stop()
					return
		for module in self.servconfig["server_modules"]:
			self.load_module(module)
	
	def rehash(self):
		try:
			with open(self.config) as f:
				self.load_options(yaml.safe_load(f))
			self.all_module_load()
		except:
			return False
		return True
	
	def load_options(self, options):
		for var, value in options.itervalues():
			self.servconfig[var] = value
		for var, value in default_options.iteritems():
			if var not in self.servconfig:
				self.servconfig[var] = value
		self.all_module_load()
	
	def save_options(self):
		# Serialize xlines
		for key, lines in self.xlines.iteritems():
			xlines = {}
			for user, data in lines.iteritems():
				xlines[user] = {
					"created": str(data["created"]),
					"duration": build_duration(data["duration"]),
					"setter": data["setter"],
					"reason": data["reason"]
				}
			setattr(self, "server_xlines_{}".format(key.lower()), xlines)
		# Load old options
		options = {}
		try:
			with open(self.config) as f:
				options = yaml.safe_load(f)
		except:
			return False
		# Overwrite with the new stuff
		for var in default_options.iterkeys():
			options[var] = getattr(self, var, None)
		for var, value in self.servconfig.iteritems():
			if var not in default_options: # Stop anything that may have tried to overwrite a default_option through servconfig
				options[var] = value
		# Save em
		try:
			with open(self.config,"w") as f:
				yaml.dump(options, f, default_flow_style=False)
		except:
			return False
		return True
	
	def cleanup(self):
		for module in self.modules.itervalues():
			try:
				module.cleanup()
			except:
				pass
		# Track the disconnections so we know they get done
		deferreds = []
		# Cleanly disconnect all clients
		log.msg("Disconnecting clients...")
		for u in self.users.values():
			u.irc_QUIT(None,["Server shutting down"])
			deferreds.append(u.disconnected)
		# Without any clients, all channels should be gone
		# But make sure the logs are closed, just in case
		log.msg("Closing logs...")
		for c in self.channels.itervalues():
			c.log.close()
		self.stats_log.close()
		# Finally, save the config. Just in case.
		log.msg("Saving options...")
		self.save_options()
		# Return deferreds
		log.msg("Waiting on deferreds...")
		self.dead = True
		return DeferredList(deferreds)
	
	def load_module(self, name):
		if name in self.modules:
			try:
				self.modules[name].cleanup()
			except:
				pass
			del self.modules[name]
		try:
			mod_find = imp.find_module("txircd/modules/{}".format(name))
		except ImportError:
			log.msg("Module not found: {}".format(name))
			return False
		try:
			mod_load = imp.load_module(name, mod_find[0], mod_find[1], mod_find[2])
		except ImportError:
			log.msg("Could not load module: {}".format(name))
			mod_find[0].close()
			return False
		mod_find[0].close()
		try:
			mod_spawner = mod_load.Spawner(self)
		except:
			log.msg("Module is not a valid txircd module: {}".format(name))
			return False
		try:
			mod_contains = mod_spawner.spawn()
		except:
			log.msg("Module is not a valid txircd module: {}".format(name))
			return False
		self.modules[name] = mod_spawner
		if "commands" in mod_contains:
			for command, implementation in mod_contains["commands"].iteritems():
				if command in self.commands:
					log.msg("Module {} tries to reimplement command {}".format(name, command))
					continue
				self.commands[command] = implementation.hook(self)
		if "modes" in mod_contains:
			for mode, implementation in mod_contains["modes"].iteritems():
				if len(mode) < 2:
					continue
				if mode[1] == "l":
					modetype = 0
				elif mode[1] == "u":
					modetype = 1
				elif mode[1] == "p":
					modetype = 2
				elif mode[1] == "n":
					modetype = 3
				elif mode[1] == "s":
					modetype = -1
				else:
					log.msg("Module {} registers a mode of an invalid type".format(name))
					continue
				if mode[0] == "c":
					if mode[2] in self.channel_mode_type:
						log.msg("Module {} tries to reimplement channel mode {}".format(name, mode))
						continue
					if modetype >= 0:
						self.channel_modes[modetype][mode[2]] = implementation.hook(self)
					else:
						if len(mode) < 5:
							log.msg("Module {} tries to register a prefix without a symbol or level")
							continue
						try:
							level = int(mode[4:])
						except:
							log.msg("Module {} tries to register a prefix without a numeric level")
							continue
						closestLevel = 0
						closestModeChar = None
						orderFail = False
						for levelMode, levelData in self.prefixes.iteritems():
							if level == levelData[0]:
								log.msg("Module {} tries to register a prefix with the same rank level as an existing prefix")
								orderFail = True
								break
							if levelData[0] < level and levelData > closestLevel:
								closestLevel = levelData[0]
								closestModeChar = levelMode
						if orderFail:
							continue
						if closestModeChar:
							self.prefix_order.insert(self.prefix_order.find(closestModeChar), mode[2])
						else:
							self.prefix_order.insert(0, mode[2])
						self.prefixes[mode[2]] = [mode[3], level, implementation]
						self.prefix_symbols[mode[3]] = mode[2]
					self.channel_mode_type[mode[2]] = modetype
				elif mode[0] == "u":
					if modetype == -1:
						log.msg("Module {} registers a mode of an invalid type".format(name))
						continue
					if mode[2] in self.user_mode_type:
						log.msg("Module {} tries to reimplement user mode {}".format(name, mode))
						continue
					self.user_modes[modetype][mode[2]] = implementation.hook(self)
					self.user_mode_type[mode[2]] = modetype
		if "actions" in mod_contains:
			for actiontype, actionfunc in mod_contains["actions"].iteritems():
				if actiontype in self.actions:
					self.actions[actiontype].append(actionfunc)
				else:
					self.actions[actiontype] = [actionfunc]
		return True
	
	def removeMode(self, modedesc):
		# This function is heavily if'd in case we get passed invalid data.
		if mode[1] == "l":
			modetype = 0
		elif mode[1] == "u":
			modetype = 1
		elif mode[1] == "p":
			modetype = 2
		elif mode[1] == "n":
			modetype = 3
		elif mode[1] == "s":
			modetype = -1
		else:
			return
		"""
		self.channel_modes = [{}, {}, {}, {}]
		self.channel_mode_type = {}
		self.user_modes = [{}, {}, {}, {}]
		self.user_mode_type = {}
		self.prefixes = {}
		self.prefix_symbols = {}
		self.prefix_order = []
		"""
		if mode[0] == "c":
			del self.channel_modes[modetype][mode[2]] if modetype != -1 and mode[2] in self.channel_modes[modetype]
			del self.channel_mode_type[mode[2]] if mode[2] in self.channel_mode_type
			if modetype == -1 and mode[2] in self.prefixes:
				del self.prefix_symbols[self.prefixes[mode[2]][0]]
				del self.prefixes[mode[2]] if mode[2] in self.prefixes
				self.prefix_order.remove(mode[2]) if mode[2] in self.prefix_order
		else:
			del self.user_modes[modetype][mode[2]] if mode[2] in self.user_modes[modetype]
			del self.user_mode_type[mode[2]] if mode[2] in self.user_mode_type
	
	def buildProtocol(self, addr):
		if self.dead:
			return None
		ip = addr.host
		self.unique_ips.add(ip)
		self.stats_data["total_connections"] = len(self.unique_ips)
		if self.app_ip_log:
			with open(self.app_ip_log,"w") as f:
				f.write(json.dumps(list(self.unique_ips), separators=(',',':')))
		conn = self.peerConnections.get(ip,0)
		max = self.client_peer_exempt[ip] if ip in self.client_peer_exempt else self.client_peer_connections
		if max and conn >= max:
			return None
		self.stats_data["connections"] += 1
		self.peerConnections[ip] = conn + 1
		return Factory.buildProtocol(self, addr)

	def unregisterProtocol(self, p):
		self.stats_data["connections"] -= 1
		peerHost = p.transport.getPeer().host
		self.peerConnections[peerHost] -= 1
		if self.peerConnections[peerHost] == 0:
			del self.peerConnections[peerHost]
	
	def flush_stats(self):
		users = {}
		countries = {}
		uptime = now() - self.created
		for u in self.users.itervalues():
			users[u.nickname] = [u.latitude, u.longitude]
			if u.country not in countries:
				countries[u.country] = 0
			countries[u.country] += 1
		line = json.dumps({
			"io":self.stats_data,
			"users":users,
			"countries":countries,
			"uptime": "{}".format(uptime if uptime.days > 0 else "0 days, {}".format(uptime))
		}, separators=(',',':'))
		self.stats_data["bytes_in"] = 0
		self.stats_data["bytes_out"] = 0
		self.stats_data["lines_in"] = 0
		self.stats_data["lines_out"] = 0
		#if not self.stats_log.closed:
		#    self.stats_log.write(line+"\n")
		if self.stats:
			self.stats.broadcast(line+"\r\n")