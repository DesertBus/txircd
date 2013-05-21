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
from txircd.mode import ChannelModes
from txircd.user import IRCUser
from txircd.stats import StatFactory
from txircd import __version__
from txsockjs.factory import SockJSFactory
import uuid, socket, collections, yaml, os, fnmatch, datetime, pygeoip, json, imp

# Add additional numerics to complement the ones in the RFC
irc.RPL_STATS = "210"
irc.RPL_STATSQLINE = "217"
irc.RPL_STATSGLINE = "223"
irc.RPL_STATSKLINE = "223"
irc.RPL_STATSZLINE = "223"
irc.RPL_STATSELINE = "223"
irc.RPL_STATSSHUN = "223" # I don't think this use of the numeric has a name, so I made one. //EA
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
irc.RPL_BADWORDADDED = "927"
irc.RPL_BADWORDREMOVED = "928"
irc.ERR_NOSUCHBADWORD = "929"
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
	"client_ban_msg": "You're banned!",
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
		expired = []
		for mask, linedata in self.factory.xlines["Z"].iteritems():
			if linedata["duration"] != 0 and epoch(now()) > epoch(linedata["created"]) + linedata["duration"]:
				expired.append(mask)
				continue
			if fnmatch.fnmatch(ip, mask):
				self.sendMessage("NOTICE", "*", ":{}".format(self.factory.client_ban_msg), prefix=self.factory.server_name)
				self.sendMessage("ERROR", ":Closing Link {} [Z:Lined: {}]".format(ip, linedata["reason"]))
				self.transport.loseConnection()
		for mask in expired:
			del self.factory.xlines["Z"][mask]
		if expired:
			self.factory.save_options()

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

	def irc_PASS(self, prefix, params):
		if not params:
			return self.sendMessage(irc.ERR_NEEDMOREPARAMS, "PASS", ":Not enough parameters", prefix=self.factory.server_name)
		self.password = params[0]

	def irc_SERVICE(self, prefix, params):
		try:
			self.type = self.factory.types["service"](self, params, self.password)
		except ValueError:
			self.type = None
			self.transport.loseConnection()

	def irc_SERVER(self, prefix, params):
		try:
			self.type = self.factory.types["server"](self, params, self.password)
		except ValueError:
			self.type = None
			self.transport.loseConnection()

	def irc_PING(self, prefix, params):
		if params:
			self.sendMessage("PONG", self.factory.server_name, ":{}".format(params[0]), prefix=self.factory.server_name)
		else: # TODO: There's no nickname here, what do?
			self.sendMessage(irc.ERR_NOORIGIN, "CHANGE_THIS", ":No origin specified", prefix=self.factory.server_name)

	def irc_PONG(self, prefix, params):
		pass
	
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
	prefix_order = "qaohv" # Hardcoded into modes :(
	prefix_symbols = {
		"q": "~",
		"a": "&",
		"o": "@",
		"h": "%",
		"v": "+"
	}

	def __init__(self, config, options = None):
		reactor.addSystemEventTrigger("before", "shutdown", self.cleanup)
		self.dead = False
		
		self.config = config
		self.version = "txircd.{}".format(__version__)
		self.created = now()
		self.token = uuid.uuid1()
		self.servers = CaseInsensitiveDictionary()
		self.users = CaseInsensitiveDictionary()
		self.whowas = CaseInsensitiveDictionary()
		self.channels = CaseInsensitiveDictionary()
		self.peerConnections = {}
		self.modules = {}
		self.actions = []
		self.commands = {}
		self.channel_modes = {}
		self.user_modes = {}
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
		self.xlines = {
			"G": CaseInsensitiveDictionary(),
			"K": CaseInsensitiveDictionary(),
			"Z": CaseInsensitiveDictionary(),
			"E": CaseInsensitiveDictionary(),
			"Q": CaseInsensitiveDictionary(),
			"SHUN": CaseInsensitiveDictionary()
		}
		self.xline_match = {
			"G": ["{ident}@{host}", "{ident}@{ip}"],
			"K": ["{ident}@{host}", "{ident}@{ip}"],
			"Z": ["{ip}"],
			"E": ["{ident}@{host}", "{ident}@{ip}"],
			"Q": ["{nick}"],
			"SHUN": ["{ident}@{host}", "{ident}@{ip}"]
		}
		
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
		
		# load RFC-required modules
		self.load_module("cmd_user")
		self.load_module("cmd_nick")
	
	def rehash(self):
		try:
			with open(self.config) as f:
				self.load_options(yaml.safe_load(f))
		except:
			return False
		return True
	
	def load_options(self, options):
		# Populate attributes with options
		for var in default_options.iterkeys():
			setattr(self, var, options[var] if var in options else default_options[var])
		# Unserialize xlines
		for key in self.xlines.iterkeys():
			self.xlines[key] = CaseInsensitiveDictionary()
			xlines = getattr(self, "server_xlines_{}".format(key.lower()), None)
			if not xlines:
				continue
			for user, data in xlines.iteritems():
				self.xlines[key][user] = {
					"created": datetime.datetime.strptime(data["created"],"%Y-%m-%d %H:%M:%S"),
					"duration": parse_duration(data["duration"]),
					"setter": data["setter"],
					"reason": data["reason"]
				}
		# Create database connection
		if self.db:
			self.db.close()
		if self.db_library:
			self.db = adbapi.ConnectionPool(self.db_library, host=self.db_host, port=self.db_port, db=self.db_database, user=self.db_username, passwd=self.db_password, cp_reconnect=True)
		# Turn on stats factory if needed, or shut it down if needed
		if self.stats_enabled and not self.stats:
			self.stats = StatFactory()
			if self.stats_port_tcp:
				try:
					reactor.listenTCP(int(self.stats_port_tcp), self.stats)
				except:
					pass # Wasn't a number
			if self.stats_port_web:
				try:
					reactor.listenTCP(int(self.stats_port_web), SockJSFactory(self.stats))
				except:
					pass # Wasn't a number
		elif not self.stats_enabled and self.stats:
			self.stats.shutdown()
			self.stats = None
		# Load geoip data
		self.geo_db = pygeoip.GeoIP(self.app_geoip_database, pygeoip.MEMORY_CACHE) if self.app_geoip_database else None
		if self.server_modules:
			for mod in server_modules:
				self.load_module(mod)
	
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
		# Save em
		try:
			with open(self.config,"w") as f:
				yaml.dump(options, f, default_flow_style=False)
		except:
			return False
		return True
	
	def cleanup(self):
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
		try:
			mod_find = imp.find_module("txircd/modules/{}".format(name))
		except ImportError:
			log.msg("Module not found: {}".format(name))
			return None
		try:
			mod_load = imp.load_module(name, mod_find[0], mod_find[1], mod_find[2])
		except ImportError:
			log.msg("Could not load module: {}".format(name))
			mod_find[0].close()
			return None
		mod_find[0].close()
		try:
			mod_contains = mod_load.spawn()
		except:
			log.msg("Module is not a valid txircd module: {}".format(name))
			return None
		self.modules[name] = {}
		if "commands" in mod_contains:
			self.modules[name]["commands"] = []
			for command, implementation in mod_contains["commands"].iteritems():
				if command in self.commands:
					log.msg("Module {} tries to reimplement command {}".format(name, command))
					continue
				self.modules[name]["commands"].append(command)
				self.commands[command] = implementation(self)
		if "modes" in mod_contains:
			for mode, implementation in mod_contains["modes"].iteritems():
				if len(mode) < 2:
					continue
				if mode[0] == "c":
					if mode[1] in self.channel_modes:
						log.msg("Module {} tries to reimplement channel mode {}".format(name, mode[1]))
						continue
					if "chanmodes" not in self.modules[name]:
						self.modules[name]["chanmodes"] = []
					self.modules[name]["chanmodes"].append(mode[1])
					self.channel_modes[mode[1]] = implementation(self)
				elif mode[0] == "u":
					if mode[1] in self.user_modes:
						log.msg("Module {} tries to reimplement user mode {}".format(name, mode[1]))
						continue
					if "usermodes" not in self.modules[name]:
						self.modules[name]["usermodes"] = []
					self.modules[name]["usermodes"].append(mode[1])
					self.user_modes[mode[1]] = implementation(self)
		if "actions" in mod_contains:
			self.modules[name]["actions"] = []
			for action in mod_contains["actions"]:
				new_action = action(self)
				self.actions.append(new_action)
				self.modules[name]["actions"].append(new_action)
		return mod_load
	
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