from twisted.enterprise import adbapi
from twisted.internet import reactor
from twisted.internet.defer import Deferred
from txircd.modbase import Command
from txircd.utils import chunk_message, crypt, irc_lower, now, CaseInsensitiveDictionary
import math, os, random, yaml

class Service(object):
	
	class ServiceSocket(object):
		class ServiceTransport(object):
			def loseConnection(self):
				pass
		
		def __init__(self):
			self.transport = self.ServiceTransport()
	
	def __init__(self, ircd, nick, ident, host, gecos, helpTexts):
		# We're going to try to keep Service fairly consistent with IRCUser, even if most of these variables will never be used
		# in order to prevent exceptions all over the place
		self.ircd = ircd
		self.socket = self.ServiceSocket()
		self.password = None
		self.nickname = nick
		self.username = ident
		self.hostname = host
		self.realname = gecos
		self.ip = "127.0.0.1"
		self.server = self.ircd.servconfig["server_name"]
		self.signon = now()
		self.lastactivity = now()
		self.lastpong = now()
		self.mode = {}
		self.channels = CaseInsensitiveDictionary()
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
	
	def register(self):
		pass
	
	def send_isupport(self):
		pass
	
	def disconnect(self, reason):
		pass
	
	def checkData(self, data):
		pass
	
	def connectionLost(self, reason):
		pass
	
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
			elif serviceCommand in self.help[1]:
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
	
	def status(self, channel):
		return self.ircd.prefix_order # Just have all statuses always.  It's easier that way.
	
	def modeString(self, user):
		return "+" # user modes are for chumps
	
	def send_motd(self):
		pass
	
	def send_lusers(self):
		pass
	
	def report_names(self, channel):
		pass
	
	def listname(self, channel, listingUser, representation):
		for mode in channel.mode.iterkeys():
			representation = self.ircd.channel_modes[self.ircd.channel_mode_type[mode]][mode].namesListEntry(self, channel, listingUser, representation)
			if not representation:
				return representation
		for mode in listingUser.mode.iterkeys():
			representation = self.ircd.user_modes[self.ircd.user_mode_type[mode]][mode].namesListEntry(self, channel, listingUser, representation)
			if not representation:
				return representation
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
		self.module.auth(data["email"], data["password"])
	
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
		if "accountid" in targetUser.metadata["ext"] and targetUser.metadata["ext"]["accountid"] == user.metadata["ext"]["accountid"]:
			targetUser.disconnect("Killed (GHOST command issued by {})".format(user.nickname))
			user.sendMessage("NOTICE", ":{} has been disconnected.".format(targetUser.nickname), prefix=self.nickserv.prefix())
		else:
			d = self.module.query("SELECT nick FROM ircnicks WHERE donor_id = {0} AND nick = {0}", user.metadata["ext"]["accountid"], irc_lower(targetUser.nickname))
			d.addCallback(self.ghostSuccess, user, targetUser)
			d.addErrback(self.module.exclaimServerError, user, self.nickserv)
	
	def processParams(self, user, params):
		if "accountid" not in user.metadata["ext"]:
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
			user.sendMessage("NOTICE", ":Usage: \x02LOGIN \x1Femail password", prefix=self.nickserv.prefix())
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
		user.delMetadata("ext", "accountid")
		user.delMetadata("ext", "accountname")
		self.module.checkNick(user)
		self.module.unregistered(user)
		user.sendMessage("NOTICE", ":You are now logged out.", prefix=self.nickserv.prefix())
	
	def processParams(self, user, params):
		if "accountid" not in user.metadata["ext"]:
			user.sendMessage("NOTICE", ":You must be logged in to log out!", prefix=self.nickserv.prefix())
			return {}
		return {
			"user": user
		}

class NSDropCommand(Command):
	def __init__(self, module, service):
		self.module = module
		self.nickserv = service
	
	def onUse(self, user, data):
		d = self.ircd.db.runInteraction(self.dropNicknameTransaction, user.metadata["ext"]["accountid"], data["nick"], self.ircd.servconfig["servdb_marker"])
		d.addCallback(self.confirmDropped, user, nick)
		d.addErrback(self.confirmNotDropped, user, nick)
	
	def processParams(self, user, params):
		if "accountid" not in user.metadata["ext"]:
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
	
	def confirmNotDropped(self, result, user, nick):
		user.sendMessage("NOTICE", ":Could not drop nickname {} from your account.  Ensure that it belongs to you.".format(nick), prefix=self.nickserv.prefix())

