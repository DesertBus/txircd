from twisted.enterprise import adbapi
from twisted.internet import reactor
from twisted.internet.defer import Deferred
from twisted.words.protocols import irc
from txircd.modbase import Command
from txircd.server import RegisterUser, RemoveUser, ModuleMessage, SetIdent, SetHost, SetName
from txircd.utils import chunk_message, crypt, irc_lower, now, CaseInsensitiveDictionary
from base64 import b64decode, b64encode
from Crypto.Random.random import getrandbits
from Crypto.Cipher import AES
from Crypto.Cipher import Blowfish
from datetime import datetime
from random import choice
import math, os, random, uuid, yaml

class Service(object):
    class ServiceSocket(object):
        class ServiceTransport(object):
            def loseConnection(self):
                pass
        
        def __init__(self):
            self.transport = self.ServiceTransport()
            self.secure = True
    
    def __init__(self, ircd, nick, ident, host, gecos, helpTexts):
        # We're going to try to keep Service fairly consistent with IRCUser, even if most of these variables will never be used
        # in order to prevent exceptions all over the place
        self.ircd = ircd
        self.socket = self.ServiceSocket()
        self.uuid = str(uuid.uuid1())
        self.password = None
        self.nickname = nick
        self.username = ident
        self.hostname = host
        self.realhost = host
        self.realname = gecos
        self.ip = "127.0.0.1"
        self.server = self.ircd.name
        self.signon = datetime.utcfromtimestamp(1) # Give these pseudoclients a really old time so that they won't be disconnected by remote servers
        self.lastactivity = now()
        self.lastpong = now()
        self.nicktime = datetime.utcfromtimestamp(1)
        self.mode = {}
        self.disconnected = Deferred()
        self.disconnected.callback(None)
        self.registered = 0
        self.metadata = {
            "server": {},
            "user": {},
            "client": {},
            "ext": {},
            "private": {}
        }
        self.cache = {} # Not only do various other modules potentially play with the cache, but we can do what we want with it to store auction data, etc.
        self.help = helpTexts
    
    def addToServers(self):
        for server in self.ircd.servers.itervalues():
            if server.nearHop == self.ircd.name:
                server.callRemote(RegisterUser, uuid=self.uuid, nick=self.nickname, ident=self.username, host=self.hostname, realhost=self.realhost, gecos=self.realname, ip=self.ip, server=self.server, secure=self.socket.secure, signon=1, nickts=1)
    
    def removeFromServers(self):
        for server in self.ircd.servers.itervalues():
            if server.nearHop == self.ircd.name:
                server.callRemote(RemoveUser, user=self.uuid, reason="Unloading module")
    
    def register(self):
        pass
    
    def send_isupport(self):
        pass
    
    def disconnect(self, reason, sourceServer = None):
        if sourceServer is None:
            return
        self.ircd.servers[sourceServer].callRemote(RegisterUser, uuid=self.uuid, nick=self.nickname, ident=self.username, host=self.hostname, realhost=self.realhost, gecos=self.realname, ip=self.ip, server=self.server, secure=self.socket.secure, signon=1, nickts=1)
    
    def sendMessage(self, command, *parameter_list, **kw):
        if command == "PRIVMSG" and "prefix" in kw:
            nick = kw["prefix"][0:kw["prefix"].find("!")]
            user = self.ircd.users[nick]
            params = parameter_list[0].split(" ")
            serviceCommand = params.pop(0).upper().lstrip(":") # Messages sent this way start with a colon
            if serviceCommand == "HELP":
                if not params:
                    helpOut = chunk_message(self.help[0], 80)
                    for line in helpOut:
                        user.sendMessage("NOTICE", ":{}".format(line), prefix=self.prefix())
                    user.sendMessage("NOTICE", ": ", prefix=self.prefix())
                    commands = sorted(self.help[1].keys())
                    for cmd in commands:
                        info = self.help[1][cmd]
                        if info[2] and "o" not in user.mode:
                            continue
                        user.sendMessage("NOTICE", ":\x02{}\x02\t{}".format(cmd.upper(), info[0]), prefix=self.prefix())
                    user.sendMessage("NOTICE", ": ", prefix=self.prefix())
                    user.sendMessage("NOTICE", ":*** End of help", prefix=self.prefix())
                else:
                    helpCmd = params[0]
                    if helpCmd not in self.help[1]:
                        user.sendMessage("NOTICE", ":No help available for \x02{}\x02.".format(helpCmd), prefix=self.prefix())
                    else:
                        info = self.help[1][helpCmd]
                        if info[2] and "o" not in user.mode:
                            user.sendMessage("NOTICE", ":No help available for \x02{}\x02.".format(helpCmd), prefix=self.prefix())
                        else:
                            helpOut = chunk_message(info[1], 80)
                            for line in helpOut:
                                user.sendMessage("NOTICE", ":{}".format(line), prefix=self.prefix())
                            user.sendMessage("NOTICE", ":*** End of \x02{}\x02 help".format(helpCmd), prefix=self.prefix())
            elif serviceCommand in self.help[1] and (not self.help[1][serviceCommand][2] or "o" in user.mode):
                self.ircd.users[nick].handleCommand(serviceCommand, None, params)
            else:
                self.ircd.users[nick].sendMessage("NOTICE", ":Unknown command \x02{}\x02.  Use \x1F/msg {} HELP\x1F for help.".format(serviceCommand, self.nickname), prefix=self.prefix())
    
    def setMetadata(self, namespace, key, value):
        oldValue = self.metadata[namespace][key] if key in self.metadata[namespace] else ""
        self.metadata[namespace][key] = value
        for modfunc in self.ircd.actions["metadataupdate"]:
            modfunc(self, namespace, key, oldValue, value)
    
    def delMetadata(self, namespace, key):
        oldValue = self.metadata[namespace][key]
        del self.metadata[namespace][key]
        for modfunc in self.ircd.actions["metadataupdate"]:
            modfunc(self, namespace, key, oldValue, "")
    
    def prefix(self):
        return "{}!{}@{}".format(self.nickname, self.username, self.hostname)
    
    def hasAccess(self, channel, level):
        return True # access to change anything in all channels
    
    def setUsername(self, newUsername, sourceServer = None):
        if sourceServer:
            self.ircd.servers[sourceServer].callRemote(SetIdent, user=self.uuid, ident=self.username)
    
    def setHostname(self, newHostname, sourceServer = None):
        if sourceServer:
            self.ircd.servers[sourceServer].callRemote(SetHost, user=self.uuid, host=self.hostname)
    
    def setRealname(self, newRealname, sourceServer = None):
        if sourceServer:
            self.ircd.servers[sourceServer].callRemote(SetName, user=self.uuid, gecos=self.realname)
    
    def setMode(self, user, modes, params, displayPrefix = None):
        return ""
    
    def modeString(self, user):
        return "+" # user modes are for chumps
    
    def send_motd(self):
        pass
    
    def send_lusers(self):
        pass
    
    def report_names(self, channel):
        pass
    
    def listname(self, channel, listingUser, representation):
        for modfunc in self.ircd.actions["nameslistentry"]:
            representation = modfunc(self, channel, listingUser, representation)
            if not representation:
                return representation
        return representation
    
    def join(self, channel):
        pass
    
    def leave(self, channel):
        pass
    
    def nick(self, newNick):
        pass


class NickServAlias(Command):
    def onUse(self, user, data):
        user.handleCommand("PRIVMSG", None, [self.ircd.servconfig["services_nickserv_nick"], " ".join(data["params"])])

class ChanServAlias(Command):
    def onUse(self, user, data):
        user.handleCommand("PRIVMSG", None, [self.ircd.servconfig["services_chanserv_nick"], " ".join(data["params"])])

class BidServAlias(Command):
    def onUse(self, user, data):
        user.handleCommand("PRIVMSG", None, [self.ircd.servconfig["services_bidserv_nick"], " ".join(data["params"])])


class NSIdentifyCommand(Command):
    def __init__(self, module, service):
        self.module = module
        self.nickserv = service
    
    def onUse(self, user, data):
        self.module.auth(user, data["email"], data["password"])
    
    def processParams(self, user, params):
        if not params:
            user.sendMessage("NOTICE", ":Usage: \x02IDENTIFY \x1Femail:password", prefix=self.nickserv.prefix())
            return {}
        if len(params) >= 2 and ":" not in params[0]:
            return {
                "user": user,
                "email": params[0],
                "password": params[1]
            }
        try:
            email, password = params[0].split(":")
        except ValueError:
            user.sendMessage("NOTICE", ":Usage: \x02IDENTIFY \x1Femail:password", prefix=self.nickserv.prefix())
            return {}
        return {
            "user": user,
            "email": email,
            "password": password
        }

class NSGhostCommand(Command):
    def __init__(self, module, service):
        self.module = module
        self.nickserv = service
    
    def onUse(self, user, data):
        targetUser = data["targetuser"]
        if "accountid" in targetUser.cache and targetUser.cache["accountid"] == user.cache["accountid"]:
            targetUser.disconnect("Killed (GHOST command issued by {})".format(user.nickname))
            user.sendMessage("NOTICE", ":{} has been disconnected.".format(targetUser.nickname), prefix=self.nickserv.prefix())
        else:
            d = self.module.query("SELECT nick FROM ircnicks WHERE donor_id = {0} AND nick = {0}", user.cache["accountid"], irc_lower(targetUser.nickname))
            d.addCallback(self.ghostSuccess, user, targetUser)
            d.addErrback(self.module.exclaimServerError, user, self.nickserv)
    
    def processParams(self, user, params):
        if "accountid" not in user.cache:
            user.sendMessage("NOTICE", ":You must be logged in to do that.", prefix=self.nickserv.prefix())
            return {}
        if not params:
            user.sendMessage("NOTICE", ":Usage: \x02GHOST \x1Fnickname", prefix=self.nickserv.prefix())
            return {}
        if params[0] not in self.ircd.users:
            user.sendMessage("NOTICE", ":No user is connected with that nickname.", prefix=self.nickserv.prefix())
            return {}
        targetUser = self.ircd.users[params[0]]
        if user == targetUser:
            user.sendMessage("NOTICE", ":That's you!  You can't ghost yourself.", prefix=self.nickserv.prefix())
            return {}
        return {
            "user": user,
            "targetuser": targetUser
        }
    
    def ghostSuccess(self, result, user, targetUser):
        if result:
            targetUser.disconnect("Killed (GHOST command used by {})".format(user.nickname))
            user.sendMessage("NOTICE", ":{} has been disconnected.".format(targetUser.nickname), prefix=self.nickserv.prefix())
        else:
            user.sendMessage("NOTICE", ":That nick does not belong to you.", prefix=self.nickserv.prefix())

