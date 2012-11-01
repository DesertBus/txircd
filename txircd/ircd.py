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
from txircd.utils import CaseInsensitiveDictionary, DefaultCaseInsensitiveDictionary, VALID_USERNAME, epoch, now, irc_lower, parse_duration, build_duration
from txircd.mode import ChannelModes
from txircd.server import IRCServer
from txircd.service import IRCService
from txircd.desertbus import DBUser
from txircd.stats import StatFactory
from txircd import __version__
from txsockjs.factory import SockJSFactory
import uuid, socket, collections, yaml, os, fnmatch, datetime, pygeoip, json

# Add additional numerics to complement the ones in the RFC
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

Channel = collections.namedtuple("Channel",["name","created","topic","users","mode","log"])

class IRCProtocol(irc.IRC):
    UNREGISTERED_COMMANDS = ["PASS", "USER", "NICK", "PING", "PONG", "QUIT", "CAP"]

    def __init__(self, *args, **kwargs):
        self.type = None
        self.password = None
        self.nick = None
        self.user = None
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
        else:
            self.sendMessage("PING",":{}".format(self.factory.server_name))
    
    def handleCommand(self, command, prefix, params):
        self.factory.stats_data["lines_in"] += 1
        self.factory.stats_data["total_lines_in"] += 1
        log.msg("handleCommand: {!r} {!r} {!r}".format(command, prefix, params))
        if not self.type and command not in self.UNREGISTERED_COMMANDS:
            return self.sendMessage(irc.ERR_NOTREGISTERED, command, ":You have not registered", prefix=self.factory.server_name)
        elif not self.type:
            return irc.IRC.handleCommand(self, command, prefix, params)
        else:
            return self.type.handleCommand(command, prefix, params)
        

    def sendLine(self, line):
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

    def irc_NICK(self, prefix, params):
        if not params:
            self.sendMessage(irc.ERR_NONICKNAMEGIVEN, ":No nickname given", prefix=self.factory.server_name)
        elif not VALID_USERNAME.match(params[0]):
            self.sendMessage(irc.ERR_ERRONEUSNICKNAME, params[0], ":Erroneous nickname", prefix=self.factory.server_name)
        elif params[0] in self.factory.users:
            self.sendMessage(irc.ERR_NICKNAMEINUSE, self.factory.users[params[0]].nickname, ":Nickname is already in use", prefix=self.factory.server_name)
        else:
            lower_nick = irc_lower(params[0])
            expired = []
            for mask, linedata in self.factory.xlines["Q"].iteritems():
                if linedata["duration"] != 0 and epoch(now()) > epoch(linedata["created"]) + linedata["duration"]:
                    expired.append(mask)
                    continue
                if fnmatch.fnmatch(lower_nick, mask):
                    self.sendMessage(irc.ERR_ERRONEUSNICKNAME, self.nick if self.nick else "*", params[0], ":Invalid nickname: {}".format(linedata["reason"]), prefix=self.factory.server_name)
                    return
            for mask in expired:
                del self.factory.xlines["Q"][mask]
            if expired:
                self.factory.save_options()
            self.nick = params[0]
            if self.user:
                try:
                    self.type = self.factory.types["user"](self, self.user, self.password, self.nick)
                except ValueError:
                    self.type = None
                    self.transport.loseConnection()

    def irc_USER(self, prefix, params):
        if len(params) < 4:
            return self.sendMessage(irc.ERR_NEEDMOREPARAMS, "USER", ":Not enough parameters", prefix=self.factory.server_name)
        self.user = params
        if self.nick:
            try:
                self.type = self.factory.types["user"](self, self.user, self.password, self.nick)
            except ValueError:
                self.type = None
                self.transport.loseConnection()

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
        "user": DBUser,
        "server": IRCServer,
        "service": IRCService,
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
        
        self.config = config
        self.version = "txircd.{}".format(__version__)
        self.created = now()
        self.token = uuid.uuid1()
        self.servers = CaseInsensitiveDictionary()
        self.users = CaseInsensitiveDictionary()
        self.whowas = CaseInsensitiveDictionary()
        self.channels = DefaultCaseInsensitiveDictionary(self.ChannelFactory)
        self.peerConnections = {}
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
        return DeferredList(deferreds)
    
    def buildProtocol(self, addr):
        self.stats_data["connections"] += 1
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
        self.peerConnections[ip] = conn + 1
        return Factory.buildProtocol(self, addr)

    def unregisterProtocol(self, p):
        self.stats_data["connections"] -= 1
        peerHost = p.transport.getPeer().host
        self.peerConnections[peerHost] -= 1
        if self.peerConnections[peerHost] == 0:
            del self.peerConnections[peerHost]
    
    def ChannelFactory(self, name):
        logfile = "{}/{}".format(self.app_log_dir,irc_lower(name))
        if not os.path.exists(logfile):
            os.makedirs(logfile)
        c = Channel(name,now(),{"message":None,"author":"","created":now()},CaseInsensitiveDictionary(),ChannelModes(self,None),DailyLogFile("log",logfile))
        c.mode.parent = c
        c.mode.combine("nt",[],name)
        return c
    
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