class NSNicklistCommand(Command):
	def __init__(self, module, service):
		self.module = module
		self.nickserv = service
	
	def onUse(self, user, data):
		d = self.query("SELECT nick FROM ircnicks WHERE donor_id = {0}", user.metadata["ext"]["accountid"])
		d.addCallback(self.shownicks, user)
		d.addErrback(self.module.exclaimServerError, user, self.nickserv)
	
	def processParams(self, user, params):
		if "accountid" not in user.metadata["ext"]:
			user.sendMessage("NOTICE", ":You must be logged in to see your nicknames.", prefix=self.nickserv.prefix())
			return {}
		return {
			"user": user
		}
	
	def showNicks(self, results, user):
		user.sendMessage("NOTICE", ":Registered Nicknames: {}".format(", ".join([n[0] for n in result])), prefix=self.nickserv.prefix())

class NSAccountCommand(Command):
	def __init__(self, module, service):
		self.module = module
		self.nickserv = service
	
	def onUse(self, user, data):
		if "targetaccount" in data:
			d = self.query("SELECT nick FROM ircnicks WHERE donor_id = {0}", data["targetaccount"])
			d.addCallback(self.shownicks, user, data["targetaccount"])
			d.addErrback(self.module.exclaimServerError, user, self.nickserv)
		else:
			targetUser = data["targetuser"]
			if "accountid" in targetUser.metadata["ext"]:
				user.sendMessage("NOTICE", ":ID: {}".format(targetUser.metadata["ext"]["accountid"]), prefix=self.nickserv.prefix())
			else:
				user.sendMessage("NOTICE", ":Not identified", prefix=self.nickserv.prefix())
	
	def processParams(self, user, params):
		if not params:
			user.sendMessage("NOTICE", ":Usage: \x02ACCOUNT \x1Fnick|id", prefix=self.nickserv.prefix())
			return {}
		if params[0] in self.ircd.users:
			return {
				"user": user,
				"targetuser": self.ircd.users[params[0]]
			}
		try:
			return {
				"user": user,
				"targetaccount": int(params[0])
			}
		except ValueError:
			user.sendMessage("NOTICE", ":The nick/ID you provided is not valid.", prefix=self.nickserv.prefix())
			return {}
	
	def shownicks(self, results, user, accountID):
		user.sendMessage("NOTICE", ":Nicks for account {}: {}".format(accountID, ", ".join([n[0] for n in result])), prefix=self.nickserv.prefix())


class CSRegisterCommand(Command):
	def __init__(self, module, service):
		self.module = module
		self.chanserv = service
	
	def onUse(self, user, data):
		channel = data["targetchan"]
		self.chanserv.cache["registered"][channel.name] = {"founder": user.metadata["ext"]["accountid"], "access": {}}
		user.sendMessage("NOTICE", ":The channel {} has been registered under your account.".format(channel.name), prefix=self.chanserv.prefix())
	
	def processParams(self, user, params):
		if "accountid" not in user.metadata["ext"]:
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
		if not user.hasAccess(cdata.name, "o"):
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
		group = False
		if "targetgroup" in data:
			accessID = data["targetgroup"]
			group = True
		elif "targetaccount" in data:
			accessID = data["targetaccount"]
		else:
			for id, flags in self.chanserv.cache["registered"][data["targetchan"]]["access"].iteritems():
				user.sendMessage("NOTICE", "  {}: +{}".format(id, flags), prefix=self.chanserv.prefix())
			user.sendMessage("NOTICE", ":End of ACCESS list", prefix=self.chanserv.prefix())
			return
		flagSet = list(self.chanserv.cache["registered"][data["targetchan"]]["access"][accessID])
		adding = True
		for flag in data["flags"]:
			if flag == "+":
				adding = True
			elif flag == "-":
				adding = False
			elif flag in self.ircd.prefix_order:
				if adding and flag not in flagSet:
					flagSet.append(flag)
				elif not adding and flag in flagSet:
					flagSet.remove(flag)
		self.chanserv.cache["registered"][data["targetchan"]]["access"][accessID] = "".join(flagSet)
		user.sendMessage("NOTICE", ":The flags for the {} {} have been changed to +{}".format("group" if group else "account", accessID, "".join(flagSet)), prefix=self.chanserv.prefix())
	
	def processParams(self, user, params):
		if not params:
			user.sendMessage("NOTICE", ":Usage: \x02ACCESS \x1Fchannel\x1F [\x1Faccount|nick|group\x1F \x1Fflags\x1F]", prefix=self.chanserv.prefix())
			return {}
		if len(params) < 3:
			return {
				"user": user,
				"targetchan": params[0]
			}
		if "accountid" not in user.metadata["ext"] or user.metadata["ext"]["accountid"] != self.chanserv.cache["registered"][params[0]]["founder"]:
			user.sendMessage("NOTICE", ":You must own the channel to change its access permissions.", prefix=self.chanserv.prefix())
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
			if "accountid" not in udata.metadata["ext"]:
				user.sendMessage("NOTICE", ":The target user is not identified to any account.", prefix=self.chanserv.prefix())
				return {}
			return {
				"user": user,
				"targetchan": params[0],
				"targetaccount": udata.metadata["ext"]["accountid"],
				"flags": params[2]
			}
		try:
			return {
				"user": user,
				"targetchan": params[0],
				"targetaccount": int(params[1]),
				"flags": params[2]
			}
		except ValueError:
			user.sendMessage("NOTICE", ":The account, nick, or group identifier that you provided is not valid.", prefix=self.chanserv.prefix())
			return {}


