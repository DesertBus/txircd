from twisted.words.protocols import irc
from txircd.modbase import Command

irc.RPL_LOCALUSERS = "265"
irc.RPL_GLOBALUSERS = "266"

class LusersCommand(Command):
	def __init__(self):
		self.maxLocal = 0
		self.maxGlobal = 0
	
	def onUse(self, user, data):
		userCount = 0
		invisibleCount = 0
		operCount = 0
		localCount = 0
		globalCount = 0
		for u in self.ircd.users.itervalues():
			if "i" in user.mode:
				invisibleCount += 1
			else:
				userCount += 1
			if "o" in user.mode:
				operCount += 1
			if u.server == self.ircd.servconfig["server_name"]:
				localCount += 1
			globalCount += 1
		serverCount = len(self.ircd.servers)
		netServerCount = serverCount + 1
		user.sendMessage(irc.RPL_LUSERCLIENT, ":There are {} users and {} invisible on {} server{}.".format(userCount, invisibleCount, netServerCount, "" if netServerCount == 1 else "s"))
		user.sendMessage(irc.RPL_LUSEROP, str(operCount), ":operator(s) online")
		user.sendMessage(irc.RPL_LUSERCHANNELS, str(len(self.ircd.channels)), ":channels formed")
		user.sendMessage(irc.RPL_LUSERME, ":I have {} clients and {} servers".format(localCount, serverCount))
		user.sendMessage(irc.RPL_LOCALUSERS, ":Current Local Users: {}  Max: {}".format(localCount, self.maxLocal))
		user.sendMessage(irc.RPL_GLOBALUSERS, ":Current Global Users: {}  Max: {}".format(globalCount, self.maxGlobal))
	
	def checkMax(self, user):
		globalUserCount = len(self.ircd.users) + 1 # Register hook is called BEFORE the user is added to the dictionary
		localUserCount = 0
		for u in self.ircd.users.itervalues():
			if u.server == self.ircd.servconfig["server_name"]:
				localUserCount += 1
		if localUserCount > self.maxLocal:
			self.maxLocal = localUserCount
		if globalUserCount > self.maxGlobal:
			self.maxGlobal = globalUserCount
		return True

class Spawner(object):
	def __init__(self, ircd):
		self.ircd = ircd
		self.lusersCmd = None
	
	def spawn(self):
		self.lusersCmd = LusersCommand()
		return {
			"commands": {
				"LUSERS": self.lusersCmd
			},
			"actions": {
				"register": [self.lusersCmd.checkMax]
			}
		}
	
	def cleanup(self):
		del self.ircd.commands["LUSERS"]
		self.ircd.actions["register"].remove(self.lusersCmd.checkMax)