class NSLoginCommand(Command):
    def __init__(self, module, service):
        self.module = module
        self.nickserv = service
    
    def onUse(self, user, data):
        self.module.auth(user, data["email"], data["password"])
    
    def processParams(self, user, params):
        if not params or len(params) < 2:
            user.sendMessage("NOTICE", ":Usage: \x02LOGIN \x1Femail\x1F \x1Fpassword", prefix=self.nickserv.prefix())
            return {}
        return {
            "user": user,
            "email": params[0],
            "password": params[1]
        }

class NSLogoutCommand(Command):
    def __init__(self, module, service):
        self.module = module
        self.nickserv = service
    
    def onUse(self, user, data):
        del user.cache["accountid"]
        user.delMetadata("ext", "accountname")
        self.module.checkNick(user)
        self.module.unregistered(user)
        user.sendMessage("NOTICE", ":You are now logged out.", prefix=self.nickserv.prefix())
    
    def processParams(self, user, params):
        if "accountid" not in user.cache:
            user.sendMessage("NOTICE", ":You're already logged out.", prefix=self.nickserv.prefix())
            return {}
        return {
            "user": user
        }

class NSDropCommand(Command):
    def __init__(self, module, service):
        self.module = module
        self.nickserv = service
    
    def onUse(self, user, data):
        d = self.module.db.runInteraction(self.dropNicknameTransaction, user.cache["accountid"], data["nick"], self.ircd.servconfig["servdb_marker"])
        d.addCallback(self.confirmDropped, user, data["nick"])
        d.addErrback(self.module.exclaimServerError, user, self.nickserv)
    
    def processParams(self, user, params):
        if "accountid" not in user.cache:
            user.sendMessage("NOTICE", ":You must be logged in to use the DROP command.", prefix=self.nickserv.prefix())
            return {}
        if not params:
            user.sendMessage("NOTICE", ":Usage: \x02DROP \x1Fnickname", prefix=self.nickserv.prefix())
            return {}
        return {
            "user": user,
            "nick": params[0]
        }
    
    def dropNicknameTransaction(self, transaction, id, nick, db_marker):
        query = "DELETE FROM ircnicks WHERE donor_id = {0} AND nick = {0}".format(db_marker)
        transaction.execute(query, (id, nick))
        return transaction.rowcount
    
    def confirmDropped(self, result, user, nick):
        if result:
            user.sendMessage("NOTICE", ":The nickname {} has been dropped from your account.".format(nick), prefix=self.nickserv.prefix())
        else:
            user.sendMessage("NOTICE", ":Could not drop nickname {} from your account.  Ensure that it belongs to you.".format(nick), prefix=self.nickserv.prefix())

class NSNicklistCommand(Command):
    def __init__(self, module, service):
        self.module = module
        self.nickserv = service
    
    def onUse(self, user, data):
        d = self.module.query("SELECT nick FROM ircnicks WHERE donor_id = {0}", user.cache["accountid"])
        d.addCallback(self.showNicks, user)
        d.addErrback(self.module.exclaimServerError, user, self.nickserv)
    
    def processParams(self, user, params):
        if "accountid" not in user.cache:
            user.sendMessage("NOTICE", ":You must be logged in to see your nicknames.", prefix=self.nickserv.prefix())
            return {}
        return {
            "user": user
        }
    
    def showNicks(self, results, user):
        user.sendMessage("NOTICE", ":Registered Nicknames: {}".format(", ".join([n[0] for n in results])), prefix=self.nickserv.prefix())

class NSCertCommand(Command):
    def __init__(self, module, service):
        self.module = module
        self.nickserv = service
    
    def onUse(self, user, data):
        accountid = user.cache["accountid"]
        if data["subcmd"] == "LIST":
            user.sendMessage("NOTICE", ":Certificate list:", prefix=self.nickserv.prefix())
            if accountid in self.nickserv.cache["certfp"]:
                for cert in self.nickserv.cache["certfp"][accountid]:
                    user.sendMessage("NOTICE", ":{}".format(cert), prefix=self.nickserv.prefix())
            user.sendMessage("NOTICE", ":*** End of certificate list", prefix=self.nickserv.prefix())
        elif data["subcmd"] == "ADD":
            if self.module.addCert(user, data["certfp"]):
                user.sendMessage("NOTICE", ":Certificate fingerprint {} added to your account.".format(data["certfp"]), prefix=self.nickserv.prefix())
            else:
                user.sendMessage("NOTICE", ":Certificate fingerprint {} could not be added to your account.".format(data["certfp"]), prefix=self.nickserv.prefix())
        else:
            certfp = data["certfp"]
            if certfp in self.nickserv.cache["certfp"][accountid]:
                self.nickserv.cache["certfp"][accountid].remove(certfp)
                user.sendMessage("NOTICE", ":Certificate fingerprint {} has been removed from your account.".format(certfp), prefix=self.nickserv.prefix())
            else:
                user.sendMessage("NOTICE", ":Certificate fingerprint {} was not associated with your account.".format(certfp), prefix=self.nickserv.prefix())
    
    def processParams(self, user, params):
        if "accountid" not in user.cache:
            user.sendMessage("NOTICE", ":You must be logged in to use that command.", prefix=self.nickserv.prefix())
            return {}
        if not params:
            user.sendMessage("NOTICE", ":Usage: \x02CERT \x1F{LIST|ADD|DEL}\x1F \x1F[certificate fingerprint]", prefix=self.nickserv.prefix())
            return {}
        subcmd = params[0].upper()
        if subcmd not in ["LIST", "ADD", "DEL"]:
            user.sendMessage("NOTICE", ":Usage: \x02CERT \x1F{LIST|ADD|DEL}\x1F \x1F[certificate fingerprint]", prefix=self.nickserv.prefix())
            return {}
        if subcmd == "LIST":
            return {
                "user": user,
                "subcmd": "LIST"
            }
        if len(params) < 2:
            user.sendMessage("NOTICE", ":Usage: \x02CERT \x1F{}\x1F \x1Fcertificate fingerprint\x1F".format(subcmd), prefix=self.nickserv.prefix())
            return {}
        return {
            "user": user,
            "subcmd": subcmd,
            "certfp": params[1].lower()
        }


class CSRegisterCommand(Command):
    def __init__(self, module, service):
        self.module = module
        self.chanserv = service
    
    def onUse(self, user, data):
        channel = data["targetchan"]
        self.chanserv.cache["registered"][channel.name] = {"founder": user.cache["accountid"], "access": {}, "registertime": now()}
        user.sendMessage("NOTICE", ":The channel {} has been registered under your account.".format(channel.name), prefix=self.chanserv.prefix())
    
    def processParams(self, user, params):
        if "accountid" not in user.cache:
            user.sendMessage("NOTICE", ":You must be logged in to register a channel.", prefix=self.chanserv.prefix())
            return {}
        if not params:
            user.sendMessage("NOTICE", ":Usage: \x02REGISTER \x1Fchannel", prefix=self.chanserv.prefix())
            return {}
        if params[0] not in self.ircd.channels:
            user.sendMessage("NOTICE", ":You cannot register a channel that does not exist.", prefix=self.chanserv.prefix())
            return {}
        if params[0] in self.chanserv.cache["registered"]:
            user.sendMessage("NOTICE", ":That channel is already registered.", prefix=self.chanserv.prefix())
            return {}
        cdata = self.ircd.channels[params[0]]
        if not user.hasAccess(cdata, "o") and "o" not in user.mode:
            user.sendMessage("NOTICE", ":You must be a channel operator to register that channel.", prefix=self.chanserv.prefix())
            return {}
        return {
            "user": user,
            "targetchan": cdata
        }