class BSStartCommand(Command):
	def __init__(self, module, service):
		self.module = module
		self.bidserv = service
	
	def onUse(self, user, data):
		d = self.query("SELECT id, name, sold, starting_bid FROM prizes WHERE id = {0}", data["auction"])
		d.addCallback(self.auctionStart, user, data["auction"])
		d.addErrback(self.module.exclaimServerError, user, self.bidserv)
	
	def processParams(self, user, params):
		if "o" not in user.mode:
			user.sendMessage("NOTICE", ":Unknown command \x02START\x02.  Use \x1F/msg {} HELP\x1F for help.".format(self.bidserv.nickname), prefix=self.bidserv.prefix())
			return {}
		if "auction" in self.bidserv.cache:
			user.sendMessage("NOTICE", ":You cannot start an auction when one is currently in progress.", prefix=self.bidserv.prefix())
			return {}
		if not params:
			user.sendMesage("NOTICE", ":Usage: \x02START \x1FauctionID", prefix=self.bidserv.prefix())
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
		if not result:
			user.sendMessage("NOTICE", ":Could not find the item ID {}".format(auctionID), prefix=self.bidserv.prefix())
			return
		if result[0][2]:
			user.sendMessage("NOTICE", ":The item {} ({}) has already been sold.".format(result[0][0], result[0][1]), prefix=self.bidserv.prefix())
			return
		self.bidserv.cache["auction"] = {
			"item": result[0][0],
			"name": result[0][1],
			"highbid": float(result[0][3]),
			"highbidder": "Nobody",
			"highbidderid": None,
			"startbid": float(result[0][3]),
			"bids": [],
			"called": 0
		}
		lines = [] # The lines array here serves as a cache for the lines so that the format isn't applied repeatedly on every iteration
		lines.append(":\x02\x034Starting Auction for Lot #{}: \"{}\"\x02 - Called by {}".format(result[0][0], result[0][1], user.nickname))
		lines.append(":\x02\x034Make bids with \x1F/bid ###.## [smack talk]")
		if "services_bidserv_increment" in self.ircd.servconfig:
			lines.append(":\x02\x034The minimum increment between bids is ${:,.2f}".format(self.ircd.servconfig["services_bidserv_increment"]))
		lines.append(":\x02\x034Only voiced (registered donor) users can bid - https://donor.desertbus.org/")
		lines.append(":\x02\x034Please do not make any fake bids")
		lines.append(":\x02\x034Beginning bidding at ${:,.2f}".format(float(result[0][3])))
		for channel in self.ircd.channels.itervalues():
			for u in channel.users:
				for line in lines:
					u.sendMessage("PRIVMSG", line, to=channel.name, prefix=self.bidserv.prefix())

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
			for u in channel.users:
				u.sendMessage("PRIVMSG", cancelMsg, to=channel.name, prefix=self.bidserv.prefix())
		del self.bidserv.cache["auction"]
	
	def processParams(self, user, params):
		if "o" not in user.mode:
			user.sendMessage("NOTICE", ":Unknown command \x02STOP\x02.  Use \x1F/msg {} HELP\x1F for help.".format(self.bidserv.nickname), prefix=self.bidserv.prefix())
			return {}
		if "auction" not in self.bidserv.cache:
			user.sendMessage("NOTICE", ":There is not an auction going on now.", prefix=self.bidserv.prefix())
			return {}
	
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
		if self.bidserv.cache["auction"]["highbidderid"] == user.metadata["ext"]["accountid"] and "services_bidserv_space_bid" in self.ircd.servconfig:
			madness += "{}! ".format(self.ircd.servconfig["services_bidserv_space_bid"])
		
		bidMsg = ":\x02\x034{}{} has the high bid of ${:,.2f}! \x0312{}".format(madness, user.nickname, bid, data["smacktalk"])
		self.bidserv.cache["auction"]["called"] = 0
		self.bidserv.cache["auction"]["bids"].append({
			"bid": bid,
			"bidder": user.metadata["ext"]["accountid"],
			"nick": user.nickname
		})
		self.bidserv.cache["auction"]["highbid"] = bid
		self.bidserv.cache["auction"]["highbidder"] = user.nickname
		self.bidserv.cache["auction"]["highbidderid"] = user.metadata["ext"]["accountid"]
		for channel in self.ircd.channels.itervalues():
			for u in channel.users:
				u.sendMessage("PRIVMSG", bidMsg, to=channel.name, prefix=self.bidserv.prefix())
	
	def processParams(self, user, params):
		if "accountid" not in user.metadata["ext"]:
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
		if "services_bidserv_increment" in self.ircd.servconfig and bid < self.bidserv.cache["auction"]["highbid"] + self.ircd.servconfig["services_bidserv_increment"]:
			user.sendMessage("NOTICE", ":The minimum bid increment is ${:,.2f}.".format(self.ircd.servconfig["services_bidserv_increment"]), prefix=self.bidserv.prefix())
		return {
			"user": user,
			"bid": bid,
			"smacktalk": " ".join(params[1:]).strip()
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
			for u in channel.users:
				u.sendMessage("PRIVMSG", revertMsg, to=channel.name, prefix=self.bidserv.prefix())
	
	def processParams(self, user, params):
		if "o" not in user.mode:
			user.sendMessage("NOTICE", ":Unknown command \x02REVERT\x02.  Use \x1F/msg {} HELP\x1F for help.".format(self.bidserv.nickname), prefix=self.bidserv.prefix())
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
			for u in channel.users:
				u.sendMessage("PRIVMSG", onceMsg, to=channel.name, prefix=self.bidserv.prefix())
	
	def processParams(self, user, params):
		if "o" not in user.mode:
			user.sendMessage("NOTICE", ":Unknown command \x02ONCE\x02.  Use \x1F/msg {} HELP\x1F for help.".format(self.bidserv.nickname), prefix=self.bidserv.prefix())
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
			for u in channel.users:
				u.sendMessage("PRIVMSG", twiceMsg, to=channel.name, prefix=self.bidserv.prefix())
	
	def processParams(self, user, params):
		if "o" not in user.mode:
			user.sendMessage("NOTICE", ":Unknown command \x02TWICE\x02.  Use \x1F/msg {} HELP\x1F for help.".format(self.bidserv.nickname), prefix=self.bidserv.prefix())
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
		soldMsg = ":\x02\x034Sold! {} to {} for ${:,.2f}!\x02 - Called by {}".format(self.bidserv.cache["auction"]["name"], self.bidserv.cache["auction"]["highbidder"], self.bidserv.cache["auction"]["bid"], user.nickname)
		for channel in self.ircd.channels.itervalues():
			for u in channel.users:
				u.sendMessage("PRIVMSG", soldMsg, to=channel.name, prefix=self.bidserv.prefix())
		if self.bidserv.cache["auction"]["highbidder"] in self.ircd.users:
			udata = self.ircd.users[self.bidserv.cache["auction"]["highbidder"]]
			if "accountid" in udata.metadata["ext"] and udata.metadata["ext"]["accountid"] == self.bidserv.cache["auction"]["highbidderid"]:
				udata.sendMessage("Congratulations!  You won \"{}\"!  Please log into your donor account and visit https://desertbus.org/donate?type=auction&prize={!s} to pay for your prize.".format(self.bidserv.cache["auction"]["name"], self.bidserv.cache["auction"]["item"]), prefix=self.bidserv.prefix())
		d = self.query("UPDATE prizes SET donor_id = {0}, sold_amount = {0}, sold = 1 WHERE id = {0}", self.bidserv.cache["auction"]["highbidderid"], self.bidserv.cache["auction"]["highbid"], self.bidserv.cache["auction"]["item"])
		d.addErrback(self.reportError, user)
		del self.bidserv.cache["auction"]
	
	def processParams(self, user, params):
		if "o" not in user.mode:
			user.sendMessage("NOTICE", ":Unknown command \x02SOLD\x02.  Use \x1F/msg {} HELP\x1F for help.".format(self.bidserv.nickname), prefix=self.bidserv.prefix())
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
		log = "{}/auction_{!s}.log".format(self.ircd.app_log_dir, id)
		count = 1
		while os.path.exists(log):
			log = "{}/auction_{!s}-{!s}.log".format(self.ircd.app_log_dir, id, count)
			count += 1
		return log
	
	def reportError(self, results, user):
		user.sendMessage("NOTICE", ":An error occurred updating the database with the winner ({} with ID {} for amount ${:,.2f}).".format(self.bidserv.cache["auction"]["highbidder"], self.bidserv.cache["auction"]["highbidderid"], self.bidserv.cache["auction"]["highbid"]), prefix=self.bidserv.prefix())

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
		self.helpText["nickserv"][1]["NICKLIST"] = ["Lists all the nicknames registered to your account", "Syntax: \x02LIST\x02\n\nLists all the nicknames registered to your account.", False]
		self.helpText["nickserv"][1]["ACCOUNT"] = ["Gives the account ID or nick provided the other", "Syntax: \x02ACCOUNT \x1Fnick|id\x1F\x02\n\nGives the account ID for the provided nick or the nicks associated with the provided account ID.  This is really only useful for use with ChanServ's access lists.", False]
		
		self.helpText["chanserv"][1]["HELP"] = ["Shows command help", "Syntax: \x02HELP \x1F[command]\x1F\x02\n\nDisplays command help.  With the optinoal command parameter, displays help for the given command.", False]
		self.helpText["chanserv"][1]["REGISTER"] = ["Registers a channel for your use", "Syntax: \x02REGISTER \x1Fchannel\x1F\x02\n\nRegisters a channel with you as a founder.  You must be a channel op or higher in the specified channel in order to register the channel.", False]
		self.helpText["chanserv"][1]["ACCESS"] = ["Allows you to change the access level of another user in a channel you own", "Syntax: \x02ACCESS \x1Fchannel\x1F [\x1Faccount|nick|group\x1F \x1Fflags\x1F]\x02\n\nLists or changes access information for a channel.  If an account is not specified, the channel's access list will be displayed.  If an account and flags are specified, the given flag changes will be applied to the given account in the channel.  Valid flags are any channel status mode level, and they are automatically applied to matching users on join or identify.  The group parameter can be any of the following:\n\t~o\tAll opered users\n\t~r\tAll registered and identified users", False]
		
		self.helpText["bidserv"][1]["HELP"] = ["Shows command help", "Syntax: \x02HELP \x1F[command]\x1F\x02\n\nDisplays command help.  With the optional command parameter, displays help for the given command.", False]
		self.helpText["bidserv"][1]["START"] = ["Start an auction", "Syntax: \x02START \x1FItemID\x1F\x02\n\nStarts an auction with the given item ID.", True]
		self.helpText["bidserv"][1]["STOP"] = ["Cancel the current auction", "Syntax: \x02STOP\x02\n\nStops and cancels the currently running auction, and logs the bid history.", True]
		self.helpText["bidserv"][1]["BID"] = ["Bid in the active auction", "Syntax: \x02BID \x1Famount\x1F \x1F[smacktalk]\x1F\x02\n\nDuring an auction, this command allows the user to place a bid.  If the bid is higher than the last successful bid, BidServ will display it along with any provided smack talk.", False]
		self.helpText["bidserv"][1]["REVERT"] = ["Cancel the highest bid", "Syntax: \x02REVERT\x02\n\nRemoves the highest bid from the auction, returning the auction to the state of the bid before that.", True]
		self.helpText["bidserv"][1]["ONCE"] = ["Call \"Going Once!\"", "Syntax: \x02ONCE\x02\n\nCalls \"Going Once!\" to the crowd.", True]
		self.helpText["bidserv"][1]["TWICE"] = ["Call \"Going Twice!\"", "Syntax: \x02TWICE\x02\n\nCalls \"Going Twice!\" to the crowd.  Use with caution, as this command is known to make the crowd go crazy and arouse bid snipers.", True]
		self.helpText["bidserv"][1]["SOLD"] = ["Award the auction to the highest bidder", "Syntax: \x02SOLD\x02\n\nDeclares the auction as complete, awarding the prize to the highest bidder.", True]
		self.helpText["bidserv"][1]["HIGHBIDDER"] = ["Get the high bidder in the current auction", "Syntax: \x02HIGHBIDDER\x02\n\nDisplays the high bidder in the current auction along with the amount of the current high bid.", False]
		
		self.nickserv = None
		self.chanserv = None
		self.bidserv = None
		
		self.auth_timer = {}
	
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
		
		self.ircd.users["NickServ"] = self.nickserv
		self.ircd.localusers["NickServ"] = self.nickserv
		self.ircd.users["ChanServ"] = self.chanserv
		self.ircd.localusers["ChanServ"] = self.chanserv
		self.ircd.users["BidServ"] = self.bidserv
		self.ircd.localusers["BidServ"] = self.bidserv
		
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
				"ACCOUNT": NSAccountCommand(self, self.nickserv),
				
				"REGISTER": CSRegisterCommand(self, self.chanserv),
				"ACCESS": CSAccessCommand(self, self.chanserv),
				
				"START": BSStartCommand(self, self.bidserv),
				"STOP": BSStopCommand(self, self.bidserv),
				"BID": BSBidCommand(self, self.bidserv),
				"REVERT": BSRevertCommand(self, self.bidserv),
				"ONCE": BSOnceCommand(self, self.bidserv),
				"TWICE": BSTwiceCommand(self, self.bidserv),
				"SOLD": BSSoldCommand(self, self.bidserv),
				"HIGHBIDDER": BSHighbidderCommand(self, self.bidserv)
			},
			"actions": {
				"register": [self.onRegister],
				"join": [self.promote],
				"quit": [self.onQuit],
				"nick": [self.onNickChange],
				"commandpermission": [self.commandPermission]
			}
		}
	
	def cleanup(self):
		if self.db:
			self.db.close()
		
		del self.ircd.users["NickServ"]
		del self.ircd.localusers["NickServ"]
		del self.ircd.users["ChanServ"]
		del self.ircd.localusers["ChanServ"]
		del self.ircd.users["BidServ"]
		del self.ircd.localusers["BidServ"]
		
		del self.ircd.commands["NICKSERV"]
		del self.ircd.commands["NS"]
		del self.ircd.commands["CHANSERV"]
		del self.ircd.commands["CS"]
		del self.ircd.commands["BIDSERV"]
		del self.ircd.commands["BS"]
		
		del self.ircd.commands["IDENTIFY"]
		del self.ircd.commands["ID"]
		del self.ircd.commands["GHOST"]
		del self.ircd.commands["LOGIN"]
		del self.ircd.commands["LOGOUT"]
		del self.ircd.commands["DROP"]
		del self.ircd.commands["NICKLIST"]
		del self.ircd.commands["ACCOUNT"]
		
		del self.ircd.commands["REGISTER"]
		del self.ircd.commands["ACCESS"]
		
		del self.ircd.commands["START"]
		del self.ircd.commands["STOP"]
		del self.ircd.commands["BID"]
		del self.ircd.commands["REVERT"]
		del self.ircd.commands["ONCE"]
		del self.ircd.commands["TWICE"]
		del self.ircd.commands["SOLD"]
		del self.ircd.commands["HIGHBIDDER"]
		
		self.ircd.actions["register"].remove(self.onRegister)
		self.ircd.actions["join"].remove(self.promote)
		self.ircd.actions["quit"].remove(self.onQuit)
		self.ircd.actions["nick"].remove(self.onNickChange)
		self.ircd.actions["commandpermission"].remove(self.commandPermission)
	
	def data_serialize(self):
		if "auction" in self.bidserv.cache:
			return [True, {
				"registeredchannels": self.chanserv.cache["registered"]._data,
				"currentauction": self.bidserv.cache["auction"]
			}]
		return [True, {
			"registeredchannels": self.chanserv.cache["registered"]._data
		}]
	
	def data_unserialize(self, data):
		if "currentauction" in data:
			self.bidserv.cache["auction"] = data["currentauction"]
		if "registered" not in self.chanserv.cache:
			self.chanserv.cache["registered"] = CaseInsensitiveDictionary()
		for key, value in data["registeredchannels"]:
			self.chanserv.cache["registered"][key] = value
	
	# Services Functions
	def query(self, query, *args):
		query = query.format(self.ircd.servconfig["servdb_marker"])
		return self.db.runQuery(query, args)
	
	def exclaimServerError(self, result, user, service):
		user.sendMessage("NOTICE", ":A server error has occurred.", prefix=service.prefix())
	
	def genGuestNick(self):
		nick = "{}{:>06d}".format(self.ircd.servconfig["services_nickserv_guest_prefix"] if "services_nickserv_guest_prefix" in self.ircd.servconfig and self.ircd.servconfig["services_nickserv_guest_prefix"] else "Guest", random.randrange(1000000))
		if nick in self.ircd.users:
			return self.genGuestNick()
		return nick
	
	def auth(self, user, username, password):
		d = self.query("SELECT id, password, display_name FROM donors WHERE email = {0}", username)
		d.addCallback(self.verifyPassword, user, password)
		d.addErrback(self.exclaimServerError, user, self.nickserv)
		return d
	
	def token(self, user, password):
		d = self.query("SELECT donor_id FROM irctokens WHERE token = {0}", password)
		d.addCallback(self.loadDonorInfo, user)
		return d
	
	def checkNick(self, user):
		if user in self.auth_timer:
			self.auth_timer[user].cancel()
			del self.auth_timer[user]
		if irc_lower(user.nickname).startswith(irc_lower(self.ircd.servconfig["services_nickserv_guest_prefix"])):
			return # Don't check guest nicks
		d = self.query("SELECT donor_id FROM ircnicks WHERE nick = {0}", irc_lower(user.nickname))
		d.addCallback(self.beginVerify, user)
		return d
	
	def verifyPassword(self, result, user, password):
		if not result:
			self.checkNick(user)
			user.sendMessage("NOTICE", ":The login credentials you provided were incorrect.", prefix=self.nickserv.prefix())
			return
		hash = result[0][1]
		check = crypt(password, hash)
		if check == hash:
			user.setMetadata("ext", "accountid", result[0][0])
			user.setMetadata("ext", "accountname", result[0][2].replace(" ", "_"))
			if user in self.auth_timer:
				self.auth_timer[user].cancel()
				del self.auth_timer[user]
			user.sendMessage("NOTICE", ":You are now identified. Welcome, {}.".format(user.metadata["ext"]["accountname"]), prefix=self.nickserv.prefix())
			self.checkNick(user)
			self.registered(user)
		else:
			self.checkNick(user)
			user.sendMessage("NOTICE", ":The login credentials you provided were incorrect.", prefix=self.nickserv.prefix())
	
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
			id = result[0][0]
			if "accountid" in user.metadata["ext"] and user.metadata["ext"]["accountid"] == id:
				if user in self.auth_timer: # Clear the timer
					self.auth_timer[user].cancel()
					del self.auth_timer[user]
				return # Already identified
			user.sendMessage("NOTICE", ":This is a registered nick. Please use \x02/msg {} login EMAIL PASSWORD\x0F to verify your identity.".format(self.nickserv.nickname), prefix=self.nickserv.prefix())
			if user in self.auth_timer:
				self.auth_timer[user].cancel() # In case we had another going
			self.auth_timer[user] = reactor.callLater(self.ircd.servconfig["services_nickserv_timeout"] if "services_nickserv_timeout" in self.ircd.servconfig else 60, self.changeNick, user, id, user.nickname)
		elif "accountid" in user.metadata["ext"]:
			# Try to register the nick
			d = self.query("SELECT nick FROM ircnicks WHERE donor_id = {0}", user.metadata["ext"]["accountid"])
			d.addCallback(self.registerNick, user, nickname)
			d.addErrback(self.failedRegisterNick, user, nickname)
	
	def setDonorInfo(self, result, user):
		if not result:
			self.checkNick(user)
			self.exclaimServerError(user, self.nickserv)
			return
		user.setMetadata("ext", "accountid", result[0][0])
		user.setMetadata("ext", "accountname", result[0][1])
		if user in self.auth_timer:
			self.auth_timer[user].cancel()
			del self.auth_timer[user]
		user.sendMessage("NOTICE", ":You are now identified. Welcome, {}.".format(user.metadata["ext"]["accountname"]), prefix=self.nickserv.prefix())
		self.checkNick(user)
		self.registered()
	
	def changeNick(self, user, id, nickname):
		if user in self.auth_timer:
			del self.auth_timer[user]
		if "accountid" in user.metadata["ext"] and user.metadata["ext"]["accountid"] == id:
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
			d = self.query("INSERT INTO ircnicks(donor_id, nick) VALUES({0},{0})", user.metadata["ext"]["accountid"], irc_lower(nickname))
			d.addCallback(self.successRegisterNick, user, nickname)
			d.addErrback(self.failedRegisterNick, user, nickname)
	
	def failedRegisterNick(self, result, user, nickname):
		user.sendMessage("NOTICE", ":Failed to register nick {} to account {}. Other users may still use it.".format(nickname, user.metadata["ext"]["accountname"]), prefix=self.nickserv.prefix())
	
	def successRegisterNick(self, result, user, nickname):
		user.sendMessage("NOTICE", ":Nickname {} is now registered to account {} and can not be used by any other user.".format(nickname, user.metadata["ext"]["accountname"]), prefix=self.nickserv.prefix())
	
	def registered(self, user):
		for channel in user.channels.iterkeys():
			c = self.ircd.channels[channel]
			self.promote(user, c)
	
	def unregistered(self, user):
		for channel, data in user.channels.iteritems():
			c = self.ircd.channels[channel]
			status = data["status"]
			if status:
				for u in c.users:
					u.sendMessage("MODE", "-{} {}".format(status, " ".join([user.nickname for i in len(status)])), to=c.name, prefix=self.chanserv.prefix())
				data["status"] = ""
	
	def promote(self, user, channel):
		if channel.name in self.chanserv.cache["registered"]:
			flags = set()
			if "o" in user.mode and "~o" in self.chanserv.cache["registered"][channel.name]["access"]:
				for flag in self.chanserv.cache["registered"][channel.name]["access"]["~o"]:
					flags.add(flag)
			if "accountid" in user.metadata["ext"]:
				if "~r" in self.chanserv.cache["registered"][channel.name]["access"]:
					for flag in self.chanserv.cache["registered"][channel.name]["access"]["~r"]:
						flags.add(flag)
				if user.metadata["ext"]["accountid"] in self.chanserv.cache["registered"][channel.name]["access"]:
					for flag in self.chanserv.cache["registered"][channel.name]["access"][user.metadata["ext"]["accountid"]]:
						flags.add(flag)
			for flag in user.status(channel.name):
				try:
					flags.remove(flag)
				except KeyError:
					pass
			
			if flags:
				for flag in flags:
					currentStatus = user.channels[channel.name]["status"]
					statusList = list(currentStatus)
					for index, statusLevel in enumerate(status):
						if self.ircd.prefixes[statusLevel][1] < self.ircd.prefixes[flag][1]:
							statusList.insert(index, flag)
							break
					if flag not in statusList:
						statusList.append(flag)
					user.channels[channel.name]["status"] = "".join(statusList)
				
				modeMsg = "+{} {}".format("".join(flags), " ".join([user.nickname for i in flags]))
				for u in channel.users:
					u.sendMessage("MODE", modeMsg, to=channel.name, prefix=self.chanserv.prefix())
	
	def onRegister(self, user):
		if user.password:
			if ":" in user.password:
				email, password = user.password.split(":", 1)
				self.auth(user, email, password)
			elif " " in user.password:
				email, password = user.password.split(":", 1)
				self.auth(user, email, password)
			else:
				self.token(user, user.password)
		self.checkNick(user)
		return True
	
	def onQuit(self, user, reason):
		if user in self.auth_timer:
			self.auth_timer[user].cancel()
			del self.auth_timer[user]
	
	def onNickChange(self, user, oldNick):
		if irc_lower(user.nickname) != irc_lower(oldNick):
			self.checkNick(user)
	
	def commandPermission(self, user, cmd, data):
		if user not in self.auth_timer:
			return data
		if cmd == "PRIVMSG":
			to_nickserv = False
			for u in data["targetuser"]:
				if irc_lower(u) == irc_lower(self.nickserv.nickname):
					to_nickserv = True
					break
			if to_nickserv:
				data["targetuser"] = [self.nickserv.nickname]
				data["targetchan"] = []
				return data
			user.sendMessage("NOTICE", ":You cannot message anyone other than NickServ until you identify or change nicks.", prefix=self.nickserv.prefix())
			return {}
		if cmd in [ "PING", "PONG", "NICK", "QUIT", "NS", "NICKSERV", "LOGIN", "ID", "IDENTIFY" ]:
			return data
		user.sendMessage("NOTICE", ":You cannot use that command until you identify or change nicks.", prefix=self.nickserv.prefix())
		return {}