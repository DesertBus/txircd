from twisted.words.protocols import irc
from txircd.modbase import Command
from txircd.utils import epoch, now, irc_lower, parse_duration, CaseInsensitiveDictionary
from fnmatch import fnmatch

irc.RPL_STATSKLINE = "223"

class KlineCommand(Command):
	def __init__(self):
		self.banList = CaseInsensitiveDictionary()
	
	def onUse(self, user, data):
		if "reason" in data:
			self.banList[data["mask"]] = {
				"setter": user.prefix(),
				"created": epoch(now()),
				"duration": data["duration"],
				"reason": data["reason"]
			}
			now_banned = {}
			for nick, u in self.ircd.users.iteritems():
				result = self.match_kline(u)
				if result:
					now_banned[nick] = result
			for uid, reason in now_banned.iteritems():
				udata = self.ircd.users[uid]
				udata.sendMessage("NOTICE", ":{}".format(self.ircd.servconfig["client_ban_msg"]))
				quit_to = set()
				leavingChans = udata.channels.keys()
				for chan in leavingChans:
					cdata = self.ircd.channels[chan]
					udata.leave(cdata)
					for u in cdata.users:
						quit_to.add(u)
				for u in quit_to:
					u.sendMessage("QUIT", ":K:Lined: {}".format(reason), to=None, prefix=udata.prefix())
				udata.sendMessage("ERROR", ":Closing Link {} [K:Lined: {}]".format(udata.prefix(), data["reason"]), to=None, prefix=None)
				del self.ircd.users[udata.nickname]
				udata.socket.transport.loseConnection()
		else:
			del self.banList[data["mask"]]
	
	def processParams(self, user, params):
		if user.registered > 0:
			user.sendMessage(irc.ERR_NOTYETREGISTERED, "KLINE", ":You have not registered")
			return {}
		if "o" not in user.mode:
			user.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - You do not have the correct operator privileges")
			return {}
		if not params:
			user.sendMessage(irc.ERR_NEEDMOREPARAMS, "KLINE", ":Not enough parameters")
			return {}
		banmask = params[0]
		if banmask in self.ircd.users:
			banmask = "{}@{}".format(user.username, user.hostname)
		elif "@" not in banmask:
			banmask = "*@{}".format(banmask)
		self.expire_klines()
		if len(params) < 3 or not params[2]:
			if banmask not in self.banList:
				user.sendMessage("NOTICE", ":*** K:line for {} does not currently exist; check /stats K for a list of active k:lines".format(banmask))
				return {}
			return {
				"user": user,
				"mask": banmask
			}
		else:
			if banmask in self.banList:
				user.sendMessage("NOTICE", ":*** There's already a k:line set on {}!".format(banmask))
				return {}
			return {
				"user": user,
				"mask": banmask,
				"duration": parse_duration(params[1]),
				"reason": " ".join(params[2:])
			}
	
	def statsList(self, cmd, data):
		if cmd != "STATS":
			return
		if data["statstype"] != "K":
			return
		self.expire_klines()
		user = data["user"]
		for mask, linedata in self.banList.iteritems():
			user.sendMessage(irc.RPL_STATSKLINE, ":{} {} {} {} :{}".format(mask, linedata["created"], linedata["duration"], linedata["setter"], linedata["reason"]))
	
	def register_check(self, user):
		result = self.match_kline(user)
		if not result:
			if result == None:
				return True
			return "again"
		user.sendMessage("NOTICE", ":{}".format(self.ircd.servconfig["client_ban_msg"]))
		user.sendMessage("ERROR", ":Closing Link: {} [K:Lined: {}]".format(user.hostname, result), to=None, prefix=None)
		return False
	
	def match_kline(self, user):
		if "o" in user.mode:
			return None # don't allow bans to affect opers
		if "except_line" not in user.cache:
			if "kline_match" in user.cache:
				return user.cache["kline_match"]
			# Determine whether the user matches
			self.expire_klines()
			match_against = irc_lower("{}@{}".format(user.username, user.hostname))
			for mask, linedata in self.banList.iteritems():
				if fnmatch(match_against, mask):
					user.cache["kline_match"] = linedata["reason"]
					return ""
			match_against = irc_lower("{}@{}".format(user.username, user.ip))
			for mask in self.banList.iterkeys(): # we just removed expired lines
				if fnmatch(match_against, mask):
					user.cache["kline_match"] = linedata["reason"]
					return ""
			return None
		else:
			if user.cache["except_line"]:
				return None
			if "kline_match" in user.cache:
				return user.cache["kline_match"]
			self.expire_klines()
			match_against = irc_lower("{}@{}".format(user.username, user.hostname))
			for mask, linedata in self.banList.iteritems():
				if fnmatch(match_against, mask):
					return linedata["reason"]
			match_against = irc_lower("{}@{}".format(user.username, user.ip))
			for mask in self.banList.iterkeys(): # we just removed expired lines
				if fnmatch(match_against, mask):
					return linedata["reason"]
			return None
	
	def expire_klines(self):
		current_time = epoch(now())
		expired = []
		for mask, linedata in self.banList.iteritems():
			if linedata["duration"] and current_time > linedata["created"] + linedata["duration"]:
				expired.append(mask)
		for mask in expired:
			del self.banList[mask]

class Spawner(object):
	def __init__(self, ircd):
		self.ircd = ircd
		self.klineCmd = None
	
	def spawn(self):
		self.klineCmd = KlineCommand()
		return {
			"commands": {
				"KLINE": self.klineCmd
			},
			"actions": {
				"commandextra": [self.klineCmd.statsList],
				"register": [self.klineCmd.register_check],
				"xline_rematch": [self.klineCmd.match_kline]
			}
		}
	
	def cleanup(self):
		del self.ircd.commands["KLINE"]
		self.ircd.actions["commandextra"].remove(self.klineCmd.statsList)
		self.ircd.actions["register"].remove(self.klineCmd.register_check)
		self.ircd.actions["xline_rematch"].remove(self.klineCmd.match_kline)