class CSAccessCommand(Command):
    def __init__(self, module, service):
        self.module = module
        self.chanserv = service
    
    def onUse(self, user, data):
        if "targetgroup" in data:
            accessID = data["targetgroup"]
        elif "targetaccount" in data:
            accessID = data["targetaccount"]
        elif "targetnick" in data:
            d = self.module.query("SELECT donor_id FROM ircnicks WHERE nick = {0} LIMIT 1", data["targetnick"])
            d.addCallback(self.changeAccess, data["targetnick"], user, data["targetchan"], data["flags"])
            d.addErrback(self.module.exclaimServerError, user, self.chanserv)
            return
        else:
            accessList = self.chanserv.cache["registered"][data["targetchan"]]["access"]
            if not accessList:
                user.sendMessage("NOTICE", ":The access list is empty.", prefix=self.chanserv.prefix())
            else:
                convertEntries = [u for u in accessList.iterkeys() if u.isdigit()]
                # For this list, we assume the lowest ID number in the ircnicks table is for the main nick of the account
                d = self.module.query("SELECT n1.donor_id, n1.nick FROM ircnicks n1 JOIN (SELECT MIN(id) minID, donor_id FROM ircnicks GROUP BY donor_id) n2 ON n1.id = n2.minID WHERE {}".format(" OR ".join(["n1.donor_id = {0}" for i in convertEntries])), *convertEntries)
                d.addCallback(self.listAccess, user, accessList)
                d.addErrback(self.module.exclaimServerError, user, self.chanserv)
            return
        self.changeAccess([[accessID]], accessID, user, data["targetchan"], data["flags"])
    
    def processParams(self, user, params):
        if not params:
            user.sendMessage("NOTICE", ":Usage: \x02ACCESS \x1Fchannel\x1F [\x1Faccount|nick|group\x1F \x1Fflags\x1F]", prefix=self.chanserv.prefix())
            return {}
        if params[0] not in self.chanserv.cache["registered"]:
            user.sendMessage("NOTICE", ":{} is not registered.".format(data["targetchan"]), prefix=self.chanserv.prefix())
            return {}
        if len(params) < 3:
            return {
                "user": user,
                "targetchan": params[0]
            }
        can_modify = False
        if "o" in user.mode:
            can_modify = True
        elif "accountid" in user.cache:
            if user.cache["accountid"] == self.chanserv.cache["registered"][params[0]]["founder"]:
                can_modify = True
            else:
                for acct, flags in self.chanserv.cache["registered"][params[0]]["access"].iteritems():
                    if (acct == "~r" or acct == user.cache["accountid"]) and "A" in flags:
                        can_modify = True
        if not can_modify:
            user.sendMessage("NOTICE", ":You do not have access to change the permissions of that channel.", prefix=self.chanserv.prefix())
            return {}
        if params[1] in ["~o", "~r"]:
            return {
                "user": user,
                "targetchan": params[0],
                "targetgroup": params[1],
                "flags": params[2]
            }
        if params[1] in self.ircd.users:
            udata = self.ircd.users[params[1]]
            if "accountid" not in udata.cache:
                user.sendMessage("NOTICE", ":The target user is not identified to any account.", prefix=self.chanserv.prefix())
                return {}
            return {
                "user": user,
                "targetchan": params[0],
                "targetaccount": udata.cache["accountid"],
                "flags": params[2]
            }
        if params[1].isdigit():
            return {
                "user": user,
                "targetchan": params[0],
                "targetaccount": params[1],
                "flags": params[2]
            }
        return {
            "user": user,
            "targetchan": params[0],
            "targetnick": params[1],
            "flags": params[2]
        }
    
    def listAccess(self, results, user, access):
        accessList = access.copy() # Ensure the original access list is not modified as we delete out of this one
        for result in results:
            id = str(result[0])
            if id in accessList:
                user.sendMessage("NOTICE", ":  {}: +{}".format(result[1], accessList[id]), prefix=self.chanserv.prefix())
            del accessList[id]
        for id, flags in accessList.iteritems(): # Everything not shown from the results of the SQL query
            user.sendMessage("NOTICE", ":  {}: +{}".format(id, flags), prefix=self.chanserv.prefix())
        user.sendMessage("NOTICE", ":End of ACCESS list", prefix=self.chanserv.prefix())
    
    def changeAccess(self, result, display, user, channel, flags):
        if not result:
            user.sendMessage("NOTICE", ":The given nickname is not registered.", prefix=self.chanserv.prefix())
            return
        accessID = str(result[0][0])
        try:
            flagSet = list(self.chanserv.cache["registered"][channel]["access"][accessID])
        except KeyError:
            flagSet = []
        adding = True
        for flag in flags:
            if flag == "+":
                adding = True
            elif flag == "-":
                adding = False
            elif flag in self.ircd.prefix_order or flag == "A":
                if adding and flag not in flagSet:
                    flagSet.append(flag)
                elif not adding and flag in flagSet:
                    flagSet.remove(flag)
        if flagSet:
            self.chanserv.cache["registered"][channel]["access"][accessID] = "".join(flagSet)
        else:
            try:
                del self.chanserv.cache["registered"][channel]["access"][accessID]
            except KeyError:
                pass # If it was already not specified somehow, go ahead and remove it
        user.sendMessage("NOTICE", ":The flags for {} have been changed to +{}".format(display, "".join(flagSet)), prefix=self.chanserv.prefix())

class CSCdropCommand(Command):
    def __init__(self, module, service):
        self.module = module
        self.chanserv = service
    
    def onUse(self, user, data):
        del self.chanserv.cache["registered"][data["channel"]]
        user.sendMessage("NOTICE", ":The channel \x02{}\x02 has been dropped.".format(data["channel"]), prefix=self.chanserv.prefix())
    
    def processParams(self, user, params):
        if "accountid" not in user.cache:
            user.sendMessage("NOTICE", ":You must be logged in to drop a channel.", prefix=self.chanserv.prefix())
            return {}
        if not params:
            user.sendMessage("NOTICE", ":Usage: \x02CDROP \x1Fchannel", prefix=self.chanserv.prefix())
            return {}
        if params[0] not in self.chanserv.cache["registered"]:
            user.sendMessage("NOTICE", ":The channel \x02{}\x02 isn't registered.".format(params[0]), prefix=self.chanserv.prefix())
            return {}
        if user.cache["accountid"] != self.chanserv.cache["registered"][params[0]]["founder"] and "o" not in user.mode:
            user.sendMessage("NOTICE", ":You must be the channel founder in order to drop it.", prefix=self.chanserv.prefix())
            return {}
        return {
            "user": user,
            "channel": params[0]
        }


class BSStartCommand(Command):
    def __init__(self, module, service):
        self.module = module
        self.bidserv = service
    
    def onUse(self, user, data):
        d = self.module.query("SELECT id, name, sold, starting_bid FROM prizes WHERE id = {0}", data["auction"])
        d.addCallback(self.auctionStart, user, data["auction"])
        d.addErrback(self.module.exclaimServerError, user, self.bidserv)
    
    def processParams(self, user, params):
        if "o" not in user.mode:
            user.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - You do not have the correct operator privileges")
            return {}
        if "auction" in self.bidserv.cache:
            user.sendMessage("NOTICE", ":You cannot start an auction when one is currently in progress.", prefix=self.bidserv.prefix())
            return {}
        if not params:
            user.sendMessage("NOTICE", ":Usage: \x02START \x1FauctionID", prefix=self.bidserv.prefix())
            return {}
        try:
            auctionID = int(params[0])
        except ValueError:
            user.sendMessage("NOTICE", ":The auction ID given is not valid.", prefix=self.bidserv.prefix())
            return {}
        return {
            "user": user,
            "auction": auctionID
        }
    
    def auctionStart(self, results, user, auctionID):
        if not results:
            user.sendMessage("NOTICE", ":Could not find the item ID {}".format(auctionID), prefix=self.bidserv.prefix())
            return
        if results[0][2]:
            user.sendMessage("NOTICE", ":The item {} ({}) has already been sold.".format(results[0][0], results[0][1]), prefix=self.bidserv.prefix())
            return
        self.bidserv.cache["auction"] = {
            "item": int(results[0][0]),
            "name": results[0][1],
            "highbid": float(results[0][3]),
            "highbidder": "Nobody",
            "highbidderid": None,
            "startbid": float(results[0][3]),
            "bids": [],
            "called": 0
        }
        lines = [] # The lines array here serves as a cache for the lines so that the format isn't applied repeatedly on every iteration
        lines.append(":\x02\x034Starting Auction for Lot #{}: \"{}\"\x02 - Called by {}".format(results[0][0], results[0][1], user.nickname))
        lines.append(":\x02\x034Item info at http://desertbus.org/live-auction/{}".format(results[0][0]))
        lines.append(":\x02\x034Make bids with \x1F/bid ###.## [smack talk]")
        if "services_bidserv_increment" in self.ircd.servconfig:
            lines.append(":\x02\x034The minimum increment between bids is ${:,.2f}".format(self.ircd.servconfig["services_bidserv_increment"]))
        lines.append(":\x02\x034Only registered donors can bid - https://donor.desertbus.org/")
        lines.append(":\x02\x034Please do not make any fake bids")
        lines.append(":\x02\x034Beginning bidding at ${:,.2f}".format(float(results[0][3])))
        for channel in self.ircd.channels.itervalues():
            for line in lines:
                channel.sendChannelMessage("PRIVMSG", line, prefix=self.bidserv.prefix())
        user.sendMessage("NOTICE", ":The auction has been started.", prefix=self.bidserv.prefix())

class BSStopCommand(Command):
    def __init__(self, module, service):
        self.module = module
        self.bidserv = service
    
    def onUse(self, user, data):
        try:
            with open(self.failedLogName(self.bidserv.cache["auction"]["item"]), "w") as logFile:
                yaml.dump(self.bidserv.cache["auction"], logFile, default_flow_style=False)
        except IOError:
            user.sendMessage("NOTICE", ":The auction logs could not be written.", prefix=self.bidserv.prefix())
        itemName = self.bidserv.cache["auction"]["name"]
        cancelMsg = ":\x02\x034Auction for {} canceled.\x02 - Called by {}".format(itemName, user.nickname)
        for channel in self.ircd.channels.itervalues():
            channel.sendChannelMessage("PRIVMSG", cancelMsg, prefix=self.bidserv.prefix())
        del self.bidserv.cache["auction"]
        user.sendMessage("NOTICE", ":The auction has been canceled.", prefix=self.bidserv.prefix())
    
    def processParams(self, user, params):
        if "o" not in user.mode:
            user.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - You do not have the correct operator privileges")
            return {}
        if "auction" not in self.bidserv.cache:
            user.sendMessage("NOTICE", ":There is not an auction going on now.", prefix=self.bidserv.prefix())
            return {}
        return {
            "user": user
        }
    
    def failedLogName(self, id):
        log = "{}/auction_stopped-{!s}.log".format(self.ircd.servconfig["app_log_dir"], id)
        count = 1
        while os.path.exists(log):
            log = "{}/auction_stopped-{!s}-{!s}.log".format(self.ircd.servconfig["app_log_dir"], id, count)
            count += 1
        return log

