# -*- coding: utf-8 -*-
from twisted.internet import reactor
from twisted.internet.defer import DeferredList
from twisted.internet.protocol import Factory
from twisted.internet.task import LoopingCall
from twisted.internet.interfaces import ISSLTransport
from twisted.python import log
from twisted.python.logfile import DailyLogFile
from twisted.words.protocols import irc
from txircd.utils import CaseInsensitiveDictionary, now
from txircd.user import IRCUser
from txircd import __version__
import uuid, socket, yaml, os, json, imp

# Add additional numerics to complement the ones in the RFC
irc.RPL_LOCALUSERS = "265"
irc.RPL_GLOBALUSERS = "266"
irc.RPL_CREATIONTIME = "329"
irc.RPL_TOPICWHOTIME = "333"
irc.ERR_CHANNOTALLOWED = "926" # I had to make this one up, too.
# Fix twisted being silly
irc.RPL_ADMINLOC1 = "257"
irc.RPL_ADMINLOC2 = "258"

default_options = {
	# App details
	"app_verbose": False,
	"app_ssl_key": "test.key",
	"app_ssl_pem": "test.pem",
	"app_irc_spec": "rfc1459",
	"app_log_dir": "logs",
	# Network details
	"network_name": "txircd",
	# Server details
	"server_name": socket.getfqdn(),
	"server_motd": "Welcome to txircd",
	"server_motd_line_length": 80,
	"server_port_tcp": 6667,
	"server_port_ssl": 6697,
	"server_port_web": 8080,
	"server_stats_public": "ou",
	"server_modules": [],
	"server_password": None,
	# Client details
	"client_vhosts": {"127.0.0.1":"localhost"},
	"client_max_data": 5000, # Bytes per 5 seconds
	"client_peer_connections": 3,
	"client_peer_exempt": {"127.0.0.1":0},
	"client_ping_interval": 60,
	"client_timeout_delay": 120,
	"client_ban_msg": "You're banned! Email abuse@xyz.com for help.",
	# Oper details
	"oper_ips": ["127.0.0.1"],
	"oper_logins": {"admin":"sha256:1000:abc:e/+7RSuHvTHideDuZkpvFXtq65+oHM9x"},
	# Channel details
	"channel_default_mode": {"n": None, "t": None},
	"channel_default_status": "o",
	"channel_exempt_chanops": "", # list of modes from which channel operators are exempt
	# Admin details
	"admin_info_server": "Host Corp: 123 example street, Seattle, WA, USA",
	"admin_info_organization": "Umbrella Corp: 123 example street, Seattle, WA, USA",
	"admin_info_person": "Lazy admin <admin@example.com>",
}

