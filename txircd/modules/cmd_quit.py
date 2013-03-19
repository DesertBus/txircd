from twisted.words.protocols import irc
from txircd.modbase import Command

class QuitCommand(Command):
	def onUse(self, user, data):
		reason = "Quit: {}".format(data["reason"]) if "reason" in data and data["reason"] else "Client Quit"
		if user.registered == 0:
			quit_to = set()
			leavingChans = user.channels.keys()
			for chan in leavingChans:
				cdata = self.ircd.channels[chan]
				user.leave(cdata)
				for u in cdata.users:
					quit_to.add(u)
			for u in quit_to:
				u.sendMessage("QUIT", ":{}".format(reason), to=None, prefix=user.prefix())
			user.sendMessage("ERROR", ":Closing Link {} [{}]".format(user.prefix(), reason), to=None, prefix=None)
			del self.ircd.users[user.nickname]
		else:
			user.sendMessage("ERROR", ":Closing Link {} [{}]".format(user.hostname, reason), to=None, prefix=None)
		user.socket.transport.loseConnection()
	
	def processParams(self, user, params):
		reason = params[0] if params and params[0] else "Client exited"
		return {
			"user": user,
			"reason": reason
		}

class Spawner(object):
	def __init__(self, ircd):
		self.ircd = ircd
	
	def spawn(self):
		return {
			"commands": {
				"QUIT": QuitCommand()
			}
		}
	
	def cleanup(self):
		del self.ircd.commands["QUIT"]