class BSBidCommand(Command):
    def __init__(self, module, service):
        self.module = module
        self.bidserv = service
    
    def onUse(self, user, data):
        bid = data["bid"]
        madness = ""
        if "services_bidserv_madness_levels" in self.ircd.servconfig:
            levels = sorted(self.ircd.servconfig["services_bidserv_madness_levels"].items(), key=lambda t: t[0])
            for amount, name in levels:
                if amount <= self.bidserv.cache["auction"]["highbid"] or bid < amount:
                    continue
                if "services_bidserv_madness_show_all" in self.ircd.servconfig and self.ircd.servconfig["services_bidserv_madness_show_all"]:
                    madness += "{}! ".format(name)
                else:
                    madness = "{}! ".format(name)
        if self.bidserv.cache["auction"]["highbidderid"] == user.cache["accountid"] and "services_bidserv_space_bid" in self.ircd.servconfig:
            madness += "{}! ".format(self.ircd.servconfig["services_bidserv_space_bid"])
        
        bidMsg = ":\x02\x034{}{} has the high bid of ${:,.2f}! \x0312{}".format(madness, user.nickname, bid, data["smacktalk"])
        self.bidserv.cache["auction"]["called"] = 0
        self.bidserv.cache["auction"]["bids"].append({
            "bid": bid,
            "bidder": user.cache["accountid"],
            "nick": user.nickname
        })
        self.bidserv.cache["auction"]["highbid"] = bid
        self.bidserv.cache["auction"]["highbidder"] = user.nickname
        self.bidserv.cache["auction"]["highbidderid"] = user.cache["accountid"]
        for channel in self.ircd.channels.itervalues():
            channel.sendChannelMessage("PRIVMSG", bidMsg, prefix=self.bidserv.prefix())
    
    def processParams(self, user, params):
        if "accountid" not in user.cache:
            user.sendMessage("NOTICE", ":You must be logged in to bid.", prefix=self.bidserv.prefix())
            return {}
        if "auction" not in self.bidserv.cache:
            user.sendMessage("NOTICE", ":There is not an auction going on right now.", prefix=self.bidserv.prefix())
            return {}
        if not params:
            user.sendMessage("NOTICE", ":Usage: \x02BID \x1Famount\x1F \x1F[smack talk]", prefix=self.bidserv.prefix())
            return {}
        try:
            bid = float(params[0].lstrip("$"))
            bid = round(bid, 2)
        except ValueError:
            user.sendMessage("NOTICE", ":Bid amount must be a valid decimal.", prefix=self.bidserv.prefix())
            return {}
        if math.isnan(bid) or math.isinf(bid):
            user.sendMessage("NOTICE", ":Bid amount must be a valid decimal.", prefix=self.bidserv.prefix())
            return {}
        if "services_bidserv_limit" in self.ircd.servconfig and bid > self.ircd.servconfig["services_bidserv_limit"]:
            user.sendMessage("NOTICE", ":Let's be honest, here.  You don't really have ${:,.2f}, do you?  I mean, do you \x02really\x02 have that much money on you?".format(bid), prefix=self.bidserv.prefix())
            return {}
        if bid <= self.bidserv.cache["auction"]["highbid"]:
            user.sendMessage("NOTICE", ":The high bid is already ${:,.2f}.".format(self.bidserv.cache["auction"]["highbid"]), prefix=self.bidserv.prefix())
            return {}
        if self.bidserv.cache["auction"]["bids"] and "services_bidserv_increment" in self.ircd.servconfig and bid < self.bidserv.cache["auction"]["highbid"] + self.ircd.servconfig["services_bidserv_increment"]:
            user.sendMessage("NOTICE", ":The minimum bid increment is ${:,.2f}.".format(self.ircd.servconfig["services_bidserv_increment"]), prefix=self.bidserv.prefix())
            return {}
        return {
            "user": user,
            "bid": bid,
            "smacktalk": " ".join(params[1:]).strip()[:250]
        }

class BSRevertCommand(Command):
    def __init__(self, module, service):
        self.module = module
        self.bidserv = service
    
    def onUse(self, user, data):
        badBid = self.bidserv.cache["auction"]["bids"].pop()
        if self.bidserv.cache["auction"]["bids"]:
            newHighBid = self.bidserv.cache["auction"]["bids"][-1]["bid"]
            newHighBidder = self.bidserv.cache["auction"]["bids"][-1]["nick"]
            newHighBidderID = self.bidserv.cache["auction"]["bids"][-1]["bidder"]
        else:
            newHighBid = self.bidserv.cache["auction"]["startbid"]
            newHighBidder = "Nobody"
            newHighBidderID = None
        revertMsg = ":\x02\x034Bid for ${:,.2f} by {} removed.  The new highest bid is for ${:,.2f} by {}!\x02 - Called by {}".format(badBid["bid"], badBid["nick"], newHighBid, newHighBidder, user.nickname)
        self.bidserv.cache["auction"]["highbid"] = newHighBid
        self.bidserv.cache["auction"]["highbidder"] = newHighBidder
        self.bidserv.cache["auction"]["highbidderid"] = newHighBidderID
        self.bidserv.cache["auction"]["called"] = 0
        for channel in self.ircd.channels.itervalues():
            channel.sendChannelMessage("PRIVMSG", revertMsg, prefix=self.bidserv.prefix())
    
    def processParams(self, user, params):
        if "o" not in user.mode:
            user.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - You do not have the correct operator privileges")
            return {}
        if "auction" not in self.bidserv.cache:
            user.sendMessage("NOTICE", ":There is not an auction going on right now.", prefix=self.bidserv.prefix())
            return {}
        if not self.bidserv.cache["auction"]["bids"]:
            user.sendMessage("NOTICE", ":No bids have been made yet!", prefix=self.bidserv.prefix())
            return {}
        return {
            "user": user
        }

class BSOnceCommand(Command):
    def __init__(self, module, service):
        self.module = module
        self.bidserv = service
    
    def onUse(self, user, data):
        self.bidserv.cache["auction"]["called"] = 1
        onceMsg = ":\x02\x034Going Once! To {} for ${:,.2f}!\x02 - Called by {}".format(self.bidserv.cache["auction"]["highbidder"], self.bidserv.cache["auction"]["highbid"], user.nickname)
        for channel in self.ircd.channels.itervalues():
            channel.sendChannelMessage("PRIVMSG", onceMsg, prefix=self.bidserv.prefix())
    
    def processParams(self, user, params):
        if "o" not in user.mode:
            user.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - You do not have the correct operator privileges")
            return {}
        if "auction" not in self.bidserv.cache:
            user.sendMessage("NOTICE", ":There is not an auction going on right now.", prefix=self.bidserv.prefix())
            return {}
        if self.bidserv.cache["auction"]["called"] != 0:
            user.sendMessage("NOTICE", ":Now is not the time to call going once.  (Current state: {})".format(self.bidserv.cache["auction"]["called"]), prefix=self.bidserv.prefix())
            return {}
        return {
            "user": user
        }

class BSTwiceCommand(Command):
    def __init__(self, module, service):
        self.module = module
        self.bidserv = service
    
    def onUse(self, user, data):
        self.bidserv.cache["auction"]["called"] = 2
        twiceMsg = ":\x02\x034Going Twice! To {} for ${:,.2f}!\x02 - Called by {}".format(self.bidserv.cache["auction"]["highbidder"], self.bidserv.cache["auction"]["highbid"], user.nickname)
        for channel in self.ircd.channels.itervalues():
            channel.sendChannelMessage("PRIVMSG", twiceMsg, prefix=self.bidserv.prefix())
    
    def processParams(self, user, params):
        if "o" not in user.mode:
            user.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - You do not have the correct operator privileges")
            return {}
        if "auction" not in self.bidserv.cache:
            user.sendMessage("NOTICE", ":There is not an auction going on right now.", prefix=self.bidserv.prefix())
            return {}
        if self.bidserv.cache["auction"]["called"] != 1:
            user.sendMessage("NOTICE", ":Now is not the time to call going twice.  (Current state: {})".format(self.bidserv.cache["auction"]["called"]), prefix=self.bidserv.prefix())
            return {}
        return {
            "user": user
        }

class BSSoldCommand(Command):
    def __init__(self, module, service):
        self.module = module
        self.bidserv = service
    
    def onUse(self, user, data):
        try:
            with open(self.logname(self.bidserv.cache["auction"]["item"]), "w") as logFile:
                yaml.dump(self.bidserv.cache["auction"], logFile, default_flow_style=False)
        except IOError:
            user.sendMessage("NOTICE", ":The log file for this auction could not be written.", prefix=self.bidserv.prefix())
        soldMsg = ":\x02\x034Sold! {} to {} for ${:,.2f}!\x02 - Called by {}".format(self.bidserv.cache["auction"]["name"], self.bidserv.cache["auction"]["highbidder"], self.bidserv.cache["auction"]["highbid"], user.nickname)
        for channel in self.ircd.channels.itervalues():
            channel.sendChannelMessage("PRIVMSG", soldMsg, prefix=self.bidserv.prefix())
        if self.bidserv.cache["auction"]["highbidder"] in self.ircd.users:
            udata = self.ircd.users[self.bidserv.cache["auction"]["highbidder"]]
            if "accountid" in udata.cache and udata.cache["accountid"] == self.bidserv.cache["auction"]["highbidderid"]:
                udata.sendMessage("NOTICE", ":Congratulations!  You won \"{}\"!  Please log into your donor account and visit https://desertbus.org/donate?type=auction&prize={!s} to pay for your prize.".format(self.bidserv.cache["auction"]["name"], self.bidserv.cache["auction"]["item"]), prefix=self.bidserv.prefix())
        d = self.module.query("UPDATE prizes SET donor_id = {0}, sold_amount = {0}, sold = 1 WHERE id = {0}", self.bidserv.cache["auction"]["highbidderid"], self.bidserv.cache["auction"]["highbid"], self.bidserv.cache["auction"]["item"])
        d.addErrback(self.reportError, user, self.bidserv.cache["auction"])
        del self.bidserv.cache["auction"]
    
    def processParams(self, user, params):
        if "o" not in user.mode:
            user.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - You do not have the correct operator privileges")
            return {}
        if "auction" not in self.bidserv.cache:
            user.sendMessage("NOTICE", ":There is not an auction going on right now.", prefix=self.bidserv.prefix())
            return {}
        if self.bidserv.cache["auction"]["called"] != 2:
            user.sendMessage("NOTICE", ":Now is not the time to call sold.  (Current state: {})".format(self.bidserv.cache["auction"]["called"]), prefix=self.bidserv.prefix())
            return {}
        return {
            "user": user
        }
    
    def logname(self, id):
        log = "{}/auction_{!s}.log".format(self.ircd.servconfig["app_log_dir"], id)
        count = 1
        while os.path.exists(log):
            log = "{}/auction_{!s}-{!s}.log".format(self.ircd.servconfig["app_log_dir"], id, count)
            count += 1
        return log
    
    def reportError(self, results, user, auctionData):
        user.sendMessage("NOTICE", ":An error occurred updating the database with the winner ({} with ID {} for amount ${:,.2f}).".format(auctionData["highbidder"], auctionData["highbidderid"], auctionData["highbid"]), prefix=self.bidserv.prefix())

