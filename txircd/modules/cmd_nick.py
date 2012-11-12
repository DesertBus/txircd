from twisted.words.protocols import irc
from txircd.modbase import Command
from txircd.utils import VALID_USERNAME, irc_lower

class NickCommand(command):
	def onUse(self, user, params):
		if not params:
			user.sendMessage(irc.ERR_NONICKNAMEGIVEN, ":No nickname given")
			return
		if not params[0]:
			user.sendMessage(irc.ERR_ERRONEUSNICKNAME, "*", ":Erroneous nickname")
			return
		if not VALID_USERNAME.match(params[0]):
			user.sendMessage(irc.ERR_ERRONEUSNICKNAME, params[0], ":Erroneous nickname")
			return
		if params[0] in self.ircd.users and irc_lower(params[0]) != irc_lower(user.nickname):
			user.sendMessage(irc.ERR_NICKNAMEINUSE, self.ircd.users[params[0]].nickname, ":Nickname is already in use")
			return
		if params[0] == user.nickname:
			return # do nothing when the given nick is the exact same as the user's current nick
		# changing nicks now
		for action in self.ircd.actions:
			action.onCommandExtra("NICK", params)
		if user.registered == 0:
			del self.ircd.users[user.nickname]
			self.ircd.users[params[0]] = user
			notify = set()
			notify.append(user)
			for chan in user.channels.iterkeys():
				cdata = self.ircd.channels[chan]
				del cdata.users[user.nickname]
				cdata.users[params[0]] = user
				for cuser in cdata.users:
					notify.append(cuser)
			oldprefix = user.prefix()
			user.nickname = params[0]
			for u in notify:
				u.sendMessage("NICK", to=params[0], prefix=oldprefix)
		else:
			user.nickname = params[0]
			user.registered -= 1
			if user.registered == 0:
				user.register()

def spawn():
	return {
		"commands": {
			"NICK": NickCommand()
		}
	}