from txircd.utils import CaseInsensitiveDictionary, now()

class IRCChannel(object):
	def __init__(self, name):
		self.name = name
		self.created = now()
		self.topic = ""
		self.topicSetter = ""
		self.topicTime = now()
		self.mode = {}
		self.users = CaseInsensitiveDictionary()
	
	def name(self):
		return self.name
	
	def getTopic(self):
		return self.topic
	
	def setTopic(self, topic, setter):
		self.topic = topic
		self.topicSetter = setter
		self.topicTime = now()
	
	def setMode(self, modeList):
		pass
	
	def unsetMode(self, modeList):
		pass