class BSHighbidderCommand(Command):
    def __init__(self, module, service):
        self.module = module
        self.bidserv = service
    
    def onUse(self, user, data):
        user.sendMessage("NOTICE", ":The current high bid is ${:,.2f} by {}.".format(self.bidserv.cache["auction"]["highbid"], self.bidserv.cache["auction"]["highbidder"]), prefix=self.bidserv.prefix())
    
    def processParams(self, user, params):
        if "auction" not in self.bidserv.cache:
            user.sendMessage("NOTICE", ":There is not an auction going on right now.", prefix=self.bidserv.prefix())
            return {}
        return {
            "user": user
        }

class BSCurrentAuctionCommand(Command):
    def __init__(self, module, service):
        self.module = module
        self.bidserv = service
    
    def onUse(self, user, data):
        user.sendMessage("NOTICE", ":The item currently up for auction is lot #{} ({}).  http://desertbus.org/live-auction/{}".format(self.bidserv.cache["auction"]["item"], self.bidserv.cache["auction"]["name"], self.bidserv.cache["auction"]["item"]), prefix=self.bidserv.prefix())
    
    def processParams(self, user, params):
        if "auction" not in self.bidserv.cache:
            user.sendMessage("NOTICE", ":There is not an auction running at this time.", prefix=self.bidserv.prefix())
            return {}
        return {
            "user": user
        }


