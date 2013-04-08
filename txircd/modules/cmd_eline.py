from twisted.words.protocols import irc
from txircd.modbase import Command
from txircd.utils import epoch, now, irc_lower, parse_duration, CaseInsensitiveDictionary
from fnmatch import fnmatch

irc.RPL_STATSELINE = "223"

class ElineCommand(Command):
	def __init__(self):
		self.exceptList = CaseInsensitiveDictionary()
	
	def onUse(self, user, data):
		if "reason" in data:
			self.exceptList[data["mask"]] = {
				"setter": user.nickname,
				"created": epoch(now()),
				"duration": data["duration"],
				"reason": data["reason"]
			}
			user.sendMessage("NOTICE", ":*** E:Line set on {}, to expire in {} seconds".format(data["mask"], data["duration"]))
		else:
			mask = data["mask"]
			del self.exceptList[mask]
			user.sendMessage("NOTICE", ":*** E:Line removed on {}".format(mask))
			for u in self.ircd.users.itervalues():
				if self.match_eline(u):
					u.cache["except_line"] = True
			now_banned = {}
			for uid, udata in self.ircd.users.iteritems():
				for modfunc in self.ircd.actions["xline_rematch"]:
					reason = modfunc(udata)
					if reason:
						now_banned[uid] = reason
						break # If the user is banned, the user is banned. We don't need to gather a consensus or something.
			for uid, reason in now_banned.iteritems():
				udata = self.ircd.users[uid]
				udata.sendMessage("NOTICE", ":{}".format(self.ircd.servconfig["client_ban_msg"]))
				udata.disconnect("Banned: Exception Removed ({})".format(reason))
	
	def processParams(self, user, params):
		if user.registered > 0:
			user.sendMessage(irc.ERR_NOTYETREGISTERED, "ELINE", ":You have not registered")
			return {}
		if "o" not in user.mode:
			user.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - You do not have the correct operator privileges")
			return {}
		if not params:
			user.sendMessage(irc.ERR_NEEDMOREPARAMS, "ELINE", ":Not enough parameters")
			return {}
		banmask = params[0]
		if banmask in self.ircd.users:
			udata = self.ircd.users[banmask]
			banmask = "{}@{}".format(udata.username, udata.hostname)
		elif "@" not in banmask:
			banmask = "*@{}".format(banmask)
		self.expire_elines()
		if len(params) < 3 or not params[2]:
			if banmask not in self.exceptList:
				user.sendMessage("NOTICE", ":*** E:line for {} not found! Check /stats E to view currently set e:lines.".format(banmask))
				return {}
			return {
				"user": user,
				"mask": banmask
			}
		if banmask in self.exceptList:
			user.sendMessage("NOTICE", ":*** An e:line is already set on {}!  Check /stats E to view currently set e:lines.".format(banmask))
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
		if data["statstype"] != "E":
			return
		self.expire_elines()
		user = data["user"]
		for mask, linedata in self.exceptList.iteritems():
			user.sendMessage(irc.RPL_STATSELINES, "{} {} {} {} :{}".format(mask, linedata["created"], linedata["duration"], linedata["setter"], linedata["reason"]))
	
	def check_register(self, user):
		if self.match_eline(user):
			user.cache["except_line"] = True
		return True
	
	def match_eline(self, user):
		self.expire_elines()
		matchMask = irc_lower("{}@{}".format(user.username, user.hostname))
		for mask, linedata in self.exceptList.iteritems():
			if fnmatch(matchMask, mask):
				user.cache["except_line"] = True
				return linedata["reason"]
		matchMask = irc_lower("{}@{}".format(user.username, user.ip))
		for mask, linedata in self.exceptList.iteritems():
			if fnmatch(matchMask, mask):
				user.cache["except_line"] = True
				return linedata["reason"]
		user.cache["except_line"] = False
		return None
	
	def expire_elines(self):
		current_time = epoch(now())
		expired = []
		for mask, linedata in self.exceptList.iteritems():
			if linedata["duration"] and current_time > linedata["created"] + linedata["duration"]:
				expired.append(mask)
		for mask in expired:
			del self.exceptList[mask]

class Spawner(object):
	def __init__(self, ircd):
		self.ircd = ircd
		self.elineCmd = None
	
	def spawn(self):
		self.elineCmd = ElineCommand()
		return {
			"commands": {
				"ELINE": self.elineCmd
			},
			"actions": {
				"commandextra": [self.elineCmd.statsList],
				"register": [self.elineCmd.check_register]
			}
		}
	
	def cleanup(self):
		del self.ircd.commands["ELINE"]
		self.ircd.actions["commandextra"].remove(self.elineCmd.statsList)
		self.ircd.actions["register"].remove(self.elineCmd.check_register)
	
	def data_serialize(self):
		return [True, self.elineCmd.exceptList._data]
	
	def data_unserialize(self, data):
		for mask, linedata in data.iteritems():
			self.elineCmd.exceptList[mask] = linedata