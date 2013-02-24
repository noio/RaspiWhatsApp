#!/usr/bin/env python

### IMPORTS ###

import os
import sys
import base64
import time
import datetime
import urllib2
import Queue

parentdir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'yowsup', 'src')
sys.path.insert(0,parentdir)

# LOCAL

from PIL import Image
from escpos import printer
from Yowsup.connectionmanager import YowsupConnectionManager

### CONSTANTS ###

### FUNCTIONS ###

def loadConfigFile(configfile):
	""" Loads a yowsup style config file and returns
		values as a dictionary 
	"""
	config = {}
	if os.path.isfile(configfile):
		for line in open(configfile):
			# Remove bits after the comment marker
			line = line.split('#')[0].strip()
			# If anything is left
			if line:
				print line
				# Split by first equals sign
				key, val = line.split('=',1)
				config[key] = val
	return config


### CLASSES ###

class WhatsappListenerClient:

	def __init__(self, keepAlive = False, sendReceipts = False):
		self.sendReceipts = sendReceipts

		connectionManager = YowsupConnectionManager()
		connectionManager.setAutoPong(keepAlive)
		self.signalsInterface = connectionManager.getSignalsInterface()
		self.methodsInterface = connectionManager.getMethodsInterface()

		# Configure the listeners
		self.signalsInterface.registerListener("message_received", self.onMessageReceived)
		self.signalsInterface.registerListener("group_messageReceived", self.onGroupMessageReceived)
		self.signalsInterface.registerListener("image_received", self.onImageReceived)
		self.signalsInterface.registerListener("group_imageReceived", self.onGroupImageReceived)
		self.signalsInterface.registerListener("auth_success", self.onAuthSuccess)
		self.signalsInterface.registerListener("auth_fail", self.onAuthFailed)
		self.signalsInterface.registerListener("disconnected", self.onDisconnected)

		self.cm = connectionManager

		# Create a printqueue so we won't print two things at the same time
		self.queue = Queue.Queue()

	def start(self, username, password):
		""" Logs in and starts the main thread that checks and processes
			the print queue.
		"""
		self.username = username
		self.methodsInterface.call("auth_login", (username, password))

		while True:
			# Sleep to keep thread responsive
			time.sleep(0.1)
			try:
				print self.queue.get(block=False)
			except Queue.Empty:
				pass

	def queueMessage(self, jid, timestamp, name, content):
		""" Adds a message to the print queue """
		print jid, timestamp, content
		formattedDate = datetime.datetime.fromtimestamp(timestamp).strftime('%d-%m-%Y %H:%M')
		output = "%s [%s]:%s"%(jid, formattedDate, content)
		output += '\n'
		self.queue.put(('text', output))

	def queueImage(self, jid, url):
		""" Adds an image to the print queue """
		print "Received Image"
		print url
		image = urllib2.urlopen(url).read()
		self.queue.put(('image', 'image.jpg'))

	def receipt(self, jid, messageId, wantsReceipt):
		""" Sends a read receipt if necessary 
		"""
		if wantsReceipt and self.sendReceipts:
			self.methodsInterface.call("message_ack", (jid, messageId))

	## SIGNAL HANDLERS ##
	def onAuthSuccess(self, username):
		print "Authed %s" % username
		self.methodsInterface.call("ready")

	def onAuthFailed(self, username, err):
		print "Auth Failed!"
		print username, err

	def onDisconnected(self, reason):
		print "Disconnected because %s" %reason

	def onGroupMessageReceived(self, messageId, jid, author, messageContent, timestamp, wantsReceipt, pushName):
		self.queueMessage(jid=jid, timestamp=timestamp, name=pushName, content=messageContent)
		self.receipt(jid, messageId, wantsReceipt)
		
	def onMessageReceived(self, messageId, jid, messageContent, timestamp, wantsReceipt, pushName):
		print messageId, jid, messageContent, timestamp, wantsReceipt, pushName
		self.queueMessage(jid=jid, timestamp=timestamp, name=pushName, content=messageContent)
		self.receipt(jid, messageId, wantsReceipt)
		
	def onImageReceived(self, messageId, jid, preview, url, size, wantsReceipt):
		self.queueImage(jid=jid, url=url)
		self.receipt(jid, messageId, wantsReceipt)

	def onGroupImageReceived(self, messageId, jid, author, preview, url, size, wantsReceipt):
		self.queueImage(jid=jid, url=url)
		self.receipt(jid, messageId, wantsReceipt)



if __name__ == '__main__':
	config = loadConfigFile('lebara.yowsupconfig')
	listener = WhatsappListenerClient(keepAlive=False, sendReceipts=True)
	listener.start(config['phone'], base64.b64decode(config['password']))