class Spawner(object):
    def __init__(self, ircd):
        self.ircd = ircd
        self.db = None
        self.helpText = {
            "nickserv": ["NickServ matches your IRC nickname to your Donor account, allowing for a painless auction process, as well as the peace of mind that nobody can use your nickname but you.", CaseInsensitiveDictionary()],
            "chanserv": ["ChanServ allows managing channels to ease slightly the process of running this thing.", CaseInsensitiveDictionary()],
            "bidserv": ["BidServ handles all of our fancy schmancy auction business and serves as the interface directly to auctions.", CaseInsensitiveDictionary()]
        }
        # Help text values:
        # [ short description, long description, oper only ]
        # The short description should be short and fit on one line.  Further details can be relegated to the long description.
        # The long description should be written in a manner suitable to be passed to chunk_message (i.e. it accepts \n to signify a line break
        # and will split lines automatically; any other characters allowed in a message should be fine).
        # Set the oper-only parameter to True to hide the command from non-opers.  The actual command output should claim it doesn't
        # know that command to non-opers; this system in the help text helps facilitate that.
        self.helpText["nickserv"][1]["HELP"] = ["Shows command help", "Syntax: \x02HELP \x1F[command]\x1F\x02\n\nDisplays command help.  With the optional command parameter, displays help for the given command.", False]
        self.helpText["nickserv"][1]["IDENTIFY"] = ["Backward-compatible version of LOGIN", "Syntax: \x02IDENTIFY \x1Femail:password\x1F\x02\n\nLogs into a donor account with the specified email and password.  If it isn't already, your current nick will be associated with the account and protected from impersonation.  You'll also be allowed to bid in all auctions.", False]
        self.helpText["nickserv"][1]["ID"] = ["Alias of IDENTIFY", "Syntax: \x02ID \x1Femail:password\x1F\x02\n\nLogs into a donor account with the specified email and password.  If it isn't already, your current nick will be associated with the account and protected from impersonation.  You'll also be allowed to bid in all auctions.", False]
        self.helpText["nickserv"][1]["LOGIN"] = ["Log into an existing donor account", "Syntax: \x02LOGIN \x1Femail\x1F \x1Fpassword\x1F\x02\n\nLogs into a donor account with the specified email and password.  If it isn't already, your current nick will be associated with the account and protected from impersonation.  You'll also be allowed to bid in all auctions.", False]
        self.helpText["nickserv"][1]["LOGOUT"] = ["Log out of your donor account", "Syntax: \x02LOGOUT\x02\n\nLogs out of whatever account you are in right now. Useful to prevent your roommate from bidding on auctions in your name.", False]
        self.helpText["nickserv"][1]["GHOST"] = ["Disconnects a user with the given nick", "Syntax: \x02GHOST \x1Fnickname\x1F\x02\n\nIf the given nickname is linked with your account, the user with the given nick is disconnected.", False]
        self.helpText["nickserv"][1]["DROP"] = ["Unregisters a givennickname from your account", "Syntax: \x02DROP \x1Fnickname\x1F\x02\n\nUnregisters the given nickname from your account, allowing other people to use it and giving you more space to register other nicknames.", False]
        self.helpText["nickserv"][1]["NICKLIST"] = ["Lists all the nicknames registered to your account", "Syntax: \x02NICKLIST\x02\n\nLists all the nicknames registered to your account.", False]
        self.helpText["nickserv"][1]["CERT"] = ["Allows you to manage SSL certificate fingerprints for SASL EXTERNAL authentication", "Syntax: \x02CERT \x1F{LIST|ADD|DEL}\x1F \x1F[certificate fingerprint]\x1F\x02\n\nProvides a mechanism to manage SSL certificate fingerprints for SASL EXTERNAL authentication.  SSL certificate fingerprints available on your account when you log in normally are automatically added to this list for later use.  Use the \x02LIST\x02 subcommand to view all certificate fingerprints associated with your account.  If you supply a certificate fingerprint for the \x02ADD\x02 or \x02DEL\x02 subcommands, you can modify the list.  If you are currently connected via SSL with a certificate, you can view your current certificate fingerprint using /WHOIS.", False]
        
        self.helpText["chanserv"][1]["HELP"] = ["Shows command help", "Syntax: \x02HELP \x1F[command]\x1F\x02\n\nDisplays command help.  With the optional command parameter, displays help for the given command.", False]
        self.helpText["chanserv"][1]["REGISTER"] = ["Registers a channel for your use", "Syntax: \x02REGISTER \x1Fchannel\x1F\x02\n\nRegisters a channel with you as a founder.  You must be a channel op or higher in the specified channel in order to register the channel.", False]
        self.helpText["chanserv"][1]["ACCESS"] = ["Allows you to change the access level of another user in a channel you own", "Syntax: \x02ACCESS \x1Fchannel\x1F [\x1Faccount|nick|group\x1F \x1Fflags\x1F]\x02\n\nLists or changes access information for a channel.  If an account is not specified, the channel's access list will be displayed.  If a nick is given for the account, it will first match a user with that nick; if one is not connected to the network, it then checks for an account to which that nick is registered.  If an account and flags are specified, the given flag changes will be applied to the given account in the channel.  Valid flags are any channel status mode level, and they are automatically applied to matching users on join or identify.  "
                                                  "You can also assign the +A flag, which grants the ability to modify the channel access list to other users.  The channel founder always has the ability to control the access list.  The group parameter can be any of the following:\n\t~o\tAll opered users\n\t~r\tAll registered and identified users", False]
        self.helpText["chanserv"][1]["CDROP"] = ["Allows you to drop channels you own", "Syntax: \x02CDROP \x1Fchannel\x1F\x02\n\nDrops the specified channel that you own.", False]
        
        self.helpText["bidserv"][1]["HELP"] = ["Shows command help", "Syntax: \x02HELP \x1F[command]\x1F\x02\n\nDisplays command help.  With the optional command parameter, displays help for the given command.", False]
        self.helpText["bidserv"][1]["START"] = ["Start an auction", "Syntax: \x02START \x1FItemID\x1F\x02\n\nStarts an auction with the given item ID.", True]
        self.helpText["bidserv"][1]["STOP"] = ["Cancel the current auction", "Syntax: \x02STOP\x02\n\nStops and cancels the currently running auction, and logs the bid history.", True]
        self.helpText["bidserv"][1]["BID"] = ["Bid in the active auction", "Syntax: \x02BID \x1Famount\x1F \x1F[smacktalk]\x1F\x02\n\nDuring an auction, this command allows the user to place a bid.  If the bid is higher than the last successful bid, BidServ will display it along with any provided smack talk.", False]
        self.helpText["bidserv"][1]["REVERT"] = ["Cancel the highest bid", "Syntax: \x02REVERT\x02\n\nRemoves the highest bid from the auction, returning the auction to the state of the bid before that.", True]
        self.helpText["bidserv"][1]["ONCE"] = ["Call \"Going Once!\"", "Syntax: \x02ONCE\x02\n\nCalls \"Going Once!\" to the crowd.", True]
        self.helpText["bidserv"][1]["TWICE"] = ["Call \"Going Twice!\"", "Syntax: \x02TWICE\x02\n\nCalls \"Going Twice!\" to the crowd.  Use with caution, as this command is known to make the crowd go crazy and arouse bid snipers.", True]
        self.helpText["bidserv"][1]["SOLD"] = ["Award the auction to the highest bidder", "Syntax: \x02SOLD\x02\n\nDeclares the auction as complete, awarding the prize to the highest bidder.", True]
        self.helpText["bidserv"][1]["HIGHBIDDER"] = ["Get the high bidder in the current auction", "Syntax: \x02HIGHBIDDER\x02\n\nDisplays the high bidder in the current auction along with the amount of the current high bid.", False]
        self.helpText["bidserv"][1]["CURRENTAUCTION"] = ["Shows the item currently up for auction.", "Syntax: \x02CURRENTAUCTION\x02\n\nDisplays the item currently up for auction.", False]
        
        self.nickserv = None
        self.chanserv = None
        self.bidserv = None
        self.operserv = None
        
        self.admins = {
            "nickserv": [],
            "chanserv": [],
            "bidserv": [],
            "operserv": []
        }
        
        self.auth_timer = {}
        self.saslUsers = {}
        
        self.dh_params = {
            "prime": choice([
                88402972170164172303996249033648413055387009713852283396427128179123747944379,
                91746108751951218532193616301150976083366027734878534201960124432778416879539,
                92945140821716085806198142320947682800779092108019535774184129113149939170123,
                93625107128045288835755305646068609532847375166101406081196645551422757580507,
                108909761299361055449660291659325447936718493848917032839979168931777346073907,
                58529074759799933482807725855391987615194322074665787950527162701215610904859,
                63215203281400196112753723499340546973831665649781552489040151108086880794939,
                99195390668713967129863040089109264022338575583938782520648896161781140978099,
                98320696763549501689335835915885018157132325101334822216070056656015233291067,
                74908680543512180865211668542005927401643158932789334079491797673369893924603,
                99025823254147595040966722556875361638898692074641873723359611001113538823443,
                107964489490334018274784413863315720640934243685778520051782258286366346826227,
                104202362400023930381804819994551127488289562009989972491899584394317891141443,
                73863143383182619527071902801928331241530571923876498504070459947520196044787,
                95801365258657418181206410666013041855141021310679528411633513825801160377803,
                89054622815932378492843517219374835719798439123122784761267126530397148323187,
                103713955944890997176144155572473093154977522758539026968740490431737758488227,
                79308228509923367000733842193939129986180038982554140219238722525621333587459,
                106461735594795909591077249375502099206790800370424877313249472120829170793483,
                108457637430077952262260760668351495732056364579055819040728019625047787438083,
                106759564531318215142965091722492578636123746401975729785500302146499220422803,
                98855733477651975750208811397393732496469393603166987989558094274863510415547,
                70674938222379309574525107444002821282063783401243929580390502861261302706259,
                67537014653035600875177807262642023628239365826709589889453984786327365000627,
                77605853594559162243575384531288420166266958774785718529594030783621600613987
            ]),
            "generator": 2,
            "privkey": getrandbits(512)
        }
        self.dh_params["pubkey"] = pow(self.dh_params["generator"], self.dh_params["privkey"], self.dh_params["prime"])
        # The Diffie-Hellman parameters are generated here for the DH-BLOWFISH and DH-AES mechanisms for SASL authentication.
        # For the prime numbers here, I generated a series of 256-bit prime numbers using the C OpenSSL library, because all the
        # ones for Python suck and won't do it for me properly.  A random one of the 25 here will be chosen on each module initialization.
        # 
        # 2 and 5 are common values for the generator.  I chose two.  You can change it to five if you want.
        # 
        # The private key is just random bits.  It is currently generated at 512 bits.
        # 
        # The public key must be generated from these other three values ((generator ^ private_key) mod prime), and is stored here as well.
        # 
        # Everything here is generated once per session.
    
    def spawn(self):
        if "servdb_library" in self.ircd.servconfig and "servdb_host" in self.ircd.servconfig and "servdb_port" in self.ircd.servconfig and "servdb_database" in self.ircd.servconfig and "servdb_username" in self.ircd.servconfig and "servdb_password" in self.ircd.servconfig and self.ircd.servconfig["servdb_library"]:
            self.db = adbapi.ConnectionPool(self.ircd.servconfig["servdb_library"], host=self.ircd.servconfig["servdb_host"], port=self.ircd.servconfig["servdb_port"], db=self.ircd.servconfig["servdb_database"], user=self.ircd.servconfig["servdb_username"], passwd=self.ircd.servconfig["servdb_password"], cp_reconnect=True)
        if "servdb_marker" not in self.ircd.servconfig:
            self.ircd.servconfig["servdb_marker"] = "%s"
        
        if "services_nickserv_guest_prefix" not in self.ircd.servconfig:
            self.ircd.servconfig["services_nickserv_guest_prefix"] = "Guest"
        
        if "services_nickserv_nick" not in self.ircd.servconfig:
            self.ircd.servconfig["services_nickserv_nick"] = "NickServ"
        if "services_nickserv_ident" not in self.ircd.servconfig:
            self.ircd.servconfig["services_nickserv_ident"] = "NickServ"
        if "services_nickserv_host" not in self.ircd.servconfig:
            self.ircd.servconfig["services_nickserv_host"] = "services.desertbus.org"
        if "services_nickserv_gecos" not in self.ircd.servconfig:
            self.ircd.servconfig["services_nickserv_gecos"] = "Nickname Service"
        
        if "services_chanserv_nick" not in self.ircd.servconfig:
            self.ircd.servconfig["services_chanserv_nick"] = "ChanServ"
        if "services_chanserv_ident" not in self.ircd.servconfig:
            self.ircd.servconfig["services_chanserv_ident"] = "ChanServ"
        if "services_chanserv_host" not in self.ircd.servconfig:
            self.ircd.servconfig["services_chanserv_host"] = "services.desertbus.org"
        if "services_chanserv_gecos" not in self.ircd.servconfig:
            self.ircd.servconfig["services_chanserv_gecos"] = "Channel Service"
        
        if "services_bidserv_nick" not in self.ircd.servconfig:
            self.ircd.servconfig["services_bidserv_nick"] = "BidServ"
        if "services_bidserv_ident" not in self.ircd.servconfig:
            self.ircd.servconfig["services_bidserv_ident"] = "BidServ"
        if "services_bidserv_host" not in self.ircd.servconfig:
            self.ircd.servconfig["services_bidserv_host"] = "services.desertbus.org"
        if "services_bidserv_gecos" not in self.ircd.servconfig:
            self.ircd.servconfig["services_bidserv_gecos"] = "Bidding Service"
        
        self.nickserv = Service(self.ircd, self.ircd.servconfig["services_nickserv_nick"], self.ircd.servconfig["services_nickserv_ident"], self.ircd.servconfig["services_nickserv_host"], self.ircd.servconfig["services_nickserv_gecos"], self.helpText["nickserv"])
        self.chanserv = Service(self.ircd, self.ircd.servconfig["services_chanserv_nick"], self.ircd.servconfig["services_chanserv_ident"], self.ircd.servconfig["services_chanserv_host"], self.ircd.servconfig["services_chanserv_gecos"], self.helpText["chanserv"])
        self.bidserv = Service(self.ircd, self.ircd.servconfig["services_bidserv_nick"], self.ircd.servconfig["services_bidserv_ident"], self.ircd.servconfig["services_bidserv_host"], self.ircd.servconfig["services_bidserv_gecos"], self.helpText["bidserv"])
        
        self.chanserv.cache["registered"] = CaseInsensitiveDictionary()
        self.nickserv.cache["certfp"] = {}
        
        self.ircd.users[self.ircd.servconfig["services_nickserv_nick"]] = self.nickserv
        self.ircd.users[self.ircd.servconfig["services_chanserv_nick"]] = self.chanserv
        self.ircd.users[self.ircd.servconfig["services_bidserv_nick"]] = self.bidserv
        self.ircd.userid[self.nickserv.uuid] = self.nickserv
        self.ircd.userid[self.chanserv.uuid] = self.chanserv
        self.ircd.userid[self.bidserv.uuid] = self.bidserv
        self.nickserv.addToServers()
        self.chanserv.addToServers()
        self.bidserv.addToServers()
        
        self.ircd.module_data_cache["sasl_agent"] = self
        
        return {
            "commands": {
                "NICKSERV": NickServAlias(),
                "NS": NickServAlias(),
                "CHANSERV": ChanServAlias(),
                "CS": ChanServAlias(),
                "BIDSERV": BidServAlias(),
                "BS": BidServAlias(),
                
                "IDENTIFY": NSIdentifyCommand(self, self.nickserv),
                "ID": NSIdentifyCommand(self, self.nickserv),
                "GHOST": NSGhostCommand(self, self.nickserv),
                "LOGIN": NSLoginCommand(self, self.nickserv),
                "LOGOUT": NSLogoutCommand(self, self.nickserv),
                "DROP": NSDropCommand(self, self.nickserv),
                "NICKLIST": NSNicklistCommand(self, self.nickserv),
                "CERT": NSCertCommand(self, self.nickserv),
                
                "REGISTER": CSRegisterCommand(self, self.chanserv),
                "ACCESS": CSAccessCommand(self, self.chanserv),
                "CDROP": CSCdropCommand(self, self.chanserv),
                
                "START": BSStartCommand(self, self.bidserv),
                "STOP": BSStopCommand(self, self.bidserv),
                "BID": BSBidCommand(self, self.bidserv),
                "REVERT": BSRevertCommand(self, self.bidserv),
                "ONCE": BSOnceCommand(self, self.bidserv),
                "TWICE": BSTwiceCommand(self, self.bidserv),
                "SOLD": BSSoldCommand(self, self.bidserv),
                "HIGHBIDDER": BSHighbidderCommand(self, self.bidserv),
                "CURRENTAUCTION": BSCurrentAuctionCommand(self, self.bidserv)
            },
            "actions": {
                "register": self.onRegister,
                "join": self.promote,
                "quit": self.onQuit,
                "nick": self.onNickChange,
                "topic": self.onTopicChange,
                "chancreate": self.onChanCreate,
                "netmerge": self.onNetmerge,
                "commandpermission": self.commandPermission
            }
        }
    
    def cleanup(self):
        if self.db:
            self.db.close()
        
        self.nickserv.removeFromServers()
        self.chanserv.removeFromServers()
        self.bidserv.removeFromServers()
        del self.ircd.users[self.nickserv.nickname]
        del self.ircd.users[self.chanserv.nickname]
        del self.ircd.users[self.bidserv.nickname]
        del self.ircd.userid[self.nickserv.uuid]
        del self.ircd.userid[self.chanserv.uuid]
        del self.ircd.userid[self.bidserv.uuid]
    
    def data_serialize(self):
        outputDict = {}
        outputDict["registeredchannels"] = self.chanserv.cache["registered"]._data
        if "auction" in self.bidserv.cache:
            outputDict["currentauction"] = self.bidserv.cache["auction"]
        outputDict["certfp"] = self.nickserv.cache["certfp"]
        outputDict["admins"] = self.admins
        return [outputDict, {"auth_timers": self.auth_timer, "saslusers": self.saslUsers}]
    
    def data_unserialize(self, data):
        if "currentauction" in data:
            self.bidserv.cache["auction"] = data["currentauction"]
        if "certfp" in data:
            self.nickserv.cache["certfp"] = data["certfp"]
        if "registeredchannels" in data:
            for key, value in data["registeredchannels"].iteritems():
                self.chanserv.cache["registered"][key] = value
        if "admins" in data:
            self.admins = data["admins"]
        if "auth_timers" in data:
            self.auth_timer = data["auth_timers"]
        if "saslusers" in data:
            self.saslUsers = data["saslusers"]
    
    # Services Functions
    def query(self, query, *args):
        query = query.format(self.ircd.servconfig["servdb_marker"])
        return self.db.runQuery(query, args)
    
    def exclaimServerError(self, result, user, service):
        if user in self.saslUsers:
            self.saslUsers[user]["failure"](user)
            del self.saslUsers[user]
        else:
            user.sendMessage("NOTICE", ":A server error has occurred.", prefix=service.prefix())
    
    def genGuestNick(self):
        nick = "{}{:>06d}".format(self.ircd.servconfig["services_nickserv_guest_prefix"] if "services_nickserv_guest_prefix" in self.ircd.servconfig and self.ircd.servconfig["services_nickserv_guest_prefix"] else "Guest", random.randrange(1000000))
        if nick in self.ircd.users:
            return self.genGuestNick()
        return nick
    
    def auth(self, user, username, password):
        d = self.query("SELECT id, display_name, password FROM donors WHERE email = {0}", username)
        d.addCallback(self.verifyPassword, user, password)
        d.addErrback(self.exclaimServerError, user, self.nickserv)
        return d
    
    def authByCert(self, user, cert, username):
        d = self.query("SELECT id, display_name FROM donors WHERE email = {0}", username)
        d.addCallback(self.verifyCert, user, cert)
        d.addErrback(self.exclaimServerError, user, self.nickserv)
        return d
    
    def token(self, user, password):
        d = self.query("SELECT donor_id FROM irctokens WHERE token = {0}", password)
        d.addCallback(self.loadDonorInfo, user)
        return d
    
    def checkNick(self, user):
        if user in self.auth_timer:
            self.removeAuthTimer(user)
        if irc_lower(user.nickname).startswith(irc_lower(self.ircd.servconfig["services_nickserv_guest_prefix"])):
            return # Don't check guest nicks
        d = self.query("SELECT donor_id FROM ircnicks WHERE nick = {0}", irc_lower(user.nickname))
        d.addCallback(self.beginVerify, user)
        return d
    
    def verifyPassword(self, result, user, password):
        if not result:
            if user in self.saslUsers:
                self.saslUsers[user]["failure"](user)
                del self.saslUsers[user]
            else:
                self.checkNick(user)
                user.sendMessage("NOTICE", ":The login credentials you provided were incorrect.", prefix=self.nickserv.prefix())
            return
        hash = result[0][2]
        check = crypt(password, hash)
        if check == hash:
            self.loginUser(result, user)
        else:
            if user in self.saslUsers:
                self.saslUsers[user]["failure"](user)
                del self.saslUsers[user]
            else:
                self.checkNick(user)
                user.sendMessage("NOTICE", ":The login credentials you provided were incorrect.", prefix=self.nickserv.prefix())
    
    def verifyCert(self, result, user, cert):
        def failValidation():
            if user in self.saslUsers:
                self.saslUsers[user]["failure"](user)
                del self.saslUsers[user]
            else:
                self.checkNick(user)
                user.sendMessage("NOTICE", ":The login credentials you provided were incorrect.", prefix=self.nickserv.prefix())
        
        if not result:
            failValidation()
            return
        accid = result[0][0]
        if accid not in self.nickserv.cache["certfp"]:
            failValidation()
            return
        if cert in self.nickserv.cache["certfp"][accid]:
            self.loginUser(result, user)
        else:
            failValidation()
    
    def loginUser(self, result, user):
        user.cache["accountid"] = str(result[0][0])
        if result[0][1]:
            user.setMetadata("ext", "accountname", result[0][1].replace(" ", "_"))
        else:
            user.setMetadata("ext", "accountname", "Anonymous") # The account name can't be blank, so fill in a default one
        if user in self.auth_timer:
            self.removeAuthTimer(user)
        if user in self.saslUsers:
            self.saslUsers[user]["success"](user)
            del self.saslUsers[user]
        else:
            user.sendMessage("NOTICE", ":You are now identified. Welcome, {}.".format(user.metadata["ext"]["accountname"]), prefix=self.nickserv.prefix())
            self.checkNick(user)
        self.registered(user)
    
    def loadDonorInfo(self, result, user):
        if not result:
            self.checkNick(user)
            user.sendMessage("NOTICE", ":An invalid authentication token was provided.", prefix=self.nickserv.prefix())
            return
        d = self.query("SELECT id, display_name FROM donors WHERE id = {0}", result[0][0])
        d.addCallback(self.setDonorInfo, user)
        d.addErrback(self.exclaimServerError, user, self.nickserv)
        return d
    
    def beginVerify(self, result, user):
        if result:
            id = str(result[0][0])
            if "accountid" in user.cache and user.cache["accountid"] == id:
                if user in self.auth_timer: # Clear the timer
                    self.removeAuthTimer(user)
                return # Already identified
            user.sendMessage("NOTICE", ":This is a registered nick. Please use \x02/msg {} login EMAIL PASSWORD\x0F to verify your identity.".format(self.nickserv.nickname), prefix=self.nickserv.prefix())
            self.unregistered(user)
            if user in self.auth_timer:
                self.removeAuthTimer(user)
            self.setAuthTimer(user)
        elif "accountid" in user.cache:
            # Try to register the nick
            d = self.query("SELECT nick FROM ircnicks WHERE donor_id = {0}", user.cache["accountid"])
            d.addCallback(self.registerNick, user, user.nickname)
            d.addErrback(self.failedRegisterNick, user, user.nickname)
    
    def setAuthTimer(self, user):
        self.auth_timer[user] = reactor.callLater(self.ircd.servconfig["services_nickserv_timeout"] if "services_nickserv_timeout" in self.ircd.servconfig else 60, self.changeNick, user, id, user.nickname)
        if user.server != self.ircd.name:
            self.ircd.servers[user.server].callRemote(ModuleMessage, destserver=user.server, type="ServiceBlockUser", args=[user.uuid])
    
    def removeAuthTimer(self, user):
        self.auth_timer[user].cancel()
        del self.auth_timer[user]
        if user.server != self.ircd.name:
            self.ircd.servers[user.server].callRemote(ModuleMessage, destserver=user.server, type="ServiceUnblockUser", args=[user.uuid])
    
    def setDonorInfo(self, result, user):
        if not result:
            self.checkNick(user)
            self.exclaimServerError(user, self.nickserv)
            return
        self.loginUser(result, user)
    
    def changeNick(self, user, id, nickname):
        if user in self.auth_timer:
            del self.auth_timer[user]
            if user.server != self.ircd.name:
                self.ircd.servers[user.server].callRemote(ModuleMessage, destserver=user.server, type="ServiceUnblockUser", args=[user.uuid])
        if "accountid" in user.cache and user.cache["accountid"] == id:
            return # Somehow we auth'd and didn't clear the timer?
        if irc_lower(user.nickname) != irc_lower(nickname):
            return # Changed nick before the timeout. Whatever
        user.nick(self.genGuestNick())
    
    def registerNick(self, result, user, nickname):
        if "services_nickserv_nick_limit" in self.ircd.servconfig and self.ircd.servconfig["services_nickserv_nick_limit"] and len(result) >= self.ircd.servconfig["services_nickserv_nick_limit"]:
            # Already registered all the nicks we can
            nicklist = ", ".join([l[0] for l in result[:-1]])+", or "+result[-1][0] if len(result) > 1 else result[0][0]
            message = ":Warning: You already have {!s} registered nicks, so {} will not be protected. Please switch to {} to prevent impersonation!".format(self.ircd.servconfig["services_nickserv_nick_limit"], nickname, nicklist)
            user.sendMessage("NOTICE", message, prefix=self.nickserv.prefix())
        else:
            d = self.query("INSERT INTO ircnicks(donor_id, nick) VALUES({0},{0})", user.cache["accountid"], irc_lower(nickname))
            d.addCallback(self.successRegisterNick, user, nickname)
            d.addErrback(self.failedRegisterNick, user, nickname)
    
    def failedRegisterNick(self, result, user, nickname):
        user.sendMessage("NOTICE", ":Failed to register nick {} to account {}. Other users may still use it.".format(nickname, user.metadata["ext"]["accountname"]), prefix=self.nickserv.prefix())
    
    def successRegisterNick(self, result, user, nickname):
        user.sendMessage("NOTICE", ":Nickname {} is now registered to account {} and can not be used by any other user.".format(nickname, user.metadata["ext"]["accountname"]), prefix=self.nickserv.prefix())
    
    def binaryString(self, num):
        strnum = "{0:x}".format(num)
        if len(strnum) % 2:
            strnum = "0" + strnum
        return strnum.decode("hex")
    
    def saslStart(self, user, mechanism):
        try:
            setupfunc = getattr(self, "saslSetup_{}".format(mechanism.replace("-", "_")))
        except AttributeError:
            return "fail"
        self.saslUsers[user] = { "mechanism": mechanism }
        return setupfunc(user)
    
    def saslSetup_PLAIN(self, user):
        user.sendMessage("AUTHENTICATE", "+", to=None, prefix=None)
    
    def saslSetup_DH_BLOWFISH(self, user):
        encodedP = self.binaryString(self.dh_params["prime"])
        lengthP = self.binaryString(len(encodedP))
        if len(lengthP) == 1:
            lengthP = "\x00" + lengthP
        encodedG = self.binaryString(self.dh_params["generator"])
        lengthG = self.binaryString(len(encodedG))
        if len(lengthG) == 1:
            lengthG = "\x00" + lengthG
        encodedY = self.binaryString(self.dh_params["pubkey"])
        lengthY = self.binaryString(len(encodedY))
        if len(lengthY) == 1:
            lengthY = "\x00" + lengthY
        outStr = "{}{}{}{}{}{}".format(lengthP, encodedP, lengthG, encodedG, lengthY, encodedY)
        output = b64encode(outStr)
        
        splitOut = [output[i:i+400] for i in range(0, len(output), 400)]
        for line in splitOut:
            user.sendMessage("AUTHENTICATE", line, to=None, prefix=None)
        if len(splitOut[-1]) == 400:
            user.sendMessage("AUTHENTICATE", "+", to=None, prefix=None)
    
    def saslSetup_DH_AES(self, user):
        return self.saslSetup_DH_BLOWFISH(user)
    
    def saslSetup_EXTERNAL(self, user):
        if "certfp" not in self.nickserv.cache:
            return "fail"
        user.sendMessage("AUTHENTICATE", "+", to=None, prefix=None)
    
    def saslNext(self, user, data):
        try:
            processfunc = getattr(self, "saslProcess_{}".format(self.saslUsers[user]["mechanism"].replace("-", "_")))
        except AttributeError:
            return "done"
        return processfunc(user, data)
    
    def saslProcess_PLAIN(self, user, data):
        try:
            authorizationID, authenticationID, password = b64decode(data).split("\0")
        except (TypeError, ValueError):
            return "done"
        self.auth(user, authenticationID, password)
        return "wait"
    
    def saslProcess_DH_BLOWFISH(self, user, data):
        try:
            encryptedData = b64decode(data)
        except TypeError:
            return "done"
        if len(encryptedData) < 2:
            return "done"
        pubkeyLen = int(encryptedData[:2].encode("hex"), 16)
        encryptedData = encryptedData[2:]
        if pubkeyLen > len(encryptedData):
            return "done"
        pubkey = int(encryptedData[:pubkeyLen].encode("hex"), 16)
        encryptedData = encryptedData[pubkeyLen:]
        
        try:
            username, encryptedData = encryptedData.split("\0", 1)
        except ValueError:
            return "done"
        
        if not encryptedData: # Ensure there is remaining data
            return "done"
        sharedSecret = self.binaryString(pow(pubkey, self.dh_params["privkey"], self.dh_params["prime"]))
        
        blowfishKey = Blowfish.new(sharedSecret)
        try:
            password = blowfishKey.decrypt(encryptedData)
        except ValueError: # decrypt raises ValueError if the message is not of the correct length
            return "done"
        self.auth(user, username, password)
        return "wait"
    
    def saslProcess_DH_AES(self, user, data):
        try:
            encryptedData = b64decode(data)
        except TypeError:
            return "done"
        if len(encryptedData) < 2:
            return "done"
        pubkeyLen = int(encryptedData[:2].encode("hex"), 16)
        encryptedData = encryptedData[2:]
        if pubkeyLen > len(encryptedData):
            return "done"
        pubkey = int(encryptedData[:pubkeyLen].encode("hex"), 16)
        encryptedData = encryptedData[pubkeyLen:]
        
        if len(encryptedData) < AES.block_size * 2:
            return "done" # The remaining data is too short to be valid for AES
        
        iv = encryptedData[:AES.block_size]
        encryptedData = encryptedData[AES.block_size:]
        sharedSecret = self.binaryString(pow(pubkey, self.dh_params["privkey"], self.dh_params["prime"]))
        
        aesCipher = AES.new(sharedSecret, mode=AES.MODE_CBC, IV=iv)
        try:
            decryptedData = aesCipher.decrypt(encryptedData)
        except ValueError:
            return "done"
        
        try:
            username, password, padding = decryptedData.split("\0", 2)
        except ValueError:
            return "done"
        
        self.auth(user, username, password)
        return "wait"
    
    def saslProcess_EXTERNAL(self, user, data):
        try:
            username = b64decode(data[0])
        except TypeError:
            return "done"
        if "certfp" not in user.metadata["server"]:
            return "done"
        self.authByCert(user, user.metadata["server"]["certfp"], username)
        return "wait"
    
    def saslDone(self, user, success):
        del self.saslUsers[user]
    
    def bindSaslResult(self, user, successFunction, failureFunction):
        self.saslUsers[user]["success"] = successFunction
        self.saslUsers[user]["failure"] = failureFunction
    
    def isServiceAdmin(self, user, service):
        if "o" in user.mode:
            return True
        if "accountid" not in user.cache:
            return False
        id = user.cache["accountid"]
        convertServices = {
            self.nickserv: "nickserv",
            self.chanserv: "chanserv",
            self.bidserv: "bidserv",
            self.operserv: "operserv"
        }
        if service not in convertServices:
            return False
        return id in self.admins[convertServices[service]]
    
    def registered(self, user):
        for c in self.ircd.channels.itervalues():
            if user in c.users:
                self.promote(user, c, True)
        if "certfp" in user.metadata["server"]:
            self.addCert(user, user.metadata["server"]["certfp"])
    
    def unregistered(self, user):
        for channel in self.ircd.channels.itervalues():
            if user in channel.users:
                status = channel.users[user]
                if status:
                    channel.setMode(None, "-{}".format(status), [user.nickname for i in range(len(status))], self.chanserv.prefix())
    
    def promote(self, user, channel, keepOldStatus=False):
        if user in self.auth_timer:
            return
        if channel.name in self.chanserv.cache["registered"]:
            flags = set()
            if "o" in user.mode and "~o" in self.chanserv.cache["registered"][channel.name]["access"]:
                for flag in self.chanserv.cache["registered"][channel.name]["access"]["~o"]:
                    flags.add(flag)
            if "accountid" in user.cache:
                if "~r" in self.chanserv.cache["registered"][channel.name]["access"]:
                    for flag in self.chanserv.cache["registered"][channel.name]["access"]["~r"]:
                        flags.add(flag)
                if user.cache["accountid"] in self.chanserv.cache["registered"][channel.name]["access"]:
                    for flag in self.chanserv.cache["registered"][channel.name]["access"][user.cache["accountid"]]:
                        flags.add(flag)
            if keepOldStatus:
                for flag in channel.users[user]:
                    flags.discard(flag)
            else:
                userStatus = channel.users[user]
                if userStatus:
                    channel.setMode(None, "-{}".format(userStatus), [user.nickname for i in range(len(userStatus))], self.chanserv.prefix())
            
            flagList = set(flags)
            for flag in flagList:
                if flag not in self.ircd.prefix_order:
                    flags.discard(flag)
            if flags:
                channel.setMode(None, "+{}".format("".join(flags)), [user.nickname for i in range(len(flags))], self.chanserv.prefix())
    
    def addCert(self, user, certfp):
        accountid = user.cache["accountid"]
        if accountid not in self.nickserv.cache["certfp"]:
            self.nickserv.cache["certfp"][accountid] = []
        if certfp not in self.nickserv.cache["certfp"][accountid]:
            self.nickserv.cache["certfp"][accountid].append(certfp)
            return True
        return False
    
    def onRegister(self, user):
        if user.password:
            if ":" in user.password:
                email, password = user.password.split(":", 1)
                self.auth(user, email, password)
            elif " " in user.password:
                email, password = user.password.split(" ", 1)
                self.auth(user, email, password)
            else:
                self.token(user, user.password)
        self.checkNick(user)
        return True
    
    def onQuit(self, user, reason):
        if user in self.auth_timer:
            self.removeAuthTimer(user)
    
    def onNickChange(self, user, oldNick):
        if irc_lower(user.nickname) != irc_lower(oldNick):
            self.checkNick(user)
    
    def onTopicChange(self, channel, newTopic, newSetter):
        if channel.name in self.chanserv.cache["registered"]:
            self.chanserv.cache["registered"][channel.name]["topic"] = [newTopic, newSetter, now()]
    
    def onChanCreate(self, channel):
        if channel.name in self.chanserv.cache["registered"] and "topic" in self.chanserv.cache["registered"][channel.name]:
            topicData = self.chanserv.cache["registered"][channel.name]["topic"]
            channel.setTopic(topicData[0], topicData[1])
            channel.topicTime = topicData[2]
            channel.created = self.chanserv.cache["registered"][channel.name]["registertime"]
    
    def onNetmerge(self, name):
        self.ircd.servers[name].callRemote(ModuleMessage, destserver=name, type="ServiceServer", args=[self.ircd.name])
    
    def commandPermission(self, user, cmd, data):
        if user not in self.auth_timer:
            return data
        if cmd == "PRIVMSG":
            to_nickserv = False
            for u in data["targetuser"]:
                if irc_lower(u.nickname) == irc_lower(self.nickserv.nickname):
                    to_nickserv = True
                    break
            if to_nickserv:
                data["targetuser"] = [self.nickserv]
                data["targetchan"] = []
                data["chanmod"] = []
                return data
            user.sendMessage("NOTICE", ":You cannot message anyone other than NickServ until you identify or change nicks.", prefix=self.nickserv.prefix())
            return {}
        if cmd in [ "PING", "PONG", "NICK", "QUIT", "NS", "NICKSERV", "LOGIN", "ID", "IDENTIFY" ]:
            return data
        user.sendMessage("NOTICE", ":You cannot use the command \x02{}\x02 until you identify or change nicks.".format(cmd), prefix=self.nickserv.prefix())
        return {}