from twisted.words.protocols import irc
from txircd.modbase import Command
from txircd.utils import epoch, now, irc_lower, parse_duration, CaseInsensitiveDictionary
from fnmatch import fnmatch

class GlineCommand(Command):
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
				result = self.match_gline(u)
				if result:
					now_banned[nick] = result
			for uid, reason in now_banned.iteritems():
				udata = self.ircd.users[uid]
				udata.sendMessage("NOTICE", ":{}".format(self.ircd.client_ban_msg))
				udata.handleCommand("QUIT", None, [reason]) # The rest of this is equivalent to that, so...
		else:
			del self.banList[data["mask"]]
	
	def processParams(self, user, params):
		if user.registered > 0:
			user.sendMessage(irc.ERR_NOTYETREGISTERED, "GLINE", ":You have not registered")
			return {}
		if "o" not in user.mode:
			user.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - You do not have the correct operator privileges")
			return {}
		if not params:
			user.sendMessage(irc.ERR_NEEDMOREPARAMS, "GLINE", ":Not enough parameters")
			return {}
		banmask = params[0]
		if banmask in self.ircd.users:
			banmask = "{}@{}".format(user.username, user.hostname)
		elif "@" not in banmask:
			banmask = "*@{}".format(banmask)
		if len(params) < 3:
			if banmask not in self.banList:
				user.sendMessage("NOTICE", ":*** G:line for {} does not currently exist; check /stats G for a list of active g:lines".format(banmask))
				return {}
			return {
				"user": user,
				"mask": banmask
			}
		else:
			if banmask in self.banList:
				user.sendMessage("NOTICE", ":*** There's already a g:line set on {}!".format(banmask))
				return {}
			return {
				"user": user,
				"mask": banmask,
				"duration": parse_duration(params[1]),
				"reason": " ".join(params[2:])
			}
	
	def statsList(self, cmd, data):
		if data["statstype"] != "G":
			return
		self.expire_glines()
		for mask, linedata in self.banList.iteritems():
			user.sendMessage(irc.RPL_STATSGLINE, ":{} {} {} {} :{}".format(mask, linedata["created"], linedata["duration"], linedata["setter"], linedata["reason"]))
	
	def register_check(self, user):
		result = self.match_gline(user)
		if not result:
			if result == None:
				return True
			return "again"
		user.sendMessage("NOTICE", ":{}".format(self.ircd.client_ban_msg))
		user.sendMessage("ERROR", ":Closing Link: {} [G-Lined: {}]".format(user.hostname, result), to=None, prefix=None)
		return False
	
	def match_gline(self, user):
		if "o" in user.mode:
			return None # don't allow bans to affect opers
		if "except_line" not in user.cache:
			if "gline_match" in user.cache:
				return user.cache["gline_match"]
			# Determine whether the user matches
			self.expire_glines()
			match_against = irc_lower("{}@{}".format(user.username, user.hostname))
			for mask, linedata in self.banList.iteritems():
				if fnmatch(match_against, mask):
					user.cache["gline_match"] = linedata["reason"]
					return ""
			match_against = irc_lower("{}@{}".format(user.username, user.ip))
			for mask in self.banList.iterkeys(): # we just removed expired lines
				if fnmatch(match_against, mask):
					user.cache["gline_match"] = linedata["reason"]
					return ""
			return None
		else:
			if user.cache["except_line"]:
				return None
			if "gline_match" in user.cache:
				return user.cache["gline_match"]
			self.expire_glines()
			match_against = irc_lower("{}@{}".format(user.username, user.hostname))
			for mask, linedata in self.banList.iteritems():
				if fnmatch(match_against, mask):
					return linedata["reason"]
			match_against = irc_lower("{}@{}".format(user.username, user.ip))
			for mask in self.banList.iterkeys(): # we just removed expired lines
				if fnmatch(match_against, mask):
					return linedata["reason"]
			return None
	
	def expire_glines(self):
		current_time = epoch(now())
		expired = []
		for mask, linedata in self.banList.iteritems():
			if linedata["duration"] and current_time > linedata["created"] + linedata["duration"]:
				expired.append(mask)
		for mask in to_expire:
			del self.banList[mask]

class Spawner(object):
	def __init__(self, ircd):
		self.ircd = ircd
		self.glineCmd = None
	
	def spawn(self):
		self.glineCmd = GlineCommand()
		return {
			"commands": {
				"GLINE": self.glineCmd
			},
			"actions": {
				"commandextra": [self.glineCmd.statsList],
				"register": [self.glineCmd.register_check],
				"xline_rematch": [self.glineCmd.match_gline]
			}
		}
	
	def cleanup(self):
		del self.ircd.commands["GLINE"]
		self.ircd.actions["commandextra"].remove(self.glineCmd.statsList)
		self.ircd.actions["register"].remove(self.glineCmd.register_check)
		self.ircd.actions["xline_rematch"].remove(self.glineCmd.match_gline)