from twisted.internet import reactor
from twisted.internet.defer import DeferredList
from twisted.internet.endpoints import clientFromString
from twisted.internet.protocol import Factory
from twisted.internet.task import LoopingCall
from twisted.internet.threads import deferToThread
from twisted.internet.interfaces import ISSLTransport
from twisted.python import log
from twisted.words.protocols import irc
from txircd.server import ConnectUser, IntroduceServer, ServerProtocol, protocol_version
from txircd.utils import CaseInsensitiveDictionary, epoch, now, resolveEndpointDescription
from txircd.user import IRCUser
from txircd import __version__
import imp, json, os, socket, yaml

# Add additional numerics to complement the ones in the RFC
irc.RPL_LOCALUSERS = "265"
irc.RPL_GLOBALUSERS = "266"
irc.RPL_CREATIONTIME = "329"
irc.RPL_TOPICWHOTIME = "333"

default_options = {
    # App details
    "app_verbose": False,
    "app_ssl_key": "test.key",
    "app_ssl_pem": "test.pem",
    "app_irc_spec": "rfc1459",
    "app_log_dir": "logs",
    # Server details
    "server_name": socket.getfqdn(),
    "server_description": "A txircd server",
    "server_network_name": "txircd",
    "server_motd": "Welcome to txircd",
    "server_motd_line_length": 80,
    "server_client_ports": [],
    "server_link_ports": [],
    "server_stats_public": "ou",
    "server_modules": [],
    "server_password": None,
    "serverlinks": {},
    "serverlink_autoconnect": [],
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
    "oper_logins": {},
    # Channel details
    "channel_default_mode": {"n": None, "t": None},
    "channel_default_status": "o",
    "channel_exempt_chanops": "", # list of modes from which channel operators are exempt
    "channel_status_minimum_change": {},
    # Admin details
    "admin_info_server": "Host Corp: 123 Example Street, Seattle, WA, USA",
    "admin_info_organization": "Umbrella Corp: 123 Example Street, Seattle, WA, USA",
    "admin_info_person": "Lazy Admin <admin@example.com>",
}

