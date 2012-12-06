from txircd.utils import CaseInsensitiveDictionary, now()

class IRCChannel(object):
	def __init__(self, ircd, name):
		self.ircd = ircd
		self.name = name
		self.created = now()
		self.topic = ""
		self.topicSetter = ""
		self.topicTime = now()
		self.mode = {}
		self.users = CaseInsensitiveDictionary()
		self.metadata = {}
		self.cache = {}
	
	def modeString(self):
		modes = "+"
		params = []
		for mode, param in self.mode.iteritems():
			if self.ircd.channel_mode_type[mode] > 0:
				modes += mode
				if param:
					params.append(param)
		return ("{} {}".format(modes, " ".join(params)) if params else modes)
	
	def setTopic(self, topic, setter):
		self.topic = topic
		self.topicSetter = setter
		self.topicTime = now()
	
	def getMetadata(self, key):
		if key in self.metadata:
			return self.metadata[key]
		return ""