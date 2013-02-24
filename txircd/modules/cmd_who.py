from twisted.words.protocols import irc
from txircd.modbase import Command

# TODO: When server-to-server is implemented, replace self.ircd.server_name in the replies with a way to get the (real or masked) server name for each user

class WhoCommand(Command):
	def onUse(self, user, data):
		if "target" not in data:
			for u in self.ircd.users.itervalues():
				if "i" in u.mode:
					continue
				common_channel = False
				for c in self.channels.iterkeys():
					if c in u.channels:
						common_channel = True
						break
				if not common_channel:
					self.sendMessage(irc.RPL_WHOREPLY, "*", u.username, u.hostname, self.ircd.server_name, u.nickname, "{}{}".format("G" if "away" in user.metadata["ext"] else "H", "*" if "o" in user.mode else ""), ":0 {}".format(u.realname))
			self.sendMessage(irc.RPL_ENDOFWHO, self.nickname, "*", ":End of /WHO list.")
		else:
			if data["target"] in self.ircd.channels:
				cdata = self.ircd.channels[data["target"]]
				in_channel = cdata.name in user.channels # cache this value instead of searching self.channels every iteration
				for u in cdata.users.itervalues():
					if (in_channel or "i" not in u.mode) and ("o" not in filters or "o" in u.mode):
						self.sendMessage(irc.RPL_WHOREPLY, cdata.name, u.username, u.hostname, self.ircd.server_name, u.nickname, "{}{}{}".format("G" if "away" in u.metadata["ext"] else "H", "*" if "o" in u.mode else "", self.ircd.prefix_symbols[self.ircd.prefix_order[len(self.ircd.prefix_order) - u.accessLevel(cdata.name)]] if u.accessLevel(cdata.name) > 0 else ""), ":0 {}".format(u.realname))
				self.sendMessage(irc.RPL_ENDOFWHO, cdata.name, ":End of /WHO list.")
			else:
				for u in self.ircd.users.itervalues():
					if "i" not in u.mode and (fnmatch.fnmatch(irc_lower(u.nickname), irc_lower(params[0])) or fnmatch.fnmatch(irc_lower(u.hostname), irc_lower(params[0]))):
						self.sendMessage(irc.RPL_WHOREPLY, params[0], u.username, u.hostname, self.ircd.server_name, u.nickname, "{}{}".format("G" if "away" in u.metadata["ext"] else "H", "*" if "o" in u.mode else ""), ":0 {}".format(u.realname))
				self.sendMessage(irc.RPL_ENDOFWHO, params[0], ":End of /WHO list.") # params[0] is used here for the target so that the original glob pattern is returned
	
	def processParams(self, user, params):
		if user.registered > 0:
			user.sendMessage(irc.ERR_NOTYETREGISTERED, "WHO", ":You have not registered")
			return {}
		if not params:
			return {
				"user": user
			}
		target = params[0]
		filters = params[1] if len(params) > 1 else ""
		if target[0][0] in self.ircd.channel_prefixes and target not in self.ircd.channels:
			user.sendMessage(irc.RPL_ENDOFWHO, channel, ":End of /WHO list")
			return {}
		return {
			"user": user,
			"target": target,
			"filters": filters
		}

def Spawner(object):
	def __init__(self, ircd):
		self.ircd = ircd
	
	def spawn(self):
		return {
			"commands": {
				"WHO": WhoCommand()
			}
		}
	
	def cleanup(self):
		del self.ircd.command["WHO"]