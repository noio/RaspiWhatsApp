#!/usr/bin/env python

### IMPORTS ###

import os
import sys
import base64
import time
import datetime
import urllib2

parentdir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'yowsup', 'src')
sys.path.insert(0,parentdir)

# LOCAL

from PIL import Image
from escpos import printer
from Yowsup.connectionmanager import YowsupConnectionManager

### CONSTANTS ###

COUNTRYCODE = '31'
PHONENUMBER = '31617414913'
PASSWORD = base64.b64decode('PHlhb+9DqepO0CYPPr2ZU1PibWA=')

### FUNCTIONS ###

def getCredentials(config):
	if os.path.isfile(config):
		f = open(config)
		
		phone = ""
		idx = ""
		pw = ""
		cc = ""
		
		try:
			for l in f:
				line = l.strip()
				if len(line) and line[0] not in ('#',';'):
					
					prep = line.split('#', 1)[0].split(';', 1)[0].split('=', 1)
					
					varname = prep[0].strip()
					val = prep[1].strip()
					
					if varname == "phone":
						phone = val
					elif varname == "id":
						idx = val
					elif varname =="password":
						pw = val
					elif varname == "cc":
						cc = val

			return (cc, phone, idx, pw);
		except:
			pass

	return 0

### CLASSES ###

class WhatsappListenerClient:

	def __init__(self, keepAlive = False, sendReceipts = False):
		self.sendReceipts = sendReceipts

		connectionManager = YowsupConnectionManager()
		connectionManager.setAutoPong(keepAlive)

		self.signalsInterface = connectionManager.getSignalsInterface()
		self.methodsInterface = connectionManager.getMethodsInterface()

		self.signalsInterface.registerListener("message_received", self.onMessageReceived)
		self.signalsInterface.registerListener("group_messageReceived", self.onGroupMessageReceived)
		self.signalsInterface.registerListener("image_received", self.onImageReceived)
		self.signalsInterface.registerListener("group_imageReceived", self.onGroupImageReceived)

		self.signalsInterface.registerListener("auth_success", self.onAuthSuccess)
		self.signalsInterface.registerListener("auth_fail", self.onAuthFailed)
		self.signalsInterface.registerListener("disconnected", self.onDisconnected)

		self.cm = connectionManager

		self.printer = printer.Usb(0x04b8,0x0202)

	def login(self, username, password):
		self.username = username
		self.methodsInterface.call("auth_login", (username, password))


		while True:
			raw_input()	

	def onAuthSuccess(self, username):
		print "Authed %s" % username
		self.methodsInterface.call("ready")

	def onAuthFailed(self, username, err):
		print "Auth Failed!"
		print username, err

	def onDisconnected(self, reason):
		print "Disconnected because %s" %reason

	def onGroupMessageReceived(self, messageId, jid, author, messageContent, timestamp, wantsReceipt, pushName):
		self.printMessage(jid, timestamp, messageContent)

		if wantsReceipt and self.sendReceipts:
			self.methodsInterface.call("message_ack", (jid, messageId))

	def onMessageReceived(self, messageId, jid, messageContent, timestamp, wantsReceipt, pushName):
		self.printMessage(jid, timestamp, messageContent)

		if wantsReceipt and self.sendReceipts:
			self.methodsInterface.call("message_ack", (jid, messageId))

	def onImageReceived(self, messageId, jid, preview, url, size, wantsReceipt, pushName):
		self.printImage(url=url)

	def onGroupImageReceived(self, messageId, jid, author, preview, url, size, wantsReceipt):
		self.printImage(url=url)

	def printMessage(self, jid, timestamp, content):
		print jid, timestamp, content
		formattedDate = datetime.datetime.fromtimestamp(timestamp).strftime('%d-%m-%Y %H:%M')
		output = "%s [%s]:%s"%(jid, formattedDate, content)
		output += '\n'
		self.printer.text(output)

	def printImage(self, url):
		print "Received Image"
		print url
		image = urllib2.urlopen(url).read()
		open('_im.jpg','wb').write(image)
		im = Image.open('_im.jpg')
		if im.size[1] > 255:
			ratio = 255. / im.size[1]
			h = int(ratio * im.size[0])
			im.thumbnail((h, 255), Image.ANTIALIAS)
			im.save('_imr.jpg')
		self.printer.image('_imr.jpg')

if __name__ == '__main__':
	listener = WhatsappListenerClient(keepAlive=False, sendReceipts=True)
	listener.login(PHONENUMBER, PASSWORD)