class IRCProtocol(irc.IRC):
    def __init__(self, *args, **kwargs):
        self.dead = False
        self.type = None
        self.secure = False
        self.data = 0
        self.data_checker = LoopingCall(self.checkData)
        self.pinger = LoopingCall.withCount(self.ping)
    
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
            self.pinger.start(self.factory.servconfig["client_ping_interval"], now=False)
            for server in self.factory.servers.itervalues():
                if server.nearHop == self.factory.name:
                    server.callRemote(ConnectUser, uuid=self.type.uuid, ip=self.type.ip, server=self.factory.name, secure=self.secure, signon=epoch(self.type.signon))

    def dataReceived(self, data):
        if self.dead:
            return
        # Get and store the peer certificate if the client is using SSL and providing a client certificate
        # I don't like handling this here, but twisted does not provide a hook to process it in a better place (e.g.
        # when the SSL handshake is complete); see http://twistedmatrix.com/trac/ticket/6024
        # This will be moved in the future when we can.
        if self.secure:
            certificate = self.transport.getPeerCertificate()
            if certificate is not None:
                self.type.setMetadata("server", "certfp", certificate.digest("md5").lower().replace(":", ""))
        # Handle the received data
        for modfunc in self.factory.actions["recvdata"]:
            modfunc(self.type, data)
        self.data += len(data)
        if self.pinger.running:
            self.pinger.reset()
        irc.IRC.dataReceived(self, data)
    
    def checkData(self):
        if self.type:
            self.type.checkData(self.data)
        self.data = 0
    
    def ping(self, intervals):
        timeout = self.factory.servconfig["client_timeout_delay"] + self.factory.servconfig["client_ping_interval"] * (intervals - 1)
        if (now() - self.type.lastpong).total_seconds() > timeout:
            log.msg("Client has stopped responding to PING and is now disconnecting.")
            self.transport.loseConnection()
            self.connectionLost(None)
        elif self.type.lastactivity > self.type.lastpong:
            self.type.lastpong = now()
        else:
            self.sendMessage("PING",":{}".format(self.factory.name))
    
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

    def __init__(self, config, options = None, sslCert = None):
        reactor.addSystemEventTrigger("before", "shutdown", self.cleanup)
        self.dead = False
        
        self.config = config
        self.version = "txircd-{}".format(__version__)
        self.created = now()
        self.servers = CaseInsensitiveDictionary()
        self.users = CaseInsensitiveDictionary()
        self.userid = {}
        self.channels = CaseInsensitiveDictionary()
        self.peerConnections = {}
        self.ssl_cert = sslCert
        self.client_ports = {}
        self.server_ports = {}
        self.modules = {}
        self.module_abilities = {}
        self.actions = {
            "connect": [],
            "register": [],
            "welcome": [],
            "join": [],
            "joinmessage": [],
            "nick": [],
            "quit": [],
            "topic": [],
            "mode": [],
            "nameslistentry": [],
            "chancreate": [],
            "chandestroy": [],
            "commandextra": [],
            "commandunknown": [],
            "commandpermission": [],
            "metadataupdate": [],
            "recvdata": [],
            "senddata": [],
            "netmerge": [],
            "netsplit": []
        }
        self.commands = {}
        self.channel_modes = [{}, {}, {}, {}]
        self.channel_mode_type = {}
        self.user_modes = [{}, {}, {}, {}]
        self.user_mode_type = {}
        self.prefixes = {}
        self.prefix_symbols = {}
        self.prefix_order = []
        self.server_commands = {}
        self.module_data_cache = {}
        self.server_factory = None
        self.common_modules = set()
        log.msg("Loading module data...")
        try:
            with open("data.yaml", "r") as dataFile:
                self.serialized_data = yaml.safe_load(dataFile)
                if self.serialized_data is None:
                    self.serialized_data = {}
        except IOError:
            self.serialized_data = {}
        self.isupport = {}
        self.usercount = {
            "localmax": 0,
            "globalmax": 0
        }
        log.msg("Loading configuration...")
        self.servconfig = {}
        if not options:
            options = {}
        self.load_options(options)
        self.name = self.servconfig["server_name"]
        log.msg("Loading modules...")
        self.all_module_load()
        self.save_serialized_deferred = None
        self.autoconnect_servers = LoopingCall(self.server_autoconnect)
        self.autoconnect_servers.start(60, now=False) # The server factory isn't added to here yet
        # Fill in the default ISUPPORT dictionary once config and modules are loaded, since some values depend on those
        self.isupport["CASEMAPPING"] = "rfc1459"
        self.isupport["CHANMODES"] = ",".join(["".join(modedict.keys()) for modedict in self.channel_modes])
        self.isupport["CHANNELLEN"] = "64"
        self.isupport["CHANTYPES"] = "#"
        self.isupport["MODES"] = 20
        self.isupport["NETWORK"] = self.servconfig["server_network_name"]
        self.isupport["NICKLEN"] = "32"
        self.isupport["PREFIX"] = "({}){}".format("".join(self.prefix_order), "".join([self.prefixes[mode][0] for mode in self.prefix_order]))
        self.isupport["STATUSMSG"] = "".join([self.prefixes[mode][0] for mode in self.prefix_order])
        self.isupport["TOPICLEN"] = "316"
        self.isupport["USERMODES"] = ",".join(["".join(modedict.keys()) for modedict in self.user_modes])
    
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
                    "cmd_links", "cmd_connect", "cmd_squit", # linked servers
                    
                    # channel modes
                    "cmode_b", "cmode_i", "cmode_k", "cmode_l", "cmode_m", "cmode_n", "cmode_o", "cmode_p", "cmode_s", "cmode_t", "cmode_v",
                    
                    # user modes
                    "umode_i", "umode_s"
                    ]
        ircv3_spec = [ # http://ircv3.atheme.org/
                    "ircv3_cap", # capability mechanism which essentially serves as the base for everything else
                    "ircv3_multi-prefix", "ircv3_sasl", # other IRC 3.1 base extensions
                    "ircv3_account-notify", "ircv3_away-notify", "ircv3_extended-join", "ircv3_tls", # IRC 3.1 optional extensions
                    "ircv3_monitor", "ircv3_metadata" # IRC 3.2 base extensions
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
        log.msg("Rehashing config file and reloading modules")
        try:
            with open(self.config) as f:
                self.load_options(yaml.safe_load(f))
            self.all_module_load()
            self.save_module_data()
        except:
            return False
        return True
    
    def load_options(self, options):
        for var, value in options.iteritems():
            self.servconfig[var] = value
        for var, value in default_options.iteritems():
            if var not in self.servconfig:
                self.servconfig[var] = value
    
    def cleanup(self):
        # Track the disconnections so we know they get done
        deferreds = []
        log.msg("Disconnecting servers...")
        for server in self.servers.values():
            if server.nearHop == self.name:
                server.transport.loseConnection()
                deferreds.append(server.disconnected)
        # Cleanly disconnect all clients
        log.msg("Disconnecting clients...")
        for u in self.users.values():
            u.sendMessage("ERROR", ":Closing Link: {} [Server shutting down]".format(u.hostname), to=None, prefix=None)
            u.socket.transport.loseConnection()
            deferreds.append(u.disconnected)
        log.msg("Unloading modules...")
        for name, spawner in self.modules.iteritems():
            try:
                spawner.cleanup()
            except AttributeError:
                pass # If the module has no extra cleanup to do, that's fine
            try:
                data_to_save, free_data = self.modules[name].data_serialize()
                if data_to_save:
                    self.serialized_data[name] = data_to_save
            except AttributeError:
                pass # If the module has no data to save, that's also fine.
        log.msg("Saving serialized data...")
        if not self.save_module_data():
            self.save_serialized_deferred.addCallback(self.save_serialized)
        deferreds.append(self.save_serialized_deferred)
        # Return deferreds
        log.msg("Waiting on deferreds...")
        self.dead = True
        return DeferredList(deferreds)
    
    def connect_server(self, servername):
        def sendServerHandshake(protocol, password):
            protocol.callRemote(IntroduceServer, name=self.name, password=password, description=self.servconfig["server_description"], version=protocol_version, commonmodules=self.common_modules)
            protocol.sentDataBurst = False
        if servername in self.servers:
            raise RuntimeError ("Server {} is already connected".format(servername))
        if servername not in self.servconfig["serverlinks"]:
            raise RuntimeError ("Server {} is not configured".format(servername))
        servinfo = self.servconfig["serverlinks"][servername]
        if "ip" not in servinfo:
            raise RuntimeError ("Server {} is not properly configured: IP address must be specified".format(servername))
        if "connect" not in servinfo:
            raise RuntimeError ("Server {} is not properly configured: Connection description not provided".format(servername))
        if "incoming_password" not in servinfo or "outgoing_password" not in servinfo:
            raise RuntimeError ("Server {} is not properly configured: Passwords not specified".format(servername))
        try:
            endpoint = clientFromString(reactor, resolveEndpointDescription(servinfo["connect"]))
        except ValueError as e:
            raise RuntimeError ("Server {} is not properly configured: Connection description is not valid ({})".format(servername, e))
        connectDeferred = endpoint.connect(self.server_factory)
        connectDeferred.addCallback(sendServerHandshake, servinfo["outgoing_password"])
        reactor.callLater(30, connectDeferred.cancel) # Time out the connection after 30 seconds
    
    def server_autoconnect(self):
        for server in self.servconfig["serverlink_autoconnect"]:
            if server not in self.servers and server in self.servconfig["serverlinks"]:
                log.msg("Initiating autoconnect to server {}".format(server))
                try:
                    self.connect_server(server)
                except RuntimeError as ex:
                    log.msg("Connection to server failed: {}".format(ex))
    
    def load_module(self, name):
        saved_data = {}
        if name in self.modules:
            saved_data = self.unload_module_data(name)
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
        self.module_abilities[name] = mod_contains
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
            for actiontype, actionfunc in mod_contains["actions"].iteritems():
                if actiontype not in self.actions:
                    self.actions[actiontype] = []
                self.actions[actiontype].append(actionfunc)
        if "server" in mod_contains:
            for commandtype, commandfunc in mod_contains["server"].iteritems():
                if commandtype not in self.server_commands:
                    self.server_commands[commandtype] = []
                self.server_commands[commandtype].append(commandfunc)
        if "common" in mod_contains and mod_contains["common"]:
            self.common_modules.add(name)
        if not saved_data and name in self.serialized_data:
            saved_data = self.serialized_data[name] # present serialized data on first load of session
        if saved_data:
            try:
                mod_spawner.data_unserialize(saved_data)
            except AttributeError:
                pass
        return True
    
    def unload_module_data(self, name):
        data_to_save = {}
        all_data = {}
        try:
            data_to_save, all_data = self.modules[name].data_serialize()
            if data_to_save:
                self.serialized_data[name] = data_to_save
            elif name in self.serialized_data:
                del self.serialized_data[name]
            # Copy data_to_save (if anything) over to all_data (intentionally overwriting any non-permanent items already in all_data)
            # So that we have one dictionary to pass back to data_unserialize if this is being immediately reloaded
            for item, value in data_to_save.iteritems():
                all_data[item] = value
        except AttributeError:
            pass
        try:
            self.modules[name].cleanup()
        except AttributeError:
            pass
        abilities = self.module_abilities[name]
        del self.module_abilities[name]
        del self.modules[name]
        if "commands" in abilities:
            for command, implementation in abilities["commands"].iteritems():
                if self.commands[command] == implementation:
                    del self.commands[command]
        if "modes" in abilities:
            for mode, implementation in abilities["modes"].iteritems():
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
                
                if mode[0] == "c":
                    if modetype == -1:
                        if mode[2] in self.prefixes:
                            del self.prefix_symbols[self.prefixes[mode[2]][0]]
                            del self.prefixes[mode[2]]
                            self.prefix_order.remove(mode[2])
                    else:
                        if mode[2] in self.channel_modes[modetype]:
                            del self.channel_modes[modetype][mode[2]]
                    if mode[2] in self.channel_mode_type:
                        del self.channel_mode_type[mode[2]]
                else:
                    if mode[2] in self.user_modes[modetype]:
                        del self.user_modes[modetype][mode[2]]
                    if mode[2] in self.user_mode_type:
                        del self.user_mode_type[mode[2]]
        if "actions" in abilities:
            for type, function in abilities["actions"].iteritems():
                if type in self.actions and function in self.actions[type]:
                    self.actions[type].remove(function)
        if "server" in abilities:
            for command, function in abilities["server"].iteritems():
                if command in self.server_commands and function in self.server_commands[command]:
                    self.server_commands[command].remove(function)
        return all_data
    
    def save_module_data(self):
        if self.save_serialized_deferred is None or self.save_serialized_deferred.called:
            self.save_serialized_deferred = deferToThread(self.save_serialized)
            return True
        # Otherwise, there's a save currently happening.  This likely means that
        #  1. We don't need to save now; not THAT much has changed
        #  2. Saving now has the potential to cause problems.
        # We could add self.save_serialized as a callback to the Deferred, but there's
        # not a good way to check whether that's done yet without complicating things (and,
        # as mentioned, there's not a need for it).
        # The return value allows us to work around it currently saving already in the
        # cleanup step (when we absolutely must save regardless), as adding a callback
        # in IRCD.cleanup won't hurt anything.
        return False
    
    def save_serialized(self, _ = None):
        with open("data.yaml", "w") as dataFile:
            yaml.dump(self.serialized_data, dataFile, default_flow_style=False)
    
    def saveClientPort(self, desc, port):
        if desc in self.client_ports:
            return
        self.client_ports[desc] = port
    
    def saveServerPort(self, desc, port):
        if desc in self.server_ports:
            return
        self.server_ports[desc] = port
    
    def buildProtocol(self, addr):
        if self.dead:
            return None
        ip = addr.host
        connections = self.peerConnections.get(ip, 0)
        maxConnections = self.servconfig["client_peer_exempt"][ip] if ip in self.servconfig["client_peer_exempt"] else self.servconfig["client_peer_connections"]
        if maxConnections and connections >= maxConnections:
            log.msg("A client at IP address {} has exceeded the session limit".format(ip))
            return None
        self.peerConnections[ip] = connections + 1
        return Factory.buildProtocol(self, addr)

    def unregisterProtocol(self, p):
        ip = p.transport.getPeer().host
        self.peerConnections[ip] -= 1