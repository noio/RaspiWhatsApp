#!/usr/bin/env python

### IMPORTS ###

import os
import sys
import base64
import time
import datetime
import urllib2
import Queue
import StringIO

# LIBRARIES
import usb

yowsupdir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'yowsup', 'src')
sys.path.insert(0, yowsupdir)
escposdir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'python-escpos')
sys.path.insert(0, escposdir)

# LOCAL

import Image
import escpos
from Yowsup.connectionmanager import YowsupConnectionManager

### CONSTANTS ###

ACTION_TEXT = 'text'
ACTION_CHAT = 'chat'
ACTION_IMAGE = 'image'
ACTION_CUT = 'cut'
ACTION_FEED = 'feed'

TIMEOUT_CUT = 3 * 60 * 60
TIMEOUT_FEED = 30 * 60

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

	def __init__(self, keepAlive=False, sendReceipts=False, dryRun=False):
		self.sendReceipts = sendReceipts
		self.dryRun = dryRun

		# Initialize
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
		self.queue = Queue.PriorityQueue()
		self.history = []
		self.printer = None
		self.last_sender = None
		self.connected = False

	def start(self, username, password):
		""" Logs in and starts the main thread that checks and processes
			the print queue.
		"""
		self.username = username
		self.password = password
		self.connect()
		time.sleep(10)
		
		while True:
			print "Connection status: %s" % self.connected
			if not self.connected:
				print "Not connected..."
				self.connect()
				time.sleep(10)
			
			try:
				if not self.dryRun:
					if self.printer is None:
						self.printer = escpos.printer.Usb(0x04b8,0x0202)
						print "Initialized printer."
					else:
						# We have a printer, but we still try to poke it
						# to provoke an error if it is disconnected.
						self.printer.set()
				# At this point we are sure to have a working printer, 
				# so we can pop something from the queue and print it.
				self.processQueue()
				self.idleUpdate()
			except (usb.core.USBError, escpos.exceptions.NotFoundError) as e:
				print type(e)
				print "Failed to initialize printer: %s" % e
				self.printer = None

			# Sleep to keep thread responsive
			time.sleep(10)

	def connect(self):
		print "Connecting..."
		self.methodsInterface.call("auth_login", (self.username, self.password))


	def processQueue(self):
		try:
			# Pull an item from the queue
			stamp, action, item = self.queue.get(block=False)
			now = datetime.datetime.now()
			# Do something depending on its type
			if action in (ACTION_CHAT, ACTION_IMAGE):
				# If we just did a cut or feed, print a new timestamp
				if not self.history or self.history[-1][1] in (ACTION_FEED, ACTION_CUT):
					self.doPrint(ACTION_TEXT, stamp.strftime('%a %H:%M\n'))
					self.last_sender = None
				# Print the actual item
				if action == ACTION_CHAT:
					text = item[1][:150].decode('utf-8')
					user = item[0].decode('utf-8')
					# Check if last message was chat by same person
					if item[0] != self.last_sender:
						text = u'%s: %s\n' % (item[0], text)
					else:
						text = u'> %s\n' % (text,)
					self.last_sender = item[0]
					self.doPrint(ACTION_CHAT, text)

				if action == ACTION_IMAGE:
					imagedata = urllib2.urlopen(item).read()
					image = Image.open(StringIO.StringIO(imagedata))
					self.doPrint(ACTION_IMAGE, image)

			self.addHistory(now, action, item)
		except Queue.Empty:
			return False
			pass

	def idleUpdate(self):
		if not self.history:
			return
		now = datetime.datetime.now()
		diff = now - self.history[-1][0]
		# Line feed if time expired
		if (self.history[-1][1] not in (ACTION_FEED, ACTION_CUT) and
			diff > datetime.timedelta(seconds=TIMEOUT_FEED)):
			self.doPrint(ACTION_FEED)
			self.addHistory(now, ACTION_FEED, None)
		# Cut after longer time
		if (self.history[-1][1] != ACTION_CUT and
			diff > datetime.timedelta(seconds=TIMEOUT_CUT)):
			self.doPrint(ACTION_CUT)
			self.addHistory(now, ACTION_CUT, None)


	def doPrint(self, action, item=None):
		if self.dryRun:
			print "Printer[%s] %s" % (action, item)
			return
		if action in (ACTION_TEXT, ACTION_CHAT):
			self.printer.text(item.encode('ascii','replace'))
		if action == ACTION_IMAGE:
			self.printer.fullimage(item)
		if action == ACTION_FEED:
			self.printer.text('\n\n')
		if action == ACTION_CUT:
			self.printer.cut()

	def addHistory(self, timestamp, action, item):
		print timestamp, action, item
		self.history.append((timestamp, action, item))
	
	def queueMessage(self, jid, timestamp, name, content):
		""" Adds a message to the print queue """
		print jid, timestamp, content
		stamp = datetime.datetime.fromtimestamp(timestamp)
		self.queue.put((stamp, ACTION_CHAT, (name, content)))

	def queueImage(self, jid, url):
		""" Adds an image to the print queue """
		print "Received Image"
		print url
		stamp = datetime.datetime.now()
		self.queue.put((stamp, ACTION_IMAGE, url))

	def receipt(self, jid, messageId, wantsReceipt):
		""" Sends a read receipt if necessary 
		"""
		if wantsReceipt and self.sendReceipts:
			self.methodsInterface.call("message_ack", (jid, messageId))

	## SIGNAL HANDLERS ##
	def onAuthSuccess(self, username):
		print "Authed %s." % username
		self.methodsInterface.call("ready")
		self.connected = True

	def onAuthFailed(self, username, err):
		print "Auth failed."
		print username, err
		self.connected = False

	def onDisconnected(self, reason):
		print "Disconnected because %s" %reason
		self.connected = False

	def onGroupMessageReceived(self, messageId, jid, author, messageContent, timestamp, wantsReceipt, pushName):
		self.queueMessage(jid=jid, timestamp=timestamp, name=pushName, content=messageContent)
		self.receipt(jid, messageId, wantsReceipt)
		
	def onMessageReceived(self, messageId, jid, messageContent, timestamp, wantsReceipt, pushName):
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
	listener = WhatsappListenerClient(keepAlive=True, sendReceipts=True, dryRun=False)
	listener.start(config['phone'], base64.b64decode(config['password']))