class IRCProtocol(irc.IRC):
	def __init__(self, *args, **kwargs):
		self.dead = False
		self.type = None
		self.secure = False
		self.data = 0
		self.data_checker = LoopingCall(self.checkData)
		self.pinger = LoopingCall(self.ping)
		self.last_message = None
	
	def connectionMade(self):
		self.type = IRCUser(self)
		tryagain = []
		for function in self.factory.actions["connect"]:
			result = function(self.type)
			if result == "again":
				tryagain.append(function)
			elif not result:
				self.transport.loseConnection()
				self.type = None
				break
		if self.type:
			for function in tryagain:
				if not function(self.type):
					self.transport.loseConnection()
					self.type = None
					break
		if self.type:
			self.secure = ISSLTransport(self.transport, None) is not None
			self.data_checker.start(5)
			self.last_message = now()
			self.pinger.start(self.factory.servconfig["client_ping_interval"], now=False)

	def dataReceived(self, data):
		if self.dead:
			return
		for modfunc in self.factory.actions["recvdata"]:
			modfunc(self.type, data)
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
		if (now() - self.last_message).total_seconds() > self.factory.servconfig["client_timeout_delay"]:
			self.transport.loseConnection()
			self.connectionLost(None)
		else:
			self.sendMessage("PING",":{}".format(self.factory.servconfig["server_name"]))
	
	def handleCommand(self, command, prefix, params):
		log.msg("handleCommand: {!r} {!r} {!r}".format(command, prefix, params))
		return self.type.handleCommand(command, prefix, params)
	
	def sendLine(self, line):
		if self.dead:
			return
		for modfunc in self.factory.actions["senddata"]:
			modfunc(self.type, line)
		log.msg("sendLine: {!r}".format(line))
		return irc.IRC.sendLine(self, line)
		
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

	def __init__(self, config, options = None):
		reactor.addSystemEventTrigger("before", "shutdown", self.cleanup)
		self.dead = False
		
		self.config = config
		self.version = "txircd-{}".format(__version__)
		self.created = now()
		self.token = uuid.uuid1()
		self.servers = CaseInsensitiveDictionary()
		self.users = CaseInsensitiveDictionary()
		self.localusers = CaseInsensitiveDictionary()
		self.channels = CaseInsensitiveDictionary()
		self.peerConnections = {}
		self.modules = {}
		self.actions = {
			"connect": [],
			"register": [],
			"welcome": [],
			"join": [],
			"joinmessage": [],
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
		self.module_data_cache = {}
		try:
			with open("data.yaml", "r") as dataFile:
				self.serialized_data = yaml.safe_load(dataFile)
		except IOError:
			self.serialized_data = {}
		self.serialize_timer = LoopingCall(self.save_serialized)
		self.isupport = {}
		self.usercount = {
			"localmax": 0,
			"globalmax": 0
		}
		self.servconfig = {}
		if not options:
			options = {}
		self.load_options(options)
		# Fill in the default ISUPPORT dictionary once config and modules are loaded, since some values depend on those
		self.isupport["CASEMAPPING"] = "rfc1459"
		self.isupport["CHANMODES"] = ",".join(["".join(modedict.keys()) for modedict in self.channel_modes])
		self.isupport["CHANNELLEN"] = "64"
		self.isupport["CHANTYPES"] = "#"
		self.isupport["MODES"] = 20
		self.isupport["NETWORK"] = self.servconfig["network_name"]
		self.isupport["NICKLEN"] = "32"
		self.isupport["PREFIX"] = "({}){}".format("".join(self.prefix_order), "".join([self.prefixes[mode][0] for mode in self.prefix_order]))
		self.isupport["STATUSMSG"] = "".join([self.prefixes[mode][0] for mode in self.prefix_order])
		self.isupport["TOPICLEN"] = "316"
		
		self.serialize_timer.start(300, now=False) # run every 5 minutes
	
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
		            "cmd_admin", "cmd_info", "cmd_lusers", "cmd_motd", "cmd_stats", "cmd_time", "cmd_version", # server info
		            "cmd_away", "cmd_ison", "cmd_userhost", "cmd_who", "cmd_whois", "cmd_whowas", # user info
		            "cmd_names", "cmd_list", # channel info
		            "cmd_kill", "cmd_eline", "cmd_gline", "cmd_kline", "cmd_qline", "cmd_zline", # user management
		            
		            # channel modes
		            "cmode_b", "cmode_i", "cmode_k", "cmode_l", "cmode_m", "cmode_n", "cmode_o", "cmode_p", "cmode_s", "cmode_t", "cmode_v",
		            
		            # user modes
		            "umode_i", "umode_s"
		            ]
		ircv3_spec = [
		              "ircv3_cap", # capability mechanism which essentially serves as the base for everything else
		              "ircv3_multi-prefix", "ircv3_sasl", "ircv3_account-notify", "ircv3_away-notify", "ircv3_extended-join", # IRC 3.1 extensions
		              "ircv3_monitor", "ircv3_metadata" # IRC 3.2 extensions
		             ]
		for module in rfc_spec:
			check = self.load_module(module)
			if not check:
				log.msg("An RFC-required capability could not be loaded!")
				raise RuntimeError("A module required for RFC compatibility could not be loaded.")
				return
		if self.servconfig["app_irc_spec"] == "ircv3":
			for module in ircv3_spec:
				check = self.load_module(module)
				if not check:
					log.msg("IRCv3 compatibility was specified, but a required IRCv3 module could not be loaded!")
					raise RuntimeError("A module required for IRCv3 compatibility could not be loaded.")
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
		for var, value in options.iteritems():
			self.servconfig[var] = value
		for var, value in default_options.iteritems():
			if var not in self.servconfig:
				self.servconfig[var] = value
		self.all_module_load()
	
	def save_options(self):
		# Overwrite with the new stuff
		options = self.servconfig
		for var, value in default_options.iteritems():
			if var not in options:
				options[var] = value
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
			u.sendMessage("ERROR", ":Closing Link: {} [Server shutting down]".format(u.hostname), to=None, prefix=None)
			u.socket.transport.loseConnection()
			deferreds.append(u.disconnected)
		log.msg("Unloading modules...")
		for name, spawner in self.modules.iteritems():
			spawner.cleanup()
			try:
				data_to_save, free_data = self.modules[name].data_serialize()
				if data_to_save:
					self.serialized_data[name] = data_to_save
			except AttributeError:
				pass
		# Finally, save the config. Just in case.
		log.msg("Saving options...")
		self.save_options()
		log.msg("Saving serialized data...")
		self.save_serialized()
		# Return deferreds
		log.msg("Waiting on deferreds...")
		self.dead = True
		return DeferredList(deferreds)
	
	def load_module(self, name):
		saved_data = {}
		if name in self.modules:
			try:
				data_to_save, free_data = self.modules[name].data_serialize()
				if data_to_save:
					self.serialized_data[name] = data_to_save
				for key, value in free_data.iteritems():
					saved_data[key] = value
				for key, value in data_to_save.iteritems():
					saved_data[key] = value
			except AttributeError:
				pass
			try:
				self.modules[name].cleanup()
			except:
				log.msg("Cleanup failed for module {}: some pieces may still be remaining!".format(name))
			del self.modules[name]
		try:
			mod_find = imp.find_module("txircd/modules/{}".format(name))
		except ImportError as e:
			log.msg("Module not found: {} {}".format(name, e))
			return False
		try:
			mod_load = imp.load_module(name, mod_find[0], mod_find[1], mod_find[2])
		except ImportError as e:
			log.msg("Could not load module: {} ({})".format(name, e))
			mod_find[0].close()
			return False
		mod_find[0].close()
		try:
			mod_spawner = mod_load.Spawner(self)
		except Exception as e:
			log.msg("Module is not a valid txircd module: {} ({})".format(name, e))
			return False
		try:
			mod_contains = mod_spawner.spawn()
		except Exception as e:
			log.msg("Module is not a valid txircd module: {} ({})".format(name, e))
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
							log.msg("Module {} tries to register a prefix without a symbol or level".format(name))
							continue
						try:
							level = int(mode[4:])
						except:
							log.msg("Module {} tries to register a prefix without a numeric level".format(name))
							continue
						closestLevel = 0
						closestModeChar = None
						orderFail = False
						for levelMode, levelData in self.prefixes.iteritems():
							if level == levelData[1]:
								log.msg("Module {} tries to register a prefix with the same rank level as an existing prefix")
								orderFail = True
								break
							if levelData[1] < level and levelData[1] > closestLevel:
								closestLevel = levelData[1]
								closestModeChar = levelMode
						if orderFail:
							continue
						if closestModeChar:
							self.prefix_order.insert(self.prefix_order.index(closestModeChar), mode[2])
						else:
							self.prefix_order.append(mode[2])
						self.prefixes[mode[2]] = [mode[3], level, implementation.hook(self)]
						self.prefix_symbols[mode[3]] = mode[2]
					self.channel_mode_type[mode[2]] = modetype
					self.isupport["PREFIX"] = "({}){}".format("".join(self.prefix_order), "".join([self.prefixes[mode][0] for mode in self.prefix_order]))
					self.isupport["STATUSMSG"] = "".join([self.prefixes[mode][0] for mode in self.prefix_order])
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
			for actiontype, actionfuncs in mod_contains["actions"].iteritems():
				if actiontype in self.actions:
					for func in actionfuncs:
						self.actions[actiontype].append(func)
				else:
					self.actions[actiontype] = actionfuncs
		if not saved_data and name in self.serialized_data:
			saved_data = self.serialized_data[name] # present serialized data on first load of session
		if saved_data:
			try:
				mod_spawner.data_unserialize(saved_data)
			except AttributeError:
				pass
		return True
	
	def removeMode(self, modedesc):
		# This function is heavily if'd in case we get passed invalid data.
		if modedesc[1] == "l":
			modetype = 0
		elif modedesc[1] == "u":
			modetype = 1
		elif modedesc[1] == "p":
			modetype = 2
		elif modedesc[1] == "n":
			modetype = 3
		elif modedesc[1] == "s":
			modetype = -1
		else:
			return
		
		if modedesc[0] == "c":
			if modetype != -1 and modedesc[2] in self.channel_modes[modetype]:
				del self.channel_modes[modetype][modedesc[2]]
			if modedesc[2] in self.channel_mode_type:
				del self.channel_mode_type[modedesc[2]]
			if modetype == -1 and modedesc[2] in self.prefixes:
				del self.prefix_symbols[self.prefixes[modedesc[2]][0]]
				if modedesc[2] in self.prefixes:
					del self.prefixes[modedesc[2]]
				if modedesc[2] in self.prefix_order:
					self.prefix_order.remove(modedesc[2])
		else:
			if modedesc[2] in self.user_modes[modetype]:
				del self.user_modes[modetype][modedesc[2]]
			if modedesc[2] in self.user_mode_type:
				del self.user_mode_type[modedesc[2]]
	
	def save_serialized(self):
		with open("data.yaml", "w") as dataFile:
			yaml.dump(self.serialized_data, dataFile, default_flow_style=False)
	
	def buildProtocol(self, addr):
		if self.dead:
			return None
		ip = addr.host
		return Factory.buildProtocol(self, addr)

	def unregisterProtocol(self, p):